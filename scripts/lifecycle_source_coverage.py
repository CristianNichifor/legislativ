"""Per-project public source coverage for legislative tracking."""

from __future__ import annotations

import re

from scripts import source_freshness, source_registry, tracker_events

CONTRACT = "project-source-coverage-v1"
TOKEN = re.compile(r"^[a-z0-9_.:/ -]{1,200}$", re.I)
PROJECT_SOURCE_GROUPS = (
    ("parliament", "Parlament", ("parlament", "camera", "senat")),
    (
        "consultations",
        "Consultări publice",
        ("consultare_guvern", "consultare_econsultare", "consultare_minister"),
    ),
    ("opinions", "Avize", ("avize",)),
    ("eu", "Drept UE", ("ue_cellar",)),
    ("monitor", "Monitorul Oficial", ("monitorul_oficial_pi",)),
)
ATTENTION_STATES = source_registry.ATTENTION_STATES | frozenset({"unavailable"})
DEFAULT_STALE_DAYS = 30


def _text(value: object, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Identificator proiect invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Identificator proiect obligatoriu.")
    if len(value) > 200 or "\x00" in value or (value and not TOKEN.fullmatch(value)):
        raise ValueError("Identificator proiect invalid.")
    return value


def _limit(query: dict | None, key: str, default: int, maximum: int) -> int:
    query = query or {}
    try:
        value = int((query.get(key) or [str(default)])[0] or default)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limită acoperire proiect invalidă.") from exc
    if not 1 <= value <= maximum:
        raise ValueError("Limită acoperire proiect invalidă.")
    return value


def _events(stare, project_id: str, limit: int) -> list[dict]:
    try:
        out = tracker_events.lista(stare, {"project_id": [project_id], "limit": [str(limit)]})
    except (OSError, ValueError):
        return []
    return out.get("events", [])


def _registry_sources(stare, project_id: str) -> list[dict]:
    try:
        rows = source_registry.lista(stare, {"limit": ["200"]}).get("sources", [])
    except (OSError, ValueError):
        return []
    needle = project_id.lower()
    return [
        row
        for row in rows
        if needle
        and (
            needle in str(row.get("identifier") or "").lower()
            or needle in str(row.get("label") or "").lower()
            or needle in str(row.get("url") or "").lower()
        )
    ]


def _family_state(family: str, sources: list[dict], events: list[dict], *, stale_days: int) -> dict:
    source_matches = [row for row in sources if row.get("family") == family]
    event_matches = [row for row in events if row.get("source_family") == family]
    attention = [
        row
        for row in source_matches
        if row.get("state") in ATTENTION_STATES
        or (row.get("sync_status") or {}).get("severity") in {"attention", "blocked"}
    ]
    if attention:
        state = "needs_review"
    elif source_matches or event_matches:
        state = "present"
    else:
        state = "missing"
    if attention:
        freshness = source_freshness.state_payload(
            "needs_review",
            reason="Sursa sau evenimentele locale cer revizie înainte de concluzii.",
            stale_days=stale_days,
        )
    elif source_matches:
        freshness = (source_matches[0].get("sync_status") or {}).get(
            "freshness_status"
        ) or source_freshness.for_registry_row(source_matches[0], stale_days=stale_days)
    elif event_matches:
        freshness = source_freshness.state_payload(
            "current",
            reason="Există cel puțin un eveniment tracker local pentru această familie.",
            stale_days=stale_days,
        )
    else:
        freshness = source_freshness.state_payload(
            "missing",
            reason="Nu există sursă în registru și nici eveniment tracker local.",
            missing=[family],
            stale_days=stale_days,
        )
    return {
        "family": family,
        "label": source_registry.families().get(family, family),
        "state": state,
        "freshness": freshness,
        "freshness_state": freshness["state"],
        "sources": len(source_matches),
        "events": len(event_matches),
        "latest_state": source_matches[0].get("state", "") if source_matches else "",
        "source_id": source_matches[0].get("id", "") if source_matches else "",
        "source_url": (
            source_matches[0].get("url", "")
            if source_matches
            else event_matches[0].get("source_url", "")
            if event_matches
            else ""
        ),
    }


def build(stare, query: dict | None = None) -> dict:
    query = query or {}
    project_id = _text((query.get("project_id") or query.get("proiect") or [""])[0], required=True)
    event_limit = _limit(query, "event_limit", 100, 200)
    stale_days = _limit(query, "stale_days", DEFAULT_STALE_DAYS, 3660)
    events = _events(stare, project_id, event_limit)
    sources = _registry_sources(stare, project_id)
    groups = []
    for key, label, families in PROJECT_SOURCE_GROUPS:
        rows = [
            _family_state(family, sources, events, stale_days=stale_days) for family in families
        ]
        state = (
            "needs_review"
            if any(row["state"] == "needs_review" for row in rows)
            else "present"
            if any(row["state"] == "present" for row in rows)
            else "missing"
        )
        freshness = source_freshness.for_coverage_group(rows, stale_days=stale_days)
        groups.append(
            {
                "key": key,
                "label": label,
                "state": state,
                "freshness": freshness,
                "freshness_state": freshness["state"],
                "families": rows,
                "present": sum(1 for row in rows if row["state"] == "present"),
                "needs_review": sum(1 for row in rows if row["state"] == "needs_review"),
                "missing": sum(1 for row in rows if row["state"] == "missing"),
            }
        )
    missing = sum(group["missing"] for group in groups)
    review = sum(group["needs_review"] for group in groups)
    freshness_counts = {state: 0 for state in source_freshness.FRESHNESS_STATES}
    for group in groups:
        freshness_counts[group["freshness_state"]] += 1
    return {
        "contract": CONTRACT,
        "project_id": project_id,
        "summary": {
            "groups": len(groups),
            "present_groups": sum(1 for group in groups if group["state"] == "present"),
            "missing_families": missing,
            "needs_review_families": review,
            "freshness_states": freshness_counts,
            "events": len(events),
            "sources": len(sources),
        },
        "groups": groups,
        "source_freshness_states": freshness_counts,
        "status": "needs_review" if review else "missing" if missing else "ok",
        "next_actions": [
            "Adaugă sau sincronizează sursele lipsă pentru proiect." if missing else "",
            "Revizuiește sursele schimbate înainte de redactare." if review else "",
        ],
        "limitari": [
            "Acoperirea este locală: folosește registrul și trackerul existente, fără crawling.",
            "Prezența unei familii de surse nu confirmă acuratețea juridică.",
        ],
    }
