"""Persistent local follows for public legislative project lifecycle tracking."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from scripts import lifecycle, tracker_events

CONTRACT = "project-lifecycle-watchlist-v1"
APPLICATION_ID = 0x4C57544C
SCHEMA_VERSION = 1
MAX_WATCHED = 200
MAX_LABEL = 300
MAX_NOTE = 1000
PUBLIC_PATH_STAGES = (
    ("consultation", "e-consultare", {"public_consultation_opened", "public_consultation_closed"}),
    ("committee", "Comisie", {"committee_assignment"}),
    ("opinion", "Aviz", {"opinion_received"}),
    ("report", "Raport", {"report_filed"}),
    ("vote", "Vot", {"plenary_agenda", "vote_recorded"}),
    ("publication", "Monitorul Oficial", {"published_in_monitor"}),
)


def cale(stare) -> Path:
    return Path(stare.initiative).with_suffix(".lifecycle-watchlist.db")


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _text(value, *, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Text watchlist lifecycle invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Câmp watchlist lifecycle lipsă.")
    if len(value) > limit or "\x00" in value:
        raise ValueError("Text watchlist lifecycle invalid.")
    return value


def _project_id(value) -> str:
    value = _text(value, limit=200, required=True)
    return tracker_events._token(value, required=True)


def _id(value=None) -> str:
    if value in (None, ""):
        return uuid.uuid4().hex
    return tracker_events._token(value, required=True)


def _open(path: Path, *, write: bool = False):
    path = Path(path)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    init(con)
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS lifecycle_watchlist (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL UNIQUE,
          label TEXT NOT NULL,
          created_at TEXT NOT NULL,
          reviewed_at TEXT,
          review_note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_lifecycle_watchlist_created
          ON lifecycle_watchlist(created_at DESC, id);
        PRAGMA application_id = 1280795724;
        PRAGMA user_version = 1;
        """
    )


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["reviewed"] = bool(out.get("reviewed_at"))
    return out


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with closing(_open(path)) as con:
        return [
            _row(row)
            for row in con.execute(
                "SELECT * FROM lifecycle_watchlist ORDER BY created_at DESC, id LIMIT ?",
                (MAX_WATCHED,),
            )
        ]


