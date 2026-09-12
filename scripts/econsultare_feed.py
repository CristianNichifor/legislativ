"""Read-only feed of locally registered e-consultare sources."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import date

from scripts import source_registry

CONTRACT = "econsultare-feed-v1"
FAMILY = "consultare_econsultare"
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


def _feed_row(source: sqlite3.Row, snapshot: sqlite3.Row | None) -> dict:
    payload = json.loads(snapshot["snapshot_json"]) if snapshot else {}
    summary = payload.get("summary") or {}
    status = _status(summary.get("status"))
    deadline = _iso_deadline(summary.get("deadline"))
    return {
        "id": source["id"],
        "source_id": source["id"],
        "label": source["label"] or source["identifier"] or source["url"],
        "identifier": source["identifier"],
        "url": source["url"],
        "state": source_registry.normalize_state(source["state"]),
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
        "needs_attention": source["state"] in source_registry.ATTENTION_STATES
        or status == "unknown",
    }


def _sort_key(row: dict) -> tuple:
    deadline = row["deadline"] or "9999-12-31"
    return (STATUSES[row["status"]], deadline, row["title"].lower(), row["id"])


def lista(stare, query: dict | None = None) -> dict:
    query = query or {}
    status_filter = (query.get("status") or [""])[0].strip().lower()
    if status_filter and status_filter not in STATUSES:
        raise ValueError("Filtru e-consultare invalid.")
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
            "source_status": "missing",
            "limitari": ["Registrul surselor nu este inițializat."],
        }
    with closing(source_registry._open(path)) as con:
        source_registry.init(con)
        sources = con.execute(
            "SELECT * FROM source_registry WHERE family=? ORDER BY updated_at DESC,id",
            (FAMILY,),
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
    items = [_feed_row(source, snapshots.get(source["id"])) for source in sources]
    if status_filter:
        items = [item for item in items if item["status"] == status_filter]
    items.sort(key=_sort_key)
    counts = {status: sum(1 for item in items if item["status"] == status) for status in STATUSES}
    return {
        "contract": CONTRACT,
        "items": items[:limit],
        "total": len(items),
        "counts": counts,
        "source_status": "ok",
        "limitari": [
            "Feed-ul citește registrul local și instantaneele păstrate; "
            "nu accesează portalul public."
        ],
    }
