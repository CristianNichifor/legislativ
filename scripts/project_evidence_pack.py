"""Project evidence pack assembled from local tracker and dossier data."""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path

from scripts import dosare, note_manuale, tracker_events

CONTRACT = "project-evidence-pack-v1"
DRILLDOWN_CONTRACT = "evidence-drilldown-reference-v1"
TOKEN = re.compile(r"^[a-z0-9_.:/ -]{1,200}$", re.I)
CONSULTATION_FAMILIES = frozenset(
    {"consultare_guvern", "consultare_econsultare", "consultare_minister", "avize"}
)
MONITOR_FAMILIES = frozenset(
    {"monitorul_oficial", "monitorul_oficial_pi", "monitorul_oficial_other_parts"}
)

RELATED_PAYLOAD_KEYS = {
    "law_id": ("laws", "law_id"),
    "act_id": ("laws", "act_id"),
    "project_id": ("projects", "project_id"),
    "plx_id": ("projects", "plx_id"),
    "celex": ("celex", "celex"),
    "celex_id": ("celex", "celex_id"),
    "consultation_id": ("consultations", "consultation_id"),
    "consultare_id": ("consultations", "consultare_id"),
    "monitor_id": ("monitor_references", "monitor_id"),
    "monitor_number": ("monitor_references", "number"),
    "note_id": ("notes", "note_id"),
    "rule_id": ("rules", "rule_id"),
    "candidate_id": ("rules", "candidate_id"),
}


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


def _payload_text(payload: dict, *keys: str, limit: int = 1000) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:limit]
    return ""


def _source_state(source_url: str, source_hash: str, tracker_status: str) -> dict:
    if source_url and source_hash:
        state = "available"
        missing: list[str] = []
    elif source_url:
        state = "missing_hash"
        missing = ["source_hash"]
    elif source_hash:
        state = "missing_url"
        missing = ["source_url"]
    else:
        state = "missing_source"
        missing = ["source_url", "source_hash"]
    return {
        "state": state,
        "tracker_status": tracker_status or "unknown",
        "missing": missing,
        "message": (
            "Dovada are URL și hash de sursă."
            if state == "available"
            else "Dovada nu are încă o sursă completă; nu poate susține o concluzie."
        ),
    }


def _uncertainty(*, source_url: str, source_hash: str, quote: str, reviewed: bool) -> dict:
    reasons = []
    if not source_url:
        reasons.append("missing_source_url")
    if not source_hash:
        reasons.append("missing_source_hash")
    if not quote:
        reasons.append("missing_exact_quote")
    if not reviewed:
        reasons.append("human_review_pending")
    level = "low" if not reasons else "medium" if reviewed else "high"
    return {
        "level": level,
        "reasons": reasons,
        "message": (
            "Dovadă completă pentru drilldown și revizie umană."
            if not reasons
            else "Câmpuri lipsă sau revizie umană lipsă; folosește doar ca indiciu."
        ),
    }


def _append_related(related: dict, bucket: str, key: str, value: object, label: str = "") -> None:
    if not isinstance(value, str) or not value.strip():
        return
    item = {"id": value.strip(), "key": key}
    if label:
        item["label"] = label
    if item not in related[bucket]:
        related[bucket].append(item)


def _related_items(
    *,
    project_id: str,
    event_type: str = "",
    source_family: str = "",
    source_id: str = "",
    payload: dict | None = None,
    note: dict | None = None,
) -> dict:
    payload = payload or {}
    related: dict[str, list[dict]] = {
        "laws": [],
        "projects": [],
        "celex": [],
        "consultations": [],
        "monitor_references": [],
        "notes": [],
        "rules": [],
    }
    _append_related(related, "projects", "project_id", project_id)
    if source_id:
        bucket = "monitor_references" if source_family in MONITOR_FAMILIES else "projects"
        if source_family in CONSULTATION_FAMILIES:
            bucket = "consultations"
        elif source_family == "ue_cellar":
            bucket = "celex"
        _append_related(related, bucket, "source_id", source_id, source_family)
    for key, (bucket, related_key) in RELATED_PAYLOAD_KEYS.items():
        _append_related(related, bucket, related_key, payload.get(key))
    if source_family in CONSULTATION_FAMILIES:
        _append_related(related, "consultations", "project_id", project_id, event_type)
    if source_family in MONITOR_FAMILIES or event_type == "published_in_monitor":
        _append_related(related, "monitor_references", "project_id", project_id, event_type)
    if note:
        _append_related(related, "notes", "note_id", note.get("id"))
        _append_related(related, "laws", "act_id", note.get("act_id"))
    return related


