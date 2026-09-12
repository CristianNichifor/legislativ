"""Project evidence pack assembled from local tracker and dossier data."""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path

from scripts import dosare, note_manuale, tracker_events

CONTRACT = "project-evidence-pack-v1"
TOKEN = re.compile(r"^[a-z0-9_.:/ -]{1,200}$", re.I)


def _text(value: object, *, limit: int = 200, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Text evidence pack invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Identificator proiect obligatoriu.")
    if len(value) > limit or "\x00" in value:
        raise ValueError("Text evidence pack invalid sau prea lung.")
    return value


def _token(value: object, *, required: bool = False) -> str:
    value = _text(value, required=required)
    if value and not TOKEN.fullmatch(value):
        raise ValueError("Identificator evidence pack invalid.")
    return value


def _limit(query: dict, key: str, default: int, maximum: int) -> int:
    try:
        value = int((query.get(key) or [str(default)])[0] or default)
    except (TypeError, ValueError) as exc:
        raise ValueError("Paginare evidence pack invalidă.") from exc
    if not 1 <= value <= maximum:
        raise ValueError("Paginare evidence pack invalidă.")
    return value


def _tracker(stare, project_id: str, limit: int) -> tuple[list[dict], list[str], str]:
    out = tracker_events.lista(stare, {"project_id": [project_id], "limit": [str(limit)]})
    return out["events"], out.get("limitari", []), out.get("source_status", "unknown")


def _lifecycle(stare, project_id: str) -> dict:
    with suppress(Exception):
        from scripts.lifecycle import project_lifecycle_summary

        out = project_lifecycle_summary(stare, query=project_id, limit=10, offset=0)
        return {
            "source_status": out.get("source_status", "ok"),
            "projects": out.get("projects", []),
        }
    return {"source_status": "unavailable", "projects": []}


def _notes(stare, dossier_id: str, project_id: str, limit: int) -> tuple[list[dict], list[str]]:
    if not dossier_id:
        return [], ["Nu a fost selectat un dosar local pentru notele de lucru."]
    path = dosare.cale(stare)
    if not Path(path).exists():
        return [], ["Depozitul local de dosare nu este inițializat."]
    try:
        out = note_manuale.lista(path, dossier_id)
    except ValueError:
        return [], ["Dosarul selectat nu este disponibil local."]
    notes = [
        note
        for note in out.get("note", [])
        if not note.get("act_id") or note.get("act_id") == project_id
    ]
    return notes[:limit], []


def build(stare, query: dict | None = None) -> dict:
    query = query or {}
    project_id = _token((query.get("project_id") or query.get("proiect") or [""])[0], required=True)
    dossier_id = _token((query.get("dossier_id") or query.get("dosar_id") or [""])[0])
    event_limit = _limit(query, "event_limit", 100, 200)
    note_limit = _limit(query, "note_limit", 25, 50)

    events, tracker_limitations, tracker_status = _tracker(stare, project_id, event_limit)
    lifecycle = _lifecycle(stare, project_id)
    notes, note_limitations = _notes(stare, dossier_id, project_id, note_limit)
    reviewed = sum(1 for event in events if event.get("review", {}).get("reviewed"))
    evidence_rows = [
        {
            "event_id": event["id"],
            "event_type": event["event_type"],
            "title": event["title"],
            "source_family": event["source_family"],
            "source_id": event.get("source_id", ""),
            "source_url": event.get("source_url", ""),
            "content_hash": event.get("content_hash", ""),
            "occurred_at": event["occurred_at"],
            "reviewed": bool(event.get("review", {}).get("reviewed")),
        }
        for event in events
    ]

    limitations = [
        "Pachetul este o sinteză locală pentru redactare și verificare, nu verdict juridic.",
        "Sursele lipsă sau nesincronizate pot ascunde etape ori avize relevante.",
        *tracker_limitations,
        *note_limitations,
    ]
    next_actions = []
    if events and reviewed < len(events):
        next_actions.append("Revizuiește evenimentele tracker nerevizuite înainte de redactare.")
    if not notes and dossier_id:
        next_actions.append("Creează o notă de dosar cu citat, sursă și raționament.")
    if not events:
        next_actions.append(
            "Sincronizează sursele proiectului sau verifică identificatorul proiectului."
        )

    return {
        "contract": CONTRACT,
        "project_id": project_id,
        "dossier_id": dossier_id,
        "source_status": "ok" if events else tracker_status,
        "summary": {
            "events": len(events),
            "reviewed_events": reviewed,
            "open_events": len(events) - reviewed,
            "notes": len(notes),
            "lifecycle_matches": len(lifecycle["projects"]),
        },
        "lifecycle": lifecycle,
        "events": events,
        "evidence": evidence_rows,
        "dossier_notes": notes,
        "next_actions": next_actions,
        "limitari": limitations,
    }
