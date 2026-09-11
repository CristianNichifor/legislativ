"""Local source registry for incremental, one-source acquisition work."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts import cellar
from scripts.source_sync import SYNC_STATES, can_transition, normalize_state

FAMILIES = {
    "legislatie_ro": "Legislație română",
    "parlament": "Proiecte parlamentare",
    "camera": "Camera Deputaților",
    "senat": "Senat",
    "consultare_guvern": "Consultări Guvern",
    "consultare_minister": "Consultări ministere",
    "monitorul_oficial": "Monitorul Oficial",
    "ccr": "Decizii CCR",
    "ue_cellar": "Drept UE · Cellar/EUR-Lex",
}
SCHEMA_VERSION = 1
MAX_TEXT = 1000
MAX_PAGE = 50
HEX64 = re.compile(r"^[a-f0-9]{64}$")
TOKEN = re.compile(r"^[a-z0-9_.:-]{1,120}$", re.I)


def cale(stare) -> Path:
    return Path(stare.initiative).with_suffix(".sources.db")


def now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value, *, limit=MAX_TEXT, required=False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Câmp text invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Câmp obligatoriu lipsă.")
    if len(value) > limit:
        raise ValueError("Câmp text prea lung.")
    return value


def _family(value: str) -> str:
    value = _text(value, limit=80, required=True)
    if value not in FAMILIES:
        raise ValueError("Familie de surse necunoscută.")
    return value


def _url(value) -> str:
    value = _text(value, limit=MAX_TEXT)
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL sursă invalid.")
    return value


def _hash(value) -> str:
    value = _text(value, limit=64)
    if value and not HEX64.fullmatch(value):
        raise ValueError("Hash sursă invalid.")
    return value


def _token(value, *, required=False) -> str:
    value = _text(value, limit=120, required=required)
    if value and not TOKEN.fullmatch(value):
        raise ValueError("Identificator sursă invalid.")
    return value


def _id(family: str, identifier: str, url: str) -> str:
    key = identifier or url
    if not key:
        raise ValueError("Sursa are nevoie de identificator sau URL.")
    digest = hashlib.sha256(f"{family}\0{key}".encode()).hexdigest()[:32]
    return f"src_{digest}"


def _open(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_registry (
          id TEXT PRIMARY KEY,
          family TEXT NOT NULL,
          identifier TEXT NOT NULL,
          url TEXT NOT NULL,
          label TEXT NOT NULL,
          state TEXT NOT NULL,
          last_hash TEXT NOT NULL DEFAULT '',
          parser_version TEXT NOT NULL DEFAULT '',
          last_attempt_at TEXT,
          last_http_status INTEGER,
          last_error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_source_registry_family_state
          ON source_registry(family,state,updated_at);
        CREATE TABLE IF NOT EXISTS source_attempts (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id TEXT NOT NULL REFERENCES source_registry(id),
          attempted_at TEXT NOT NULL,
          state TEXT NOT NULL,
          http_status INTEGER,
          error_category TEXT NOT NULL DEFAULT '',
          content_hash TEXT NOT NULL DEFAULT '',
          parser_version TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT ''
        );
        PRAGMA user_version = 1;
        """
    )


def _row(row: sqlite3.Row) -> dict:
    return dict(row)


def families() -> dict[str, str]:
    return dict(FAMILIES)


def lista(stare, qs: dict | None = None) -> dict:
    qs = qs or {}
    offset = max(0, int((qs.get("offset") or ["0"])[0]))
    family = (qs.get("family") or [""])[0]
    state = (qs.get("state") or [""])[0]
    query = _text((qs.get("q") or [""])[0], limit=200).lower()
    params: list[object] = []
    where = []
    if family:
        where.append("family=?")
        params.append(_family(family))
    if state:
        where.append("state=?")
        params.append(normalize_state(state))
    if query:
        where.append("(lower(identifier) LIKE ? OR lower(url) LIKE ? OR lower(label) LIKE ?)")
        needle = f"%{query}%"
        params.extend([needle, needle, needle])
    clause = " WHERE " + " AND ".join(where) if where else ""
    path = cale(stare)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "families": families(),
            "states": list(SYNC_STATES),
            "sources": [],
            "total": 0,
            "offset": offset,
            "more": False,
            "counts": {},
        }
    with closing(_open(path)) as con:
        init(con)
        total = con.execute("SELECT count(*) FROM source_registry" + clause, params).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM source_registry"
            + clause
            + " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
            [*params, MAX_PAGE, offset],
        ).fetchall()
        counts = {
            f"{r['family']}:{r['state']}": r["c"]
            for r in con.execute(
                "SELECT family,state,count(*) c FROM source_registry GROUP BY family,state"
            )
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "families": families(),
        "states": list(SYNC_STATES),
        "sources": [_row(row) for row in rows],
        "total": total,
        "offset": offset,
        "more": offset + len(rows) < total,
        "counts": counts,
    }


def descopera(stare, data: dict) -> dict:
    family = _family(data.get("family", ""))
    identifier = _token(data.get("identifier", ""))
    url = _url(data.get("url", ""))
    label = _text(data.get("label", ""), limit=300) or identifier or url
    ident = _id(family, identifier, url)
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        con.execute(
            """
            INSERT INTO source_registry
              (id,family,identifier,url,label,state,created_at,updated_at)
            VALUES (?,?,?,?,?,'discovered',?,?)
            ON CONFLICT(id) DO UPDATE SET
              url=COALESCE(NULLIF(excluded.url,''),url),
              label=excluded.label,
              updated_at=excluded.updated_at
            """,
            (ident, family, identifier, url, label, stamp, stamp),
        )
        con.commit()
        return _row(con.execute("SELECT * FROM source_registry WHERE id=?", (ident,)).fetchone())