def adauga(stare, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {"id", "project_id", "label"}:
        raise ValueError("Cerere watchlist lifecycle invalidă.")
    project_id = _project_id(request.get("project_id"))
    label = _text(request.get("label") or project_id, limit=MAX_LABEL)
    ident = _id(request.get("id"))
    stamp = _stamp()
    with closing(_open(cale(stare), write=True)) as con:
        total = con.execute("SELECT count(*) FROM lifecycle_watchlist").fetchone()[0]
        existing = con.execute(
            "SELECT id FROM lifecycle_watchlist WHERE project_id=?", (project_id,)
        ).fetchone()
        if total >= MAX_WATCHED and existing is None:
            raise ValueError("Watchlist-ul lifecycle este plin.")
        con.execute(
            "INSERT INTO lifecycle_watchlist(id,project_id,label,created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET label=excluded.label",
            (ident, project_id, label, stamp),
        )
        con.commit()
        return _row(
            con.execute(
                "SELECT * FROM lifecycle_watchlist WHERE project_id=?", (project_id,)
            ).fetchone()
        )


def sterge(stare, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"project_id"}:
        raise ValueError("Cerere watchlist lifecycle invalidă.")
    project_id = _project_id(request.get("project_id"))
    with closing(_open(cale(stare), write=True)) as con:
        cur = con.execute("DELETE FROM lifecycle_watchlist WHERE project_id=?", (project_id,))
        con.commit()
    return {"contract": CONTRACT, "project_id": project_id, "deleted": cur.rowcount == 1}


def marcheaza_revizuit(stare, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {"project_id", "note"}:
        raise ValueError("Cerere watchlist lifecycle invalidă.")
    project_id = _project_id(request.get("project_id"))
    note = _text(request.get("note") or "", limit=MAX_NOTE)
    stamp = _stamp()
    with closing(_open(cale(stare), write=True)) as con:
        row = con.execute(
            "SELECT * FROM lifecycle_watchlist WHERE project_id=?", (project_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Proiectul nu este urmărit.")
        con.execute(
            "UPDATE lifecycle_watchlist SET reviewed_at=?,review_note=? WHERE project_id=?",
            (stamp, note, project_id),
        )
        con.commit()
        return _row(
            con.execute(
                "SELECT * FROM lifecycle_watchlist WHERE project_id=?", (project_id,)
            ).fetchone()
        )


def _lifecycle_project(stare, project_id: str) -> dict | None:
    out = lifecycle.project_lifecycle_summary(stare, query=project_id, limit=50)
    for project in out.get("projects", []):
        if project.get("project_id") == project_id:
            return project
    return None


def _tracker_project(stare, project_id: str) -> dict:
    try:
        return tracker_events.lista(stare, {"project_id": [project_id], "limit": ["100"]})
    except (OSError, ValueError, sqlite3.Error):
        return tracker_events._empty(100, 0)


def _coverage(events: list[dict]) -> list[dict]:
    types = {event.get("event_type") for event in events}
    out = []
    for key, label, event_types in PUBLIC_PATH_STAGES:
        present = bool(types & event_types)
        out.append(
            {
                "key": key,
                "label": label,
                "state": "present" if present else "missing",
                "event_types": sorted(types & event_types),
                "required_any": sorted(event_types),
            }
        )
    return out


def _status_state(project: dict | None, tracker: dict, watched: dict) -> str:
    if project and project.get("registry_source_state") in lifecycle.REGISTRY_ATTENTION_STATES:
        return "changed"
    if tracker.get("summary", {}).get("unreviewed"):
        return "changed"
    if project and project.get("source_state") in {"stale", "unknown", "unavailable"}:
        return project["source_state"]
    if not project:
        return "missing"
    latest = tracker.get("summary", {}).get("latest_event") or {}
    reviewed_at = watched.get("reviewed_at") or ""
    latest_at = latest.get("occurred_at") or latest.get("observed_at") or ""
    if latest_at and (not reviewed_at or latest_at > reviewed_at):
        return "changed"
    return "ok"


def _missing_reasons(project: dict | None, coverage: list[dict]) -> list[str]:
    reasons = []
    if not project:
        reasons.append("missing_project_snapshot")
    for item in coverage:
        if item["state"] == "missing":
            reasons.append(f"missing_{item['key']}")
    return reasons


def _watched_item(stare, watched: dict) -> dict:
    project_id = watched["project_id"]
    project = _lifecycle_project(stare, project_id)
    tracker = _tracker_project(stare, project_id)
    events = tracker.get("events") or []
    coverage = _coverage(events)
    state = _status_state(project, tracker, watched)
    latest = (tracker.get("summary") or {}).get("latest_event") or (project or {}).get(
        "latest_event"
    ) or {}
    missing = _missing_reasons(project, coverage)
    needs_attention = state in {"changed", "stale", "unknown", "unavailable", "missing"} or any(
        item["state"] == "missing" for item in coverage
    )
    if project:
        source_url = project.get("url") or (project.get("registry_source") or {}).get("url", "")
        title = project.get("title") or watched["label"]
        stage = project.get("stage") or {}
        uncertainty = project.get("uncertainty") or {}
        timestamp = project.get("last_updated") or project.get("last_seen") or ""
    else:
        source_url = latest.get("source_url", "")
        title = watched["label"]
        stage = {"key": "unavailable", "label": "unavailable", "known": False, "available": False}
        uncertainty = {
            "level": "high",
            "reasons": ["missing_project_snapshot"],
            "message": "Proiectul urmărit nu există în registrul local.",
        }
        timestamp = latest.get("occurred_at") or latest.get("observed_at") or ""
    return {
        "contract": CONTRACT,
        "watch": watched,
        "project_id": project_id,
        "title": title,
        "state": state,
        "needs_attention": needs_attention,
        "project": project,
        "stage": stage,
        "latest_stage": {
            "key": latest.get("stage_key") or stage.get("key", ""),
            "label": latest.get("stage_label") or stage.get("label", ""),
            "timestamp": latest.get("occurred_at") or latest.get("date") or timestamp,
            "source_url": latest.get("source_url") or source_url,
            "source_family": latest.get("source_family") or "",
            "title": latest.get("title") or latest.get("action") or "",
        },
        "source": {
            "url": source_url,
            "state": (project or {}).get("registry_source_state")
            or (project or {}).get("source_state")
            or state,
            "name": (project or {}).get("source_name") or latest.get("source_family") or "",
            "timestamp": timestamp,
            "registry_source_id": (project or {}).get("registry_source_id", ""),
        },
        "tracker": {
            "total": tracker.get("total", 0),
            "unreviewed": (tracker.get("summary") or {}).get("unreviewed", 0),
            "latest_event": latest,
            "events": events,
        },
        "path_coverage": coverage,
        "missing": missing,
        "uncertainty": uncertainty,
        "updated_at": latest.get("occurred_at") or timestamp or watched.get("created_at", ""),
    }


def lista(stare) -> dict:
    rows = _load_rows(cale(stare))
    items = [_watched_item(stare, row) for row in rows]
    items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {
        "contract": CONTRACT,
        "generated_at": _stamp(),
        "items": items,
        "total": len(items),
        "attention": sum(1 for item in items if item["needs_attention"]),
        "limitari": [
            "Watchlist-ul citește numai snapshoturi și evenimente locale; nu pornește crawling.",
            "Etapele lipsă înseamnă că nu există dovadă locală pentru acel punct din traseu.",
        ],
    }


def executa(stare, request: dict) -> dict:
    action = _text(request.get("action", "list"), limit=40) if isinstance(request, dict) else ""
    action = action or "list"
    if action == "list":
        return lista(stare)
    if action == "add":
        return {"contract": CONTRACT, "watch": adauga(stare, _without_action(request))}
    if action == "delete":
        return sterge(stare, _without_action(request))
    if action == "review":
        return {"contract": CONTRACT, "watch": marcheaza_revizuit(stare, _without_action(request))}
    raise ValueError("Acțiune watchlist lifecycle invalidă.")


def _without_action(request: dict) -> dict:
    return {key: value for key, value in request.items() if key != "action"}
