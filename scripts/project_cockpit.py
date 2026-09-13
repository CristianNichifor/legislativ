"""Backend project cockpit for legislative workflow review."""

from __future__ import annotations

import re
from contextlib import suppress

from scripts import project_evidence_pack, tracker_events
from scripts.lifecycle import project_lifecycle_summary

CONTRACT = "project-cockpit-summary-v1"
TOKEN = re.compile(r"^[a-z0-9_.:/ -]{1,200}$", re.I)


def _text(value: object, *, limit: int = 200, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Text cockpit invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Identificator proiect obligatoriu.")
    if len(value) > limit or "\x00" in value:
        raise ValueError("Text cockpit invalid sau prea lung.")
    return value


def _token(value: object, *, required: bool = False) -> str:
    value = _text(value, required=required)
    if value and not TOKEN.fullmatch(value):
        raise ValueError("Identificator proiect invalid.")
    return value


def _limit(query: dict, key: str, default: int, maximum: int) -> int:
    try:
        value = int((query.get(key) or [str(default)])[0] or default)
    except (TypeError, ValueError) as exc:
        raise ValueError("Paginare cockpit invalidă.") from exc
    if not 1 <= value <= maximum:
        raise ValueError("Paginare cockpit invalidă.")
    return value


def _first_lifecycle_project(lifecycle: dict, project_id: str) -> dict:
    projects = lifecycle.get("projects") or []
    for project in projects:
        if project.get("project_id") == project_id:
            return project
    return projects[0] if projects else {}


def _tracker_summary(events: list[dict], total: int) -> dict:
    reviewed = sum(1 for event in events if event.get("review", {}).get("reviewed"))
    by_type: dict[str, int] = {}
    for event in events:
        event_type = event.get("event_type") or "unknown"
        by_type[event_type] = by_type.get(event_type, 0) + 1
    return {
        "total": total,
        "returned": len(events),
        "reviewed": reviewed,
        "unreviewed": max(0, len(events) - reviewed),
        "by_type": by_type,
        "latest_event": events[0] if events else None,
    }


def _source_attention(project: dict) -> dict:
    state = project.get("registry_source_state") or project.get("source_state") or "unknown"
    return {
        "needs_attention": bool(project.get("needs_attention")),
        "source_state": project.get("source_state") or "unknown",
        "registry_source_id": project.get("registry_source_id") or "",
        "registry_source_state": project.get("registry_source_state") or "",
        "registry_can_sync": bool(project.get("registry_can_sync")),
        "attention_state": state,
        "uncertainty": project.get("uncertainty") or {},
    }


def _evidence_summary(pack: dict) -> dict:
    summary = pack.get("summary") or {}
    return {
        "available": bool(pack) and "error" not in pack,
        "contract": pack.get("contract", ""),
        "events": int(summary.get("events") or 0),
        "reviewed_events": int(summary.get("reviewed_events") or 0),
        "open_events": int(summary.get("open_events") or 0),
        "notes": int(summary.get("notes") or 0),
        "evidence_rows": len(pack.get("evidence") or []),
    }


def _next_actions(
    *,
    tracker_summary: dict,
    source_attention: dict,
    evidence_summary: dict,
    evidence_pack: dict,
    dossier_id: str,
) -> list[dict]:
    actions: list[dict] = []
    if tracker_summary["unreviewed"]:
        actions.append(
            {
                "key": "review_tracker_events",
                "label": "Revizuiește evenimentele tracker nerevizuite.",
                "reason": "Evenimentele pot indica avize, voturi, rapoarte sau consultări.",
                "count": tracker_summary["unreviewed"],
            }
        )
    if source_attention["needs_attention"] or source_attention["attention_state"] in {
        "changed",
        "failed",
        "stale",
        "unknown",
        "unavailable",
    }:
        actions.append(
            {
                "key": "sync_attention_sources",
                "label": "Sincronizează sau verifică sursele cu atenție.",
                "reason": "Sursele nesincronizate pot ascunde etape, avize ori publicări.",
                "source_id": source_attention["registry_source_id"],
            }
        )
    if dossier_id and evidence_summary["notes"] == 0:
        actions.append(
            {
                "key": "create_dossier_note",
                "label": "Creează sau leagă note de dosar pentru lacune și observații.",
                "reason": "Redactarea are nevoie de citat, sursă și raționament lângă proiect.",
            }
        )
    elif not dossier_id:
        actions.append(
            {
                "key": "link_dossier",
                "label": "Leagă proiectul de un dosar local de lucru.",
                "reason": "Fără dosar, observațiile de redactare rămân separate de proiect.",
            }
        )
    if evidence_summary["available"]:
        actions.append(
            {
                "key": "open_evidence_pack",
                "label": "Deschide pachetul de evidență înainte de concluzii.",
                "reason": "Pachetul grupează evenimentele, sursele și notele locale.",
                "open_events": evidence_summary["open_events"],
            }
        )
    actions.extend(
        {
            "key": "evidence_pack_next_action",
            "label": item,
            "reason": "Acțiune recomandată de pachetul local de evidență.",
        }
        for item in evidence_pack.get("next_actions", [])
        if item
    )
    deduped = []
    seen = set()
    for action in actions:
        key = (action["key"], action["label"])
        if key not in seen:
            seen.add(key)
            deduped.append(action)
    return deduped[:8]


def build(stare, query: dict | None = None) -> dict:
    query = query or {}
    project_id = _token((query.get("project_id") or query.get("proiect") or [""])[0], required=True)
    dossier_id = _token((query.get("dossier_id") or query.get("dosar_id") or [""])[0])
    event_limit = _limit(query, "event_limit", 50, 100)
    stale_days = _limit(query, "stale_days", 30, 3660)

    lifecycle = project_lifecycle_summary(
        stare, query=project_id, limit=10, offset=0, stale_days=stale_days
    )
    project = _first_lifecycle_project(lifecycle, project_id)
    tracker = tracker_events.lista(
        stare, {"project_id": [project_id], "limit": [str(event_limit)], "offset": ["0"]}
    )
    evidence_pack = {}
    with suppress(Exception):
        evidence_pack = project_evidence_pack.build(
            stare,
            {
                "project_id": [project_id],
                "dossier_id": [dossier_id],
                "event_limit": [str(event_limit)],
                "note_limit": ["10"],
            },
        )

    tracker_info = _tracker_summary(tracker.get("events", []), int(tracker.get("total") or 0))
    source_info = _source_attention(project)
    evidence_info = _evidence_summary(evidence_pack)
    limitations = [
        "Cockpit-ul combină date locale sincronizate și poate fi incomplet.",
        "Rezultatele sunt pentru redactare și revizie legislativă; nu reprezintă verdict juridic.",
        "Sursele publice nesincronizate, indisponibile sau schimbate pot lipsi din sumar.",
        *lifecycle.get("limitari", []),
        *tracker.get("limitari", []),
        *evidence_pack.get("limitari", []),
    ]

    return {
        "contract": CONTRACT,
        "project_id": project_id,
        "dossier_id": dossier_id,
        "source_status": lifecycle.get("source_status", "unknown"),
        "lifecycle": {
            "source_status": lifecycle.get("source_status", "unknown"),
            "total": lifecycle.get("total", 0),
            "returned": lifecycle.get("returned", 0),
            "project": project or None,
        },
        "tracker": tracker_info,
        "source_attention": source_info,
        "evidence_pack": evidence_info,
        "next_actions": _next_actions(
            tracker_summary=tracker_info,
            source_attention=source_info,
            evidence_summary=evidence_info,
            evidence_pack=evidence_pack,
            dossier_id=dossier_id,
        ),
        "limitari": list(dict.fromkeys(limitations)),
    }
