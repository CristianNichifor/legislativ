"""Operational source tracker and lifecycle workbench assembled from local state."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts import attention_feed, lifecycle, source_registry, tracker_events

CONTRACT = "source-tracker-lifecycle-workbench-v1"
MAX_LIMIT = 100


def _limit(query: dict | None, key: str, default: int) -> int:
    query = query or {}
    try:
        value = int((query.get(key) or [str(default)])[0] or default)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limită workbench invalidă.") from exc
    if not 1 <= value <= MAX_LIMIT:
        raise ValueError("Limită workbench invalidă.")
    return value


def _source_row(row: dict) -> dict:
    status = row.get("sync_status") or {}
    impact = row.get("impact") or {}
    actions = impact.get("actions") or {}
    return {
        "kind": "source",
        "id": row.get("id", ""),
        "source_id": row.get("id", ""),
        "source_family": row.get("family", ""),
        "source_label": row.get("label") or row.get("identifier") or row.get("url") or "Sursă",
        "project_id": (
            row.get("identifier", "")
            if row.get("family") in source_registry.PROJECT_FAMILIES
            else ""
        ),
        "state": row.get("state", ""),
        "severity": status.get("severity", "attention"),
        "last_sync": row.get("last_attempt_at") or row.get("updated_at") or "",
        "last_error": row.get("last_error", ""),
        "content_hash": row.get("last_hash", ""),
        "parser_version": row.get("parser_version", ""),
        "official_url": row.get("url", ""),
        "changed": bool((row.get("latest_change") or {}).get("changes")),
        "change_summary": [
            change.get("type", "") for change in (row.get("latest_change") or {}).get("changes", [])
        ],
        "affected": impact.get("summary") or {},
        "actions": {
            "inspect": True,
            "retry_sync": bool(actions.get("retry_sync")),
            "review_source": bool(actions.get("mark_reviewed")),
            "open_evidence": bool(row.get("url")),
            "open_project": row.get("family") in source_registry.PROJECT_FAMILIES
            and bool(row.get("identifier")),
        },
        "next_action": status.get("next_action", ""),
    }


def _tracker_row(row: dict) -> dict:
    review = row.get("review") or {}
    return {
        "kind": "tracker_event",
        "id": row.get("id", ""),
        "source_id": row.get("source_id", ""),
        "source_family": row.get("source_family", ""),
        "source_label": row.get("source_family", "") or "tracker",
        "project_id": row.get("project_id", ""),
        "state": "unreviewed" if not review.get("reviewed") else "reviewed",
        "severity": "attention" if not review.get("reviewed") else "ok",
        "last_sync": row.get("occurred_at") or row.get("observed_at") or "",
        "content_hash": row.get("content_hash", ""),
        "official_url": row.get("source_url", ""),
        "title": row.get("title") or row.get("display_label") or row.get("event_label") or "",
        "stage": {
            "key": row.get("stage_key", ""),
            "label": row.get("stage_label", ""),
            "order": row.get("stage_order", 999),
        },
        "actions": {
            "review_event": not review.get("reviewed"),
            "create_note": bool(row.get("project_id")),
            "open_evidence": bool(row.get("source_url")),
            "open_project": bool(row.get("project_id")),
        },
        "next_action": "Revizuiește evenimentul și leagă-l la dosar dacă afectează redactarea.",
    }


def _project_row(row: dict) -> dict:
    source = row.get("registry_source") or {}
    deadline = row.get("deadline_attention") or {}
    return {
        "kind": "project_lifecycle",
        "id": row.get("project_id", ""),
        "source_id": row.get("registry_source_id", ""),
        "source_family": source.get("family", ""),
        "source_label": source.get("label") or row.get("source_name", ""),
        "project_id": row.get("project_id", ""),
        "title": row.get("title", ""),
        "state": row.get("registry_source_state") or row.get("source_state") or "unknown",
        "severity": "attention" if row.get("needs_attention") else "ok",
        "last_sync": (
            source.get("last_attempt_at") or row.get("last_updated") or row.get("last_seen") or ""
        ),
        "official_url": source.get("url") or row.get("url", ""),
        "stage": row.get("stage") or {},
        "deadline": deadline,
        "attention_reasons": row.get("attention_reasons") or [],
        "affected": {"affected_dossiers": row.get("affected_dossiers", 0)},
        "actions": {
            "retry_sync": bool(row.get("registry_can_sync"))
            and row.get("registry_source_state") in {"failed", "rate_limited"},
            "review_source": row.get("registry_source_state") in {"changed", "needs_review"},
            "open_evidence": bool(source.get("url") or row.get("url")),
            "open_project": bool(row.get("project_id")),
        },
        "next_action": _project_next_action(row, deadline),
    }


def _project_next_action(row: dict, deadline: dict) -> str:
    if deadline.get("state") == "overdue":
        return "Verifică termenul depășit și actualizează dosarul de lucru."
    if deadline.get("state") == "deadline_soon":
        return "Verifică termenul apropiat înainte de închiderea reviziei."
    if row.get("registry_source_state") in {"changed", "needs_review"}:
        return "Revizuiește sursa urmărită și dosarele afectate."
    if row.get("registry_can_sync"):
        return "Sincronizează explicit sursa dacă datele locale sunt vechi."
    return "Verifică stadiul local și evenimentele tracker asociate."


def _actions(rows: list[dict], *, attention_total: int) -> list[dict]:
    unreviewed = sum(
        1 for row in rows if row["kind"] == "tracker_event" and row["state"] == "unreviewed"
    )
    sources_to_review = sum(1 for row in rows if row["actions"].get("review_source"))
    retryable = sum(1 for row in rows if row["actions"].get("retry_sync"))
    lifecycle_attention = sum(
        1 for row in rows if row["kind"] == "project_lifecycle" and row["severity"] == "attention"
    )
    actions = []
    if unreviewed:
        actions.append(
            {
                "key": "review_tracker_events",
                "label": "Revizuiește evenimentele tracker nerevizuite.",
                "count": unreviewed,
            }
        )
    if sources_to_review:
        actions.append(
            {
                "key": "review_changed_sources",
                "label": "Închide reviziile de surse schimbate numai după verificarea impactului.",
                "count": sources_to_review,
            }
        )
    if retryable:
        actions.append(
            {
                "key": "retry_failed_sources",
                "label": "Reîncearcă sursele eșuate sau limitate, câte una.",
                "count": retryable,
            }
        )
    if lifecycle_attention:
        actions.append(
            {
                "key": "inspect_lifecycle",
                "label": "Verifică proiectele cu termen, stadiu necunoscut sau sursă veche.",
                "count": lifecycle_attention,
            }
        )
    if attention_total and not actions:
        actions.append(
            {
                "key": "inspect_attention_feed",
                "label": "Deschide feed-ul de atenție pentru elementele locale rămase.",
                "count": attention_total,
            }
        )
    return actions[:8]


def build(stare, query: dict | None = None) -> dict:
    source_limit = _limit(query, "source_limit", 25)
    event_limit = _limit(query, "event_limit", 25)
    project_limit = _limit(query, "project_limit", 25)
    now = datetime.now(UTC).isoformat()

    registry = source_registry.lista(stare, {"attention": ["1"], "offset": ["0"]})
    tracker = tracker_events.lista(
        stare, {"reviewed": ["0"], "limit": [str(event_limit)], "offset": ["0"]}
    )
    projects = lifecycle.project_lifecycle_summary(stare, limit=project_limit, offset=0)
    attention = attention_feed.lista(stare, {"limit": [str(MAX_LIMIT)]})

    rows = [
        *[_source_row(row) for row in (registry.get("sources") or [])[:source_limit]],
        *[_tracker_row(row) for row in tracker.get("events", [])],
        *[_project_row(row) for row in projects.get("projects", []) if row.get("needs_attention")],
    ]
    rows.sort(key=lambda row: (row.get("last_sync") or "", row.get("kind") or ""), reverse=True)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    attention_total = int(attention.get("total") or 0)
    summary = {
        "attention_items": attention_total,
        "sources_attention": len(registry.get("sources") or []),
        "tracker_unreviewed": int(tracker.get("total") or 0),
        "projects_attention": sum(
            1 for row in projects.get("projects", []) if row.get("needs_attention")
        ),
        "retryable_sources": sum(1 for row in rows if row.get("actions", {}).get("retry_sync")),
        "reviewable_sources": sum(1 for row in rows if row.get("actions", {}).get("review_source")),
        "evidence_links": sum(
            1 for row in rows if row.get("official_url") or row.get("content_hash")
        ),
    }

    return {
        "contract": CONTRACT,
        "generated_at": now,
        "summary": summary,
        "counts": counts,
        "rows": rows[:MAX_LIMIT],
        "next_actions": _actions(rows, attention_total=attention_total),
        "source_status": {
            "registry": "ok",
            "tracker": tracker.get("source_status", "unknown"),
            "lifecycle": projects.get("source_status", "unknown"),
        },
        "limitari": [
            "Workbench-ul citește numai starea locală: nu pornește crawling sau rebuild.",
            "Acțiunile de retry/review folosesc endpointurile existente și rămân explicite.",
            *registry.get("limitari", []),
            *tracker.get("limitari", []),
            *projects.get("limitari", []),
            *attention.get("limitari", []),
        ],
    }
