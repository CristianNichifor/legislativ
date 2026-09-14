"""Read-only feed of locally registered public consultation sources."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import date

from scripts import source_registry

CONTRACT = "consultation-feed-v1"
FAMILIES = ("consultare_econsultare", "consultare_guvern", "consultare_minister")
DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
STATUSES = {"open": 0, "unknown": 1, "closed": 2}


def _iso_deadline(value: str) -> str:
    value = str(value or "").strip()
    match = DATE.match(value)
    if not match:
        return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _status(value: str) -> str:
    value = str(value or "unknown").strip().lower()
    return value if value in STATUSES else "unknown"


def _missing_fields(summary: dict, status: str, deadline: str) -> list[str]:
    missing = []
    if not (summary.get("title") or "").strip():
        missing.append("title")
    if not (summary.get("authority") or "").strip():
        missing.append("authority")
    if status == "unknown":
        missing.append("status")
    if status == "open" and not deadline:
        missing.append("deadline")
    return missing


def _feed_row(source: sqlite3.Row, snapshot: sqlite3.Row | None, labels: dict[str, str]) -> dict:
    payload = json.loads(snapshot["snapshot_json"]) if snapshot else {}
    summary = payload.get("summary") or {}
    status = _status(summary.get("status"))
    deadline = _iso_deadline(summary.get("deadline"))
    state = source_registry.normalize_state(source["state"])
    missing = _missing_fields(summary, status, deadline)
    return {
        "id": source["id"],
        "source_id": source["id"],
        "family": source["family"],
        "family_label": labels.get(source["family"], source["family"]),
        "label": source["label"] or source["identifier"] or source["url"],
        "identifier": source["identifier"],
        "url": source["url"],
        "state": state,
        "last_attempt_at": source["last_attempt_at"] or "",
        "updated_at": source["updated_at"],
        "last_error": source["last_error"],
        "title": summary.get("title") or "",
        "authority": summary.get("authority") or "",
        "status": status,
        "deadline": deadline,
        "deadline_raw": summary.get("deadline") or "",
        "documents": int(summary.get("documents") or 0),
        "truncated": bool(summary.get("truncated")),
        "snapshot_at": snapshot["captured_at"] if snapshot else "",
        "snapshot_hash": snapshot["content_hash"] if snapshot else "",
        "missing_fields": missing,
        "needs_attention": state in source_registry.ATTENTION_STATES or bool(missing),
        "can_review": state in {"changed", "needs_review"},
        "next_action": _next_action(state, missing),
    }


def _sort_key(row: dict) -> tuple:
    deadline = row["deadline"] or "9999-12-31"
    return (STATUSES[row["status"]], deadline, row["family"], row["title"].lower(), row["id"])


def _next_action(state: str, missing: list[str]) -> str:
    if state in {"failed", "unavailable", "rate_limited"}:
        return "Reîncearcă sursa sau creează notă în dosar cu indisponibilitatea."
    if missing:
        return "Completează sau revizuiește metadata lipsă: " + ", ".join(missing) + "."
    if state in {"changed", "needs_review"}:
        return "Revizuiește schimbarea și leag-o la timeline/dosar."
    return "Consultarea are metadata minimă pentru urmărire locală."


def lista(stare, query: dict | None = None) -> dict:
    query = query or {}
    status_filter = (query.get("status") or [""])[0].strip().lower()
    if status_filter and status_filter not in STATUSES:
        raise ValueError("Filtru e-consultare invalid.")
    family_filter = (query.get("family") or [""])[0].strip()
    if family_filter and family_filter not in FAMILIES:
        raise ValueError("Filtru familie consultări invalid.")
    try:
        limit = int((query.get("limit") or ["100"])[0] or 100)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limită e-consultare invalidă.") from exc
    if not 1 <= limit <= 300:
        raise ValueError("Limită e-consultare invalidă.")
    path = source_registry.cale(stare)
    if not path.exists():
        return {
            "contract": CONTRACT,
            "items": [],
            "total": 0,
            "families": {},
            "source_status": "missing",
            "limitari": ["Registrul surselor nu este inițializat."],
        }
    with closing(source_registry._open(path)) as con:
        source_registry.init(con)
        labels = source_registry.families()
        family_values = [family_filter] if family_filter else list(FAMILIES)
        sources = con.execute(
            "SELECT * FROM source_registry WHERE family IN ("
            + ",".join("?" for _ in family_values)
            + ") ORDER BY updated_at DESC,id",
            family_values,
        ).fetchall()
        snapshots = {}
        if sources:
            placeholders = ",".join("?" for _ in sources)
            for row in con.execute(
                "SELECT source_id,captured_at,content_hash,snapshot_json FROM source_snapshots "
                "WHERE source_id IN (" + placeholders + ") ORDER BY captured_at DESC,seq DESC",
                [source["id"] for source in sources],
            ):
                snapshots.setdefault(row["source_id"], row)
    items = [_feed_row(source, snapshots.get(source["id"]), labels) for source in sources]
    if status_filter:
        items = [item for item in items if item["status"] == status_filter]
    items.sort(key=_sort_key)
    counts = {status: sum(1 for item in items if item["status"] == status) for status in STATUSES}
    family_counts = {
        family: sum(1 for item in items if item["family"] == family) for family in FAMILIES
    }
    attention = sum(1 for item in items if item["needs_attention"])
    return {
        "contract": CONTRACT,
        "items": items[:limit],
        "total": len(items),
        "counts": counts,
        "families": family_counts,
        "attention": attention,
        "source_status": "ok",
        "limitari": [
            "Feed-ul citește registrul local pentru e-consultare, Guvern și ministere; "
            "nu accesează portalul public."
        ],
    }
