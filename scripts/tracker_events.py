"""Append-only legislative tracker events from public source observations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from scripts.source_portfolio import TRACKER_EVENTS

APPLICATION_ID = 0x4C545245
SCHEMA_VERSION = 2
CONTRACT = "legislative-tracker-events-v1"
MAX_TEXT = 1000
MAX_PAYLOAD = 20000
EVENT_TYPES = {event.key: event for event in TRACKER_EVENTS}
TOKEN = re.compile(r"^[a-z0-9_.:/ -]{1,200}$", re.I)


def cale(stare) -> Path:
    if getattr(stare, "tracker_events_db", None) is not None:
        return Path(stare.tracker_events_db)
    if getattr(stare, "date_dir", None) is not None:
        raise ValueError("Tracker-ul legislativ persistent este disponibil numai local.")
    return Path(stare.initiative).with_suffix(".tracker.db")


@contextmanager
def _open(path, *, write=False):
    path = Path(path)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(FileExistsError):
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    con = sqlite3.connect(
        path.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=5
    )
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        app = con.execute("PRAGMA application_id").fetchone()[0]
        if write and version == 0 and app == 0:
            init(con)
            version = SCHEMA_VERSION
            app = APPLICATION_ID
        if write and version == 1 and app == APPLICATION_ID:
            _init_reviews(con)
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        if version != SCHEMA_VERSION or app != APPLICATION_ID:
            raise ValueError("Schema tracker-ului legislativ nu este compatibilă.")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE tracker_events (id TEXT PRIMARY KEY, event_type TEXT NOT NULL, "
        "project_id TEXT NOT NULL, dossier_id TEXT NOT NULL DEFAULT '', "
        "source_family TEXT NOT NULL, source_id TEXT NOT NULL DEFAULT '', "
        "source_url TEXT NOT NULL DEFAULT '', occurred_at TEXT NOT NULL, "
        "observed_at TEXT NOT NULL, title TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "content_hash TEXT NOT NULL DEFAULT '', "
        "UNIQUE(event_type,project_id,source_family,source_url,occurred_at,content_hash))"
    )
    con.execute(
        "CREATE INDEX tracker_events_project "
        "ON tracker_events(project_id,occurred_at DESC,observed_at DESC,id)"
    )
    con.execute(
        "CREATE INDEX tracker_events_dossier "
        "ON tracker_events(dossier_id,occurred_at DESC,observed_at DESC,id)"
    )
    _init_reviews(con)
    con.execute(f"PRAGMA application_id={APPLICATION_ID}")
    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _init_reviews(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS tracker_event_reviews (event_id TEXT PRIMARY KEY "
        "REFERENCES tracker_events(id), reviewed_at TEXT NOT NULL, reviewer TEXT NOT NULL, "
        "note TEXT NOT NULL)"
    )


def _text(value, *, limit=MAX_TEXT, required=False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Text tracker invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Câmp tracker obligatoriu lipsă.")
    if len(value) > limit or "\x00" in value:
        raise ValueError("Text tracker invalid sau prea lung.")
    return value


def _event_type(value) -> str:
    value = _text(value, limit=80, required=True)
    if value not in EVENT_TYPES:
        raise ValueError("Tip eveniment legislativ necunoscut.")
    return value


def _token(value, *, required=False) -> str:
    value = _text(value, limit=200, required=required)
    if value and not TOKEN.fullmatch(value):
        raise ValueError("Identificator tracker invalid.")
    return value


def _payload(value) -> str:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("Payload tracker invalid.")
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_PAYLOAD:
        raise ValueError("Payload tracker prea mare.")
    return raw


def _stamp(value, *, required=False) -> str:
    value = _text(value, limit=80, required=required)
    if not value:
        return datetime.now(UTC).isoformat()
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Dată tracker invalidă.") from exc
    return value


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["payload"] = json.loads(out.pop("payload_json") or "{}")
    out["event_label"] = EVENT_TYPES[out["event_type"]].label
    return out


def _with_reviews(con: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    reviews = {
        row["event_id"]: dict(row)
        for row in con.execute(
            "SELECT * FROM tracker_event_reviews WHERE event_id IN (" + placeholders + ")",
            ids,
        )
    }
    for row in rows:
        review = reviews.get(row["id"])
        row["review"] = {
            "reviewed": bool(review),
            "reviewed_at": review["reviewed_at"] if review else "",
            "reviewer": review["reviewer"] if review else "",
            "note": review["note"] if review else "",
        }
    return rows


def _event(con: sqlite3.Connection, event_id: str) -> dict:
    row = con.execute("SELECT * FROM tracker_events WHERE id=?", (event_id,)).fetchone()
    if not row:
        raise ValueError("Eveniment tracker inexistent.")
    return _with_reviews(con, [_row(row)])[0]


def _empty(limit: int = 50, offset: int = 0) -> dict:
    return {
        "contract": CONTRACT,
        "events": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "event_types": sorted(EVENT_TYPES),
        "source_status": "missing",
        "limitari": ["Tracker-ul legislativ nu este inițializat."],
    }


def adauga(stare, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {
        "id",
        "event_type",
        "project_id",
        "dossier_id",
        "source_family",
        "source_id",
        "source_url",
        "occurred_at",
        "observed_at",
        "title",
        "payload",
        "content_hash",
    }:
        raise ValueError("Cerere tracker invalidă.")
    event_type = _event_type(request.get("event_type"))
    contract = EVENT_TYPES[event_type]
    source_family = _text(
        request.get("source_family") or contract.source_family, limit=80, required=True
    )
    row = {
        "id": _token(request.get("id")) or uuid.uuid4().hex,
        "event_type": event_type,
        "project_id": _token(request.get("project_id"), required=True),
        "dossier_id": _token(request.get("dossier_id")),
        "source_family": source_family,
        "source_id": _token(request.get("source_id")),
        "source_url": _text(request.get("source_url"), limit=MAX_TEXT),
        "occurred_at": _stamp(request.get("occurred_at"), required=True),
        "observed_at": _stamp(request.get("observed_at")),
        "title": _text(request.get("title") or contract.label, limit=300, required=True),
        "payload_json": _payload(request.get("payload")),
        "content_hash": _token(request.get("content_hash")),
    }
    with _open(cale(stare), write=True) as con:
        con.execute(
            "INSERT INTO tracker_events "
            "(id,event_type,project_id,dossier_id,source_family,source_id,source_url,"
            "occurred_at,observed_at,title,payload_json,content_hash) "
            "VALUES (:id,:event_type,:project_id,:dossier_id,:source_family,:source_id,"
            ":source_url,:occurred_at,:observed_at,:title,:payload_json,:content_hash) "
            "ON CONFLICT(event_type,project_id,source_family,source_url,occurred_at,content_hash) "
            "DO UPDATE SET observed_at=excluded.observed_at,title=excluded.title,"
            "payload_json=excluded.payload_json",
            row,
        )
        saved = con.execute(
            "SELECT * FROM tracker_events WHERE event_type=? AND project_id=? AND "
            "source_family=? AND source_url=? AND occurred_at=? AND content_hash=?",
            (
                row["event_type"],
                row["project_id"],
                row["source_family"],
                row["source_url"],
                row["occurred_at"],
                row["content_hash"],
            ),
        ).fetchone()
    return {"contract": CONTRACT, "event": _row(saved)}


def lista(stare, query: dict | None = None) -> dict:
    query = query or {}
    try:
        limit = int((query.get("limit") or ["50"])[0] or 50)
        offset = int((query.get("offset") or ["0"])[0] or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Paginare tracker invalidă.") from exc
    if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
        raise ValueError("Paginare tracker invalidă.")
    reviewed_filter = (query.get("reviewed") or [""])[0]
    if reviewed_filter not in {"", "0", "1"}:
        raise ValueError("Filtru tracker invalid.")
    path = cale(stare)
    if not path.exists():
        return _empty(limit, offset)
    where = []
    params: list[str] = []
    for key in ("project_id", "dossier_id", "event_type", "source_family"):
        value = (query.get(key) or [""])[0]
        if value:
            where.append(f"{key}=?")
            params.append(
                _token(value, required=True) if key != "source_family" else _text(value, limit=80)
            )
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with _open(path) as con:
        review_join = (
            " LEFT JOIN tracker_event_reviews r ON r.event_id=tracker_events.id"
            if reviewed_filter
            else ""
        )
        review_clause = ""
        if reviewed_filter:
            review_clause = (" AND " if where else " WHERE ") + (
                "r.event_id IS NOT NULL" if reviewed_filter == "1" else "r.event_id IS NULL"
            )
        total = con.execute(
            "SELECT count(*) FROM tracker_events" + review_join + clause + review_clause,
            params,
        ).fetchone()[0]
        rows = [
            _row(row)
            for row in con.execute(
                "SELECT tracker_events.* FROM tracker_events"
                + review_join
                + clause
                + review_clause
                + " ORDER BY occurred_at DESC,observed_at DESC,id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
        ]
        rows = _with_reviews(con, rows)
    return {
        "contract": CONTRACT,
        "events": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "event_types": sorted(EVENT_TYPES),
        "source_status": "ok",
        "limitari": [
            "Tracker-ul citește evenimente locale normalizate; nu sincronizează surse publice."
        ],
    }


def marcheaza_revizuit(stare, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {"id", "reviewer", "note"}:
        raise ValueError("Cerere revizie tracker invalidă.")
    event_id = _token(request.get("id"), required=True)
    reviewer = _text(request.get("reviewer") or "utilizator", limit=120, required=True)
    note = _text(request.get("note") or "", limit=1000)
    with _open(cale(stare), write=True) as con:
        _event(con, event_id)
        con.execute(
            "INSERT INTO tracker_event_reviews(event_id,reviewed_at,reviewer,note) "
            "VALUES (?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET "
            "reviewed_at=excluded.reviewed_at,reviewer=excluded.reviewer,note=excluded.note",
            (event_id, datetime.now(UTC).isoformat(), reviewer, note),
        )
        return {"contract": CONTRACT, "event": _event(con, event_id)}


def creeaza_nota_dosar(stare, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {
        "id",
        "dosar_id",
        "note_id",
        "type",
        "status",
        "reasoning",
    }:
        raise ValueError("Cerere notă tracker invalidă.")
    event_id = _token(request.get("id"), required=True)
    dossier_id = _token(request.get("dosar_id"), required=True)
    with _open(cale(stare)) as con:
        event = _event(con, event_id)

    from scripts import dosare, note_manuale

    payload = event.get("payload") or {}
    reasoning = _text(request.get("reasoning") or "", limit=8000)
    if not reasoning:
        reasoning = (
            "Eveniment tracker: "
            f"{event.get('event_label') or event['event_type']} pentru {event['project_id']}."
        )
    source_hash = event.get("content_hash") or ""
    note = note_manuale.salveaza(
        dosare.cale(stare),
        {
            "id": _token(request.get("note_id")) or uuid.uuid4().hex,
            "dosar_id": dossier_id,
            "revizie": 0,
            "title": f"Revizie tracker · {event['title']}"[:200],
            "type": request.get("type") or "necorelare",
            "act_id": event["project_id"],
            "locator": event["event_type"][:120],
            "evidence_quote": json.dumps(payload, ensure_ascii=False, sort_keys=True)[:4000],
            "source_url": event.get("source_url") or "https://legislativ.local/tracker",
            "source_hash": source_hash if len(source_hash) == 64 else "",
            "reasoning": reasoning,
            "status": request.get("status") or "ready_for_review",
        },
    )
    return {"contract": CONTRACT, "event": event, "note": note}


def executa(stare, request: dict) -> dict:
    action = _text(request.get("action") or "add", limit=20)
    if action == "add":
        return adauga(stare, {key: value for key, value in request.items() if key != "action"})
    if action == "list":
        return lista(
            stare, {key: [str(value)] for key, value in request.items() if key != "action"}
        )
    if action == "review":
        return marcheaza_revizuit(
            stare, {key: value for key, value in request.items() if key != "action"}
        )
    if action == "create_note":
        return creeaza_nota_dosar(
            stare, {key: value for key, value in request.items() if key != "action"}
        )
    raise ValueError("Acțiune tracker invalidă.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--project-id", default="")
    args = parser.parse_args(argv)
    stare = argparse.Namespace(
        initiative=str(Path(args.db).with_suffix(".db")), tracker_events_db=args.db
    )
    print(json.dumps(lista(stare, {"project_id": [args.project_id]}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
