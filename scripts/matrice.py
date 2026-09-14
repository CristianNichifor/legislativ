"""Central matrix workspace contract.

This module keeps the product-facing matrix payload separate from the SQL-heavy matrix queries in
``servicii``. It only normalizes already-known local evidence into honest work states.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

WORKSPACE_CONTRACT = "law-matrix-workspace-v2"
ITEM_STATES = ("evidence-backed", "missing-source", "needs-review", "unsupported")
ITEM_KINDS = (
    "manual_note",
    "deterministic_candidate",
    "eu_risk",
    "lifecycle_source",
    "rule_candidate",
)


def _empty_counts() -> dict[str, Any]:
    return {
        "total": 0,
        "by_state": {state: 0 for state in ITEM_STATES},
        "by_kind": {kind: 0 for kind in ITEM_KINDS},
    }


def _add(counts: dict[str, Any], item: dict[str, Any]) -> None:
    counts["total"] += 1
    counts["by_state"][item["state"]] = counts["by_state"].get(item["state"], 0) + 1
    counts["by_kind"][item["kind"]] = counts["by_kind"].get(item["kind"], 0) + 1


def _source_state(source: dict[str, Any]) -> str:
    if source.get("missing") or source.get("stale") or source.get("partial"):
        return "missing-source"
    if source.get("attention") or source.get("reviewable"):
        return "needs-review"
    if source.get("loaded") or source.get("current"):
        return "evidence-backed"
    return "unsupported"


def _note_state(row: sqlite3.Row) -> str:
    if not row["sursa_url"] or not row["sursa_sha256"] or not row["citat_dovada"]:
        return "missing-source"
    if row["stare"] in {"reviewed", "accepted"}:
        return "evidence-backed"
    return "needs-review"


def _rule_state(candidate: dict[str, Any]) -> str:
    if candidate.get("status") == "not_codeable":
        return "unsupported"
    if not candidate.get("source_hash"):
        return "missing-source"
    if candidate.get("review_state") in {"human_reviewed", "legally_validated"}:
        return "evidence-backed"
    return "needs-review"


def _source_registry_state(row: sqlite3.Row) -> str:
    state = row["state"]
    if state in {"fetched", "unchanged"} and row["last_hash"]:
        return "evidence-backed"
    if state in {"failed", "rate_limited", "unavailable", "discovered", "queued"}:
        return "missing-source"
    if state in {"changed", "needs_review"}:
        return "needs-review"
    return "unsupported"


def _tracker_state(row: sqlite3.Row, reviewed: bool) -> str:
    if row["content_hash"]:
        return "evidence-backed" if reviewed else "needs-review"
    if row["source_url"]:
        return "needs-review"
    return "missing-source"


def _deterministic_items(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        emitent = row.get("emitent") or ""
        source_state = _source_state(row.get("source_quality") or {})
        for key, label in (
            ("viduri", "Lacună normativă candidată"),
            ("neconstitutionale", "CCR nereparat candidat"),
            ("contradictii", "Contradicție candidată"),
            ("initiative_in_lucru", "Proiect în procedură"),
            ("amendamente_primite", "Presiune de amendare"),
        ):
            count = int((row.get("semnale") or {}).get(key) or 0)
            if count <= 0:
                continue
            if source_state not in {"evidence-backed", "missing-source", "unsupported"}:
                source_state = "needs-review"
            items.append(
                {
                    "id": f"deterministic:{emitent}:{key}",
                    "kind": "deterministic_candidate",
                    "state": source_state,
                    "title": label,
                    "scope": emitent,
                    "count": count,
                    "evidence": {
                        "matrix_row": emitent,
                        "examples": (row.get("exemple") or {}).get(
                            "viduri" if key == "viduri" else "neconstitutionale", []
                        )[:3],
                    },
                    "not_legal_verdict": True,
                }
            )
            if len(items) >= limit:
                return items
    return items


def _private_items(path: Path | None, limit: int) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            tables = {
                row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "note_manuale" in tables:
                for row in con.execute(
                    "SELECT id,dosar_id,titlu,tip,act_id,locator,citat_dovada,sursa_url,"
                    "sursa_sha256,stare,modificat_la FROM note_manuale "
                    "ORDER BY modificat_la DESC,id LIMIT ?",
                    (limit,),
                ):
                    items.append(
                        {
                            "id": f"note:{row['id']}",
                            "kind": "manual_note",
                            "state": _note_state(row),
                            "title": row["titlu"],
                            "scope": row["act_id"],
                            "dossier_id": row["dosar_id"],
                            "locator": row["locator"],
                            "note_type": row["tip"],
                            "review_state": row["stare"],
                            "source_url": row["sursa_url"],
                            "source_hash": row["sursa_sha256"],
                            "not_legal_verdict": True,
                        }
                    )
            remaining = max(0, limit - len(items))
            if remaining and "rule_candidate_queue" in tables:
                for row in con.execute(
                    "SELECT id,dosar_id,candidate_id,act_id,locator,status,review_state,"
                    "source_hash,payload_json,creat_la FROM rule_candidate_queue "
                    "ORDER BY creat_la DESC,id LIMIT ?",
                    (remaining,),
                ):
                    candidate = json.loads(row["payload_json"])
                    items.append(
                        {
                            "id": f"rule:{row['id']}",
                            "kind": "rule_candidate",
                            "state": _rule_state(candidate),
                            "title": candidate.get("action") or row["candidate_id"],
                            "scope": row["act_id"],
                            "dossier_id": row["dosar_id"],
                            "locator": row["locator"],
                            "candidate_id": row["candidate_id"],
                            "review_state": row["review_state"],
                            "source_hash": row["source_hash"],
                            "not_legal_verdict": True,
                        }
                    )
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError):
        return []
    return items[:limit]


def _source_items(path: Path | None, limit: int) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            for row in con.execute(
                "SELECT id,family,identifier,url,label,state,last_hash,updated_at "
                "FROM source_registry ORDER BY updated_at DESC,id LIMIT ?",
                (limit,),
            ):
                items.append(
                    {
                        "id": f"source:{row['id']}",
                        "kind": "lifecycle_source",
                        "state": _source_registry_state(row),
                        "title": row["label"],
                        "scope": row["identifier"],
                        "source_family": row["family"],
                        "source_url": row["url"],
                        "source_hash": row["last_hash"],
                        "source_state": row["state"],
                        "not_legal_verdict": True,
                    }
                )
    except (OSError, sqlite3.Error, ValueError):
        return []
    return items


def _tracker_items(path: Path | None, limit: int) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            for row in con.execute(
                "SELECT e.id,e.event_type,e.project_id,e.source_family,e.source_url,e.title,"
                "e.content_hash,e.occurred_at,r.event_id reviewed_id "
                "FROM tracker_events e LEFT JOIN tracker_event_reviews r ON r.event_id=e.id "
                "ORDER BY e.occurred_at DESC,e.id LIMIT ?",
                (limit,),
            ):
                items.append(
                    {
                        "id": f"tracker:{row['id']}",
                        "kind": "lifecycle_source",
                        "state": _tracker_state(row, bool(row["reviewed_id"])),
                        "title": row["title"],
                        "scope": row["project_id"],
                        "event_type": row["event_type"],
                        "source_family": row["source_family"],
                        "source_url": row["source_url"],
                        "source_hash": row["content_hash"],
                        "reviewed": bool(row["reviewed_id"]),
                        "not_legal_verdict": True,
                    }
                )
    except (OSError, sqlite3.Error, ValueError):
        return []
    return items


def _eu_items(references: list[dict[str, Any]], scope: str, limit: int) -> list[dict[str, Any]]:
    items = []
    for ref in references[:limit]:
        items.append(
            {
                "id": f"eu:{scope}:{ref.get('celex', '')}",
                "kind": "eu_risk",
                "state": "evidence-backed" if ref.get("importat") else "missing-source",
                "title": ref.get("titlu") or ref.get("celex") or "Referință UE",
                "scope": scope,
                "celex": ref.get("celex", ""),
                "mentions": ref.get("mentionari", 0),
                "imported": bool(ref.get("importat")),
                "not_legal_verdict": True,
            }
        )
    return items


def build_workspace(
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    filters: dict[str, Any],
    private_path: Path | None,
    source_registry_path: Path | None,
    tracker_path: Path | None,
    eu_references: list[dict[str, Any]] | None = None,
    eu_scope: str = "matrix",
    status: str = "work_ready",
    limit: int = 40,
) -> dict[str, Any]:
    """Build the single product-facing matrix workspace payload."""
    limit = max(1, min(int(limit), 100))
    items = [
        *_deterministic_items(rows, limit),
        *_eu_items(eu_references or [], eu_scope, limit),
        *_private_items(private_path, limit),
        *_source_items(source_registry_path, limit),
        *_tracker_items(tracker_path, limit),
    ][:limit]
    counts = _empty_counts()
    for item in items:
        _add(counts, item)
    return {
        "contract": WORKSPACE_CONTRACT,
        "status": status if items else "needs_sources",
        "states": [
            {"key": "evidence-backed", "label": "susținut de dovezi locale"},
            {"key": "missing-source", "label": "sursă lipsă sau incompletă"},
            {"key": "needs-review", "label": "necesită revizie umană"},
            {"key": "unsupported", "label": "nesuportat de datele locale"},
        ],
        "active_filters": {
            "review_state": filters.get("review_state") or "",
            "source_family": filters.get("source_family") or "",
            "lifecycle_state": filters.get("lifecycle_state") or "",
        },
        "counts": counts,
        "summary": {
            "matrix_rows": len(rows),
            "matrix_signals": sum(
                int((row.get("semnale") or {}).get(key) or 0)
                for row in rows
                for key in (
                    "viduri",
                    "neconstitutionale",
                    "contradictii",
                    "initiative_in_lucru",
                    "amendamente_primite",
                )
            ),
            "source_attention": summary.get("surse_atentie", 0),
            "source_missing": summary.get("surse_lipsa", 0),
        },
        "items": items,
        "limitari": [
            "Contractul agregă doar dovezi și stări locale existente.",
            "Starea unsupported înseamnă nesuportat de datele locale, nu concluzie juridică.",
            "Toate intrările sunt candidați de lucru; nu verdict juridic.",
        ],
        "not_legal_verdict": True,
    }