def _event_drilldown(event: dict, tracker_status: str) -> dict:
    payload = event.get("payload") or {}
    source_url = event.get("source_url", "")
    source_hash = event.get("content_hash", "")
    reviewed = bool(event.get("review", {}).get("reviewed"))
    quote = _payload_text(
        payload,
        "quote",
        "evidence_quote",
        "source_quote",
        limit=1200,
    )
    return {
        "contract": DRILLDOWN_CONTRACT,
        "kind": "tracker_event",
        "id": event.get("id", ""),
        "event_id": event.get("id", ""),
        "title": event.get("title", ""),
        "quote": quote,
        "source_url": source_url,
        "source_hash": source_hash,
        "source_family": event.get("source_family", ""),
        "source_id": event.get("source_id", ""),
        "source_state": _source_state(source_url, source_hash, tracker_status),
        "lifecycle_state": {
            "event_type": event.get("event_type", ""),
            "stage_key": event.get("stage_key", ""),
            "stage_label": event.get("stage_label", ""),
            "occurred_at": event.get("occurred_at", ""),
            "reviewed": reviewed,
        },
        "uncertainty": _uncertainty(
            source_url=source_url,
            source_hash=source_hash,
            quote=quote,
            reviewed=reviewed,
        ),
        "related_items": _related_items(
            project_id=event.get("project_id", ""),
            event_type=event.get("event_type", ""),
            source_family=event.get("source_family", ""),
            source_id=event.get("source_id", ""),
            payload=payload,
        ),
        "not_legal_verdict": True,
        "limitations": [
            "Dovada indică o sursă de verificat; nu verdict juridic.",
            (
                "Absența unui câmp sursă înseamnă date locale incomplete, "
                "nu absența juridică a etapei."
            ),
        ],
    }


def _note_drilldown(note: dict) -> dict:
    source_url = note.get("source_url", "")
    source_hash = note.get("source_hash", "")
    quote = note.get("evidence_quote", "")
    reviewed = note.get("status") in {"reviewed", "ready_for_review"}
    return {
        "contract": DRILLDOWN_CONTRACT,
        "kind": "dossier_note",
        "id": note.get("id", ""),
        "note_id": note.get("id", ""),
        "title": note.get("title", ""),
        "quote": quote,
        "source_url": source_url,
        "source_hash": source_hash,
        "source_family": "",
        "source_id": "",
        "source_state": _source_state(source_url, source_hash, "local_dossier"),
        "lifecycle_state": {
            "event_type": "dossier_note",
            "stage_key": "human_review",
            "stage_label": note.get("status", ""),
            "occurred_at": note.get("modificat_la", "") or note.get("creat_la", ""),
            "reviewed": reviewed,
        },
        "uncertainty": _uncertainty(
            source_url=source_url,
            source_hash=source_hash,
            quote=quote,
            reviewed=reviewed,
        ),
        "related_items": _related_items(project_id=note.get("act_id", ""), note=note),
        "not_legal_verdict": True,
        "limitations": [
            "Nota de dosar este muncă locală privată și nu verdict juridic.",
            "Citatul, URL-ul și hash-ul trebuie verificate înainte de folosire în redactare.",
        ],
    }


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
    event_drilldowns = [_event_drilldown(event, tracker_status) for event in events]
    note_drilldowns = [_note_drilldown(note) for note in notes]
    evidence_rows = [
        {
            "event_id": event["id"],
            "event_type": event["event_type"],
            "title": event["title"],
            "source_family": event["source_family"],
            "source_id": event.get("source_id", ""),
            "source_url": event.get("source_url", ""),
            "content_hash": event.get("content_hash", ""),
            "source_hash": event.get("content_hash", ""),
            "quote": drilldown["quote"],
            "occurred_at": event["occurred_at"],
            "reviewed": bool(event.get("review", {}).get("reviewed")),
            "source_state": drilldown["source_state"],
            "uncertainty": drilldown["uncertainty"],
            "lifecycle_state": drilldown["lifecycle_state"],
            "related_items": drilldown["related_items"],
            "not_legal_verdict": True,
            "drilldown": drilldown,
        }
        for event, drilldown in zip(events, event_drilldowns, strict=True)
    ]
    consultation_rows = [
        {
            "event_id": event["id"],
            "event_type": event["event_type"],
            "source_family": event["source_family"],
            "title": event["title"],
            "authority": (event.get("payload") or {}).get("authority", ""),
            "deadline": (event.get("payload") or {}).get("deadline", ""),
            "status": (event.get("payload") or {}).get("status", ""),
            "source_url": event.get("source_url", ""),
            "reviewed": bool(event.get("review", {}).get("reviewed")),
        }
        for event in events
        if event.get("source_family") in CONSULTATION_FAMILIES
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
            "consultations": len(consultation_rows),
            "open_consultations": sum(1 for row in consultation_rows if not row["reviewed"]),
            "drilldown_records": len(event_drilldowns) + len(note_drilldowns),
            "missing_source_records": sum(
                1
                for row in [*event_drilldowns, *note_drilldowns]
                if row["source_state"]["state"] != "available"
            ),
            "missing_quote_records": sum(
                1 for row in [*event_drilldowns, *note_drilldowns] if not row["quote"]
            ),
        },
        "lifecycle": lifecycle,
        "events": events,
        "evidence": evidence_rows,
        "evidence_records": event_drilldowns,
        "consultations": consultation_rows,
        "dossier_notes": [
            {
                **note,
                "drilldown": drilldown,
                "source_state": drilldown["source_state"],
                "uncertainty": drilldown["uncertainty"],
                "related_items": drilldown["related_items"],
                "not_legal_verdict": True,
            }
            for note, drilldown in zip(notes, note_drilldowns, strict=True)
        ],
        "dossier_evidence_records": note_drilldowns,
        "next_actions": next_actions,
        "limitari": limitations,
    }