def pune_in_coada(stare, source_id: str) -> dict:
    source_id = _token(source_id, required=True)
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        row = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("Sursa nu există în registru.")
        if not can_transition(row["state"], "queued"):
            raise ValueError("Tranziție de stare invalidă.")
        con.execute(
            "UPDATE source_registry SET state='queued',updated_at=? WHERE id=?",
            (stamp, source_id),
        )
        con.commit()
        updated = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        return _row(updated)


def inregistreaza(stare, data: dict) -> dict:
    source_id = _token(data.get("id", ""), required=True)
    state = normalize_state(_text(data.get("state", ""), limit=40, required=True))
    content_hash = _hash(data.get("content_hash", ""))
    parser_version = _token(data.get("parser_version", ""))
    error = _token(data.get("error_category", ""))
    note = _text(data.get("note", ""), limit=500)
    http_status = data.get("http_status")
    if http_status is not None and (
        not isinstance(http_status, int) or not 100 <= http_status <= 599
    ):
        raise ValueError("Status HTTP invalid.")
    stamp = now()
    with closing(_open(cale(stare))) as con:
        init(con)
        row = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("Sursa nu există în registru.")
        if not can_transition(row["state"], state):
            raise ValueError("Tranziție de stare invalidă.")
        con.execute(
            """
            INSERT INTO source_attempts
              (source_id,attempted_at,state,http_status,error_category,content_hash,parser_version,note)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (source_id, stamp, state, http_status, error, content_hash, parser_version, note),
        )
        con.execute(
            """
            UPDATE source_registry SET state=?,last_attempt_at=?,last_http_status=?,
              last_error=?,last_hash=COALESCE(NULLIF(?,''),last_hash),
              parser_version=COALESCE(NULLIF(?,''),parser_version),updated_at=?
            WHERE id=?
            """,
            (state, stamp, http_status, error, content_hash, parser_version, stamp, source_id),
        )
        con.commit()
        updated = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
        return _row(updated)


def _source(stare, source_id: str) -> dict:
    source_id = _token(source_id, required=True)
    with closing(_open(cale(stare))) as con:
        init(con)
        row = con.execute("SELECT * FROM source_registry WHERE id=?", (source_id,)).fetchone()
    if row is None:
        raise ValueError("Sursa nu există în registru.")
    return _row(row)


def _celex_from_source(row: dict) -> str:
    value = row.get("identifier") or row.get("url") or ""
    try:
        return cellar.normalizeaza_celex(value)
    except ValueError:
        pass
    if row.get("url"):
        try:
            return cellar.normalizeaza_celex(row["url"])
        except ValueError:
            pass
    raise ValueError("Sursa UE nu are identificator CELEX valid.") from None


def _eu_hash(stare, celex: str) -> str:
    path = Path(stare.eu)
    if not path.exists():
        return ""
    with cellar.deschide(path, readonly=True) as con:
        row = con.execute("SELECT text_sha256 FROM eu_acte WHERE celex=?", (celex,)).fetchone()
    return row["text_sha256"] if row else ""


def sincronizeaza_ue(stare, source_id: str) -> dict:
    """Run one bounded CELEX sync for one registry row, using the existing EU importer."""
    row = _source(stare, source_id)
    if row["family"] != "ue_cellar":
        raise ValueError("Doar sursele UE Cellar/EUR-Lex pot fi sincronizate aici.")
    if row["state"] != "queued":
        row = pune_in_coada(stare, source_id)
    celex = _celex_from_source(row)
    from scripts import achizitii_ue

    try:
        result = achizitii_ue.importa(stare, {"celex": celex})
    except ValueError as exc:
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "failed",
                "error_category": "fetch_failed",
                "note": str(exc)[:500],
            },
        )
    if result.get("stare") == "metadate":
        return inregistreaza(
            stare,
            {
                "id": source_id,
                "state": "needs_review",
                "parser_version": "achizitii_ue.v1",
                "note": "Metadate UE disponibile, dar fără text RON/ENG compatibil.",
            },
        )
    content_hash = _eu_hash(stare, celex)
    inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "fetched",
            "http_status": 200,
            "content_hash": content_hash,
            "parser_version": "achizitii_ue.v1",
            "note": f"CELEX {celex} importat în limba {result.get('limba', 'necunoscută')}.",
        },
    )
    return inregistreaza(
        stare,
        {
            "id": source_id,
            "state": "changed" if result.get("schimbat") else "unchanged",
            "http_status": 200,
            "content_hash": content_hash,
            "parser_version": "achizitii_ue.v1",
        },
    )


def executa(stare, data: dict) -> dict:
    action = _text(data.get("action", "discover"), limit=40) or "discover"
    if action == "discover":
        return descopera(stare, data)
    if action == "queue":
        return pune_in_coada(stare, data.get("id", ""))
    if action == "record":
        return inregistreaza(stare, data)
    if action == "sync":
        return sincronizeaza_ue(stare, data.get("id", ""))
    raise ValueError("Acțiune registru necunoscută.")
