"""Unified local attention feed for source, tracker and lifecycle work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from scripts import lifecycle, source_registry, tracker_events

CONTRACT = "legislative-attention-feed-v1"
MAX_LIMIT = 100


def _limit(query: dict | None) -> int:
    query = query or {}
    try:
        value = int((query.get("limit") or ["50"])[0] or 50)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limită feed atenție invalidă.") from exc
    if not 1 <= value <= MAX_LIMIT:
        raise ValueError("Limită feed atenție invalidă.")
    return value


def _source_items(stare, limit: int) -> list[dict[str, Any]]:
    try:
        out = source_registry.lista(stare)
    except (OSError, ValueError):
        return []
    items = []
    now = datetime.now(UTC)
    for row in out.get("sources", []):
        latest_snapshot = (row.get("snapshots") or [{}])[0]
        summary = latest_snapshot.get("summary") or {}
        deadline = lifecycle.deadline_attention(summary.get("deadline"), now=now)
        latest_change_types = {
            change.get("type") for change in (row.get("latest_change") or {}).get("changes", [])
        }
        has_attention_state = row.get("state", "") in source_registry.ATTENTION_STATES
        has_stage_or_deadline_change = bool(
            latest_change_types & {"deadline_changed", "consultation_closed"}
        )
        if not (has_attention_state or deadline["needs_attention"] or has_stage_or_deadline_change):
            continue
        if deadline["state"] in {"deadline_soon", "overdue"}:
            state = deadline["state"]
        elif has_stage_or_deadline_change:
            state = "stage_or_deadline_changed"
        else:
            state = row.get("state", "")
        items.append(
            {
                "kind": "source",
                "severity": "attention",
                "id": row.get("id", ""),
                "title": row.get("label") or row.get("identifier") or row.get("url") or "Sursă",
                "subtitle": source_registry.FAMILIES.get(
                    row.get("family", ""), row.get("family", "")
                ),
                "state": state,
                "deadline": deadline,
                "attention_label": _attention_label(state),
                "project_id": (
                    row.get("identifier", "")
                    if row.get("family") in source_registry.PROJECT_FAMILIES
                    else ""
                ),
                "source_family": row.get("family", ""),
                "source_id": row.get("id", ""),
                "source_url": row.get("url", ""),
                "updated_at": row.get("updated_at") or row.get("last_attempt_at") or "",
                "next_action": _source_next_action(state, row),
            }
        )
        if len(items) >= limit:
            break
    return items


def _attention_label(state: str) -> str:
    return {
        "deadline_soon": "Termen apropiat",
        "overdue": "Termen depășit",
        "stage_or_deadline_changed": "Schimbare stadiu/termen",
        "recent_stage_change": "Stadiu schimbat recent",
    }.get(state, "")


def _source_next_action(state: str, row: dict) -> str:
    if state == "deadline_soon":
        return "Verifică termenul apropiat din captura locală și decide dacă deschizi o revizie."
    if state == "overdue":
        return "Verifică dacă termenul depășit a fost închis sau prelungit în sursa oficială."
    if state == "stage_or_deadline_changed":
        return "Revizuiește schimbarea de stadiu/termen detectată între capturile locale."
    return (row.get("sync_status") or {}).get("next_action", "Verifică sursa")


def _tracker_items(stare, limit: int) -> list[dict[str, Any]]:
    try:
        out = tracker_events.lista(stare, {"reviewed": ["0"], "limit": [str(limit)]})
    except (OSError, ValueError):
        return []
    items = []
    for row in out.get("events", [])[:limit]:
        items.append(
            {
                "kind": "tracker_event",
                "severity": "attention",
                "id": row.get("id", ""),
                "title": row.get("display_label") or row.get("title") or row.get("event_label", ""),
                "subtitle": row.get("title", ""),
                "state": "stage_change",
                "attention_label": row.get("stage_label", ""),
                "project_id": row.get("project_id", ""),
                "source_family": row.get("source_family", ""),
                "source_id": row.get("source_id", ""),
                "source_url": row.get("source_url", ""),
                "updated_at": row.get("occurred_at") or row.get("observed_at") or "",
                "next_action": "Revizuiește evenimentul și atașează-l la dosar dacă e relevant.",
            }
        )
    return items


def _lifecycle_items(stare, limit: int) -> list[dict[str, Any]]:
    try:
        out = lifecycle.project_lifecycle_summary(stare, limit=limit)
    except (OSError, ValueError):
        return []
    items = []
    for row in out.get("projects", []):
        if not row.get("needs_attention"):
            continue
        stage = row.get("stage") or {}
        state = _lifecycle_attention_state(row)
        items.append(
            {
                "kind": "project_lifecycle",
                "severity": "attention",
                "id": row.get("project_id", ""),
                "title": row.get("title") or row.get("project_id", ""),
                "subtitle": f"{row.get('source_name', 'Proiect')} · {stage.get('label', '')}",
                "state": state,
                "attention_label": _attention_label(state),
                "deadline": row.get("deadline_attention") or {},
                "attention_reasons": row.get("attention_reasons") or [],
                "project_id": row.get("project_id", ""),
                "source_family": (row.get("registry_source") or {}).get("family", ""),
                "source_id": row.get("registry_source_id", ""),
                "source_url": row.get("url", ""),
                "updated_at": row.get("last_updated") or row.get("last_seen") or "",
                "next_action": _lifecycle_next_action(state),
            }
        )
    return items[:limit]


def _lifecycle_attention_state(row: dict) -> str:
    reasons = set(row.get("attention_reasons") or [])
    if "deadline_overdue" in reasons:
        return "overdue"
    if "deadline_soon" in reasons:
        return "deadline_soon"
    if "recent_stage_change" in reasons:
        return "recent_stage_change"
    if "registry_source" in reasons:
        return row.get("registry_source_state") or "registry_source"
    return row.get("source_state", "")


def _lifecycle_next_action(state: str) -> str:
    if state == "deadline_soon":
        return "Verifică termenul apropiat și pregătește revizia înainte de expirare."
    if state == "overdue":
        return "Verifică dacă termenul a fost închis, prelungit sau trebuie escaladat."
    if state == "recent_stage_change":
        return "Revizuiește schimbarea de stadiu și actualizează dosarele afectate."
    return "Sincronizează sau verifică stadiul proiectului."


def lista(stare, query: dict | None = None) -> dict:
    limit = _limit(query)
    items = [
        *_source_items(stare, limit),
        *_tracker_items(stare, limit),
        *_lifecycle_items(stare, limit),
    ]
    items.sort(
        key=lambda item: (item.get("updated_at") or "", item.get("kind") or ""),
        reverse=True,
    )
    items = items[:limit]
    counts: dict[str, int] = {}
    for item in items:
        kind = item["kind"]
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "contract": CONTRACT,
        "generated_at": datetime.now(UTC).isoformat(),
        "items": items,
        "total": len(items),
        "counts": counts,
        "limitari": [
            "Feed-ul combină doar starea locală: surse marcate cu atenție, "
            "evenimente tracker nerevizuite, schimbări de stadiu/termen și proiecte locale "
            "stale/necunoscute, fără fetch live."
        ],
    }
