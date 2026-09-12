"""Local Monitorul Oficial Part I references as tracker events.

This module is deliberately a replay adapter, not an ingestion job. It consumes publication
references already present in local act/project rows, normalizes them to the
``published_in_monitor`` tracker event shape, and optionally stores those events through the
existing append-only tracker store.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scripts import tracker_events
from scripts.publicare import Publicare, publicare

EVENT_TYPE = "published_in_monitor"
SOURCE_FAMILY = "monitorul_oficial_pi"
DEFAULT_PART = "I"
MAX_LOCAL_ROWS = 5000


def _text(value: Any) -> str:
    return str(value or "").strip()


def _date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    if not text:
        return ""
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return ""


def _number(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= 99999 else None


def _part(value: Any) -> str:
    part = _text(value).upper()
    return part or DEFAULT_PART


def _source_hash(row: dict, parsed: Publicare | None) -> str:
    given = _text(row.get("source_hash") or row.get("sha256"))
    if given:
        return given
    text = _text(row.get("text"))
    if text:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    if parsed and parsed.text:
        return hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
    return ""


def _content_hash(*parts: Any) -> str:
    raw = "\x1f".join(_text(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _title(row: dict, *, number: int, when: str, republication: bool) -> str:
    act_id = _text(row.get("act_id") or row.get("cheie_act") or row.get("id") or row.get("plx_id"))
    prefix = "Republicat" if republication else "Publicat"
    target = f" pentru {act_id}" if act_id else ""
    return f"{prefix} in Monitorul Oficial Partea I nr. {number} din {when}{target}"


def _event(
    row: dict,
    *,
    project_id: str,
    parsed: Publicare | None,
    observed_at: str | None,
) -> dict | None:
    number = _number(parsed.monitor if parsed else row.get("monitor") or row.get("number"))
    when = _date(parsed.data if parsed else row.get("publicat") or row.get("date"))
    if number is None or not when:
        return None
    part = _part(parsed.partea if parsed else row.get("part") or row.get("partea"))
    if part != DEFAULT_PART:
        return None
    act_id = _text(row.get("act_id") or row.get("cheie_act") or row.get("id"))
    source_hash = _source_hash(row, parsed)
    republication = bool(parsed.republicare if parsed else row.get("republicare"))
    payload = {
        "part": part,
        "number": number,
        "date": when,
        "act_id": act_id,
        "source_hash": source_hash,
        "republication": republication,
    }
    source_url = _text(row.get("source_url") or row.get("sursa_url"))
    if source_url:
        payload["source_url"] = source_url
    raw_status = _text(row.get("stadiu") or row.get("actiune"))
    if raw_status:
        payload["raw_status"] = raw_status
    return {
        "event_type": EVENT_TYPE,
        "project_id": project_id,
        "dossier_id": _text(row.get("dossier_id")),
        "source_family": SOURCE_FAMILY,
        "source_id": _text(row.get("source_id") or row.get("id_portal") or row.get("plx_id")),
        "source_url": source_url,
        "occurred_at": datetime.fromisoformat(when).replace(tzinfo=UTC).isoformat(),
        "observed_at": observed_at
        or _text(row.get("observed_at") or row.get("citit_la") or row.get("adus_la")),
        "title": _title(row, number=number, when=when, republication=republication),
        "payload": payload,
        "content_hash": _content_hash(
            EVENT_TYPE, project_id, part, number, when, act_id, source_hash
        ),
    }


def event_from_act_row(row: dict, *, observed_at: str | None = None) -> dict | None:
    """Return a tracker event for one local act/document row, or ``None`` when incomplete."""
    parsed = publicare(row.get("text") or "") if row.get("text") else None
    project_id = _text(
        row.get("project_id") or row.get("cheie_act") or row.get("act_id") or row.get("id")
    )
    if not project_id:
        return None
    return _event(dict(row), project_id=project_id, parsed=parsed, observed_at=observed_at)


def event_from_project_row(row: dict, *, observed_at: str | None = None) -> dict | None:
    """Return a tracker event for one local project/status row, or ``None`` when incomplete."""
    row = dict(row)
    text = "\n".join(
        part
        for part in (_text(row.get("stadiu")), _text(row.get("actiune")), _text(row.get("text")))
        if part
    )
    parsed = publicare(text) if text else None
    project_id = _text(row.get("project_id") or row.get("plx_id"))
    if not project_id:
        return None
    return _event(row, project_id=project_id, parsed=parsed, observed_at=observed_at)


def events_from_rows(
    act_rows: Iterable[dict] = (),
    project_rows: Iterable[dict] = (),
    *,
    observed_at: str | None = None,
) -> list[dict]:
    """Convert local act/project rows to tracker event-shaped dictionaries."""
    events = []
    seen = set()
    for builder, rows in (
        (event_from_act_row, act_rows),
        (event_from_project_row, project_rows),
    ):
        for row in rows:
            event = builder(row, observed_at=observed_at)
            if not event:
                continue
            key = (
                event["event_type"],
                event["project_id"],
                event["source_family"],
                event["source_url"],
                event["occurred_at"],
                event["content_hash"],
            )
            if key in seen:
                continue
            seen.add(key)
            events.append(event)
    return events


def _readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def local_act_events(corpus_db: str | Path, *, limit: int = MAX_LOCAL_ROWS) -> list[dict]:
    """Read already stored act/document publication references from a local corpus DB."""
    if not 1 <= limit <= MAX_LOCAL_ROWS:
        raise ValueError("Local Monitor replay limit invalid.")
    rows: list[dict] = []
    with closing(_readonly(Path(corpus_db))) as con:
        if _has_table(con, "documente"):
            rows.extend(
                dict(row)
                for row in con.execute(
                    "SELECT cheie_act,id_portal,publicat,monitor,republicare,"
                    "sursa_url,text,adus_la "
                    "FROM documente WHERE publicat IS NOT NULL AND monitor IS NOT NULL "
                    "ORDER BY publicat DESC, id_portal LIMIT ?",
                    (limit,),
                )
            )
        if len(rows) < limit and _has_table(con, "acte"):
            rows.extend(
                dict(row)
                for row in con.execute(
                    "SELECT id AS act_id,id_portal,publicat,sursa_url,citit_la "
                    "FROM acte WHERE publicat IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='documente') "
                    "ORDER BY publicat DESC, id LIMIT ?",
                    (limit - len(rows),),
                )
            )
    return events_from_rows(rows)


def local_project_events(initiative_db: str | Path, *, limit: int = MAX_LOCAL_ROWS) -> list[dict]:
    """Read stored project/status publication references from a local initiative DB."""
    if not 1 <= limit <= MAX_LOCAL_ROWS:
        raise ValueError("Local Monitor replay limit invalid.")
    rows = []
    with closing(_readonly(Path(initiative_db))) as con:
        if _has_table(con, "initiative"):
            rows.extend(
                dict(row)
                for row in con.execute(
                    "SELECT plx_id,stadiu,sursa_url,citit_la FROM initiative "
                    "WHERE stadiu LIKE '%Monitorul Oficial%' "
                    "ORDER BY citit_la DESC, plx_id LIMIT ?",
                    (limit,),
                )
            )
        if len(rows) < limit and _has_table(con, "initiativa_etapa"):
            rows.extend(
                dict(row)
                for row in con.execute(
                    "SELECT plx_id,data,camera,actiune FROM initiativa_etapa "
                    "WHERE actiune LIKE '%Monitorul Oficial%' "
                    "ORDER BY COALESCE(data, '') DESC, plx_id, ord LIMIT ?",
                    (limit - len(rows),),
                )
            )
    return events_from_rows(project_rows=rows)


def replay_to_tracker(
    stare,
    *,
    corpus_db: str | Path | None = None,
    initiative_db: str | Path | None = None,
    limit: int = MAX_LOCAL_ROWS,
) -> dict:
    """Store locally derived MO Part I publication events in the tracker DB."""
    events: list[dict] = []
    if corpus_db is not None:
        events.extend(local_act_events(corpus_db, limit=limit))
    if initiative_db is not None:
        events.extend(local_project_events(initiative_db, limit=limit))
    stored = [tracker_events.adauga(stare, event)["event"] for event in events]
    return {
        "contract": tracker_events.CONTRACT,
        "event_type": EVENT_TYPE,
        "source_family": SOURCE_FAMILY,
        "stored": len(stored),
        "events": stored,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-db", type=Path)
    parser.add_argument("--initiative-db", type=Path)
    parser.add_argument("--tracker-db", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_LOCAL_ROWS)
    args = parser.parse_args()
    state = argparse.Namespace(tracker_events_db=args.tracker_db)
    result = replay_to_tracker(
        state,
        corpus_db=args.corpus_db,
        initiative_db=args.initiative_db,
        limit=args.limit,
    )
    print(f"{result['stored']} Monitorul Oficial Part I tracker events stored")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
