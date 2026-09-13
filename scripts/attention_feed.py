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
        out = source_registry.lista(stare, {"attention": ["1"]})
    except (OSError, ValueError):
        return []
    items = []
    for row in out.get("sources", [])[:limit]:
        items.append(
            {
                "kind": "source",
                "severity": "attention",
                "id": row.get("id", ""),
                "title": row.get("label") or row.get("identifier") or row.get("url") or "Sursă",
                "subtitle": source_registry.FAMILIES.get(
                    row.get("family", ""), row.get("family", "")
                ),
                "state": row.get("state", ""),
                "project_id": (
                    row.get("identifier", "")
                    if row.get("family") in source_registry.PROJECT_FAMILIES
                    else ""
                ),
                "source_family": row.get("family", ""),
                "source_id": row.get("id", ""),
                "source_url": row.get("url", ""),
                "updated_at": row.get("updated_at") or row.get("last_attempt_at") or "",
                "next_action": (row.get("sync_status") or {}).get("next_action", "Verifică sursa"),
            }
        )
    return items


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
                "state": "unreviewed",
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
        items.append(
            {
                "kind": "project_lifecycle",
                "severity": "attention",
                "id": row.get("project_id", ""),
                "title": row.get("title") or row.get("project_id", ""),
                "subtitle": f"{row.get('source_name', 'Proiect')} · {stage.get('label', '')}",
                "state": row.get("source_state", ""),
                "project_id": row.get("project_id", ""),
                "source_family": (row.get("registry_source") or {}).get("family", ""),
                "source_id": row.get("registry_source_id", ""),
                "source_url": row.get("url", ""),
                "updated_at": row.get("last_updated") or row.get("last_seen") or "",
                "next_action": "Sincronizează sau verifică stadiul proiectului.",
            }
        )
    return items[:limit]


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
            "evenimente tracker nerevizuite și proiecte locale stale/necunoscute."
        ],
    }
