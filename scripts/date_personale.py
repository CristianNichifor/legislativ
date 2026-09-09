"""Prepare a private EU generation without modifying either source database."""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from pathlib import Path

from scripts import achizitii_ue, cellar, instantanee_ue

MAX_ROWS = 1_000_000
MAX_BYTES = 4_000_000_000
MAX_ROW_BYTES = instantanee_ue.MAX_SNAPSHOT_BYTES
TABLES = {
    "eu_acte": instantanee_ue.FIELDS,
    "eu_manifestari": instantanee_ue.FIELDS[:11],
    "eu_instantanee": ("id", "celex", "snapshot_json"),
    "eu_achizitii": ("celex", "incercat_la", "reusit_la", "stare", "eroare"),
}
PRIMARY_KEYS = {
    "eu_acte": ("celex",),
    "eu_manifestari": ("celex", "limba", "format", "item_url"),
    "eu_instantanee": ("id",),
    "eu_achizitii": ("celex",),
}


def _open(stack, path):
    con = stack.enter_context(
        closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True))
    )
    con.execute("PRAGMA trusted_schema=OFF")
    con.execute("PRAGMA query_only=ON")
    con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_ROW_BYTES + 65536)
    steps = 0

    def stop():
        nonlocal steps
        steps += 1
        return steps > 20_000

    con.set_progress_handler(stop, 10_000)
    con.execute("BEGIN")
    for table, columns in TABLES.items():
        row = con.execute("SELECT type, sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
        if row is None:
            if table == "eu_acte":
                raise ValueError("Missing eu_acte table")
            continue
        if row[0] != "table" or "VIRTUAL" in row[1].upper():
            raise ValueError("Unsupported EU table: " + table)
        # Identifiers come exclusively from TABLES, never from a source schema.
        info = con.execute(f"PRAGMA table_xinfo({table})").fetchall()
        if tuple(r[1] for r in info) != columns or any(r[6] for r in info):
            raise ValueError("Unsupported EU columns: " + table)
        keys = tuple(r[1] for r in sorted(info, key=lambda r: r[5]) if r[5])
        if keys != PRIMARY_KEYS[table]:
            raise ValueError("Unsupported EU primary key: " + table)
    return con


def _rows(con, table, budget):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
        return
    columns = TABLES[table]
    size = "+".join(f"coalesce(length(CAST({c} AS BLOB)),0)" for c in columns)
    count, total, largest = con.execute(
        f"SELECT count(*), coalesce(sum({size}),0), coalesce(max({size}),0) FROM {table}"
    ).fetchone()
    budget[0] -= total
    if count > MAX_ROWS or largest > MAX_ROW_BYTES or budget[0] < 0:
        raise ValueError("EU preparation size limit exceeded")
    yield from con.execute(f"SELECT {','.join(columns)} FROM {table}")


def _insert(con, table, row):
    columns = TABLES[table]
    con.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        row,
    )


def _archive(con, row):
    try:
        data = json.loads(row[2])
        payload = {k: data[k] for k in ("schema_version", "algoritm", "sursa")}
        source = data["sursa"]
        valid = (
            data["id"] == row[0]
            and data["celex"] == source["celex"] == row[1]
            and data["stare"] == "capturat"
            and payload["schema_version"] == 1
            and payload["algoritm"] == "sha256-json-text-ue-v1"
            and hashlib.sha256(instantanee_ue._json(payload).encode()).hexdigest() == row[0]
            and hashlib.sha256(source["text"].encode()).hexdigest() == source["text_sha256"]
        )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValueError("Invalid EU snapshot") from exc
    if not valid:
        raise ValueError("Invalid EU snapshot")
    existing = con.execute(
        "SELECT celex,snapshot_json FROM eu_instantanee WHERE id=?", (row[0],)
    ).fetchone()
    if existing is not None:
        if tuple(existing) != tuple(row[1:]):
            raise ValueError("Conflicting EU snapshot ID: " + str(row[0]))
        return
    _insert(con, "eu_instantanee", row)


def _merge(con, source, *, published, budget):
    for row in _rows(source, "eu_instantanee", budget):
        _archive(con, row)
    if not published:
        for row in _rows(source, "eu_achizitii", budget):
            _insert(con, "eu_achizitii", row)
    for row in _rows(source, "eu_acte", budget):
        celex = row[0]
        snapshot = instantanee_ue.citeste_curenta(source, celex)
        if snapshot["stare"] != "capturat":
            raise ValueError("Cannot preserve EU observation: " + snapshot["stare"])
        _archive(con, (snapshot["id"], celex, instantanee_ue._json(snapshot)))
        if (
            published
            and con.execute(
                "SELECT 1 FROM eu_acte JOIN eu_achizitii USING(celex) WHERE celex=?", (celex,)
            ).fetchone()
        ):
            continue
        con.execute("DELETE FROM eu_acte WHERE celex=?", (celex,))
        _insert(con, "eu_acte", row)
        if (
            published
            and not con.execute("SELECT 1 FROM eu_achizitii WHERE celex=?", (celex,)).fetchone()
        ):
            con.execute("DELETE FROM eu_manifestari WHERE celex=?", (celex,))
    # Replace public metadata as a set, including removal of obsolete manifestations.
    if published:
        con.execute("CREATE TEMP TABLE published_metadata (celex TEXT PRIMARY KEY)")
    for row in _rows(source, "eu_manifestari", budget):
        celex = row[0]
        if published:
            if con.execute("SELECT 1 FROM eu_achizitii WHERE celex=?", (celex,)).fetchone():
                continue
            if not con.execute(
                "SELECT 1 FROM published_metadata WHERE celex=?", (celex,)
            ).fetchone():
                con.execute("DELETE FROM eu_manifestari WHERE celex=?", (celex,))
                con.execute("INSERT INTO published_metadata VALUES (?)", (celex,))
        _insert(con, "eu_manifestari", row)


def prepare_eu(public_db, previous_effective_db, target_db):
    """Return a new private DB path; fail without publishing a partial target.

    The caller must quiesce all EU writers until activation completes and retain the
    previous effective DB. The target's parent must already be a private directory.
    None is allowed only for previous_effective_db (first activation).
    """
    target = Path(target_db).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    budget = [MAX_BYTES]
    with ExitStack() as stack:
        public = _open(stack, public_db)
        previous = (
            _open(stack, previous_effective_db) if previous_effective_db is not None else None
        )
        fd, name = tempfile.mkstemp(prefix=".eu-", suffix=".db", dir=target.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            with cellar.deschide(temporary) as con:
                con.execute(achizitii_ue.ATTEMPT_SCHEMA)
                con.execute("BEGIN")
                if previous is not None:
                    _merge(con, previous, published=False, budget=budget)
                _merge(con, public, published=True, budget=budget)
                for celex, text, language in con.execute("SELECT celex,text,limba FROM eu_acte"):
                    cellar.scrie_provizii_celex(con, celex, text, language)
            # Finish WAL before publishing a single self-contained SQLite file.
            with closing(sqlite3.connect(temporary)) as con:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                con.execute("PRAGMA journal_mode=DELETE")
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.link(temporary, target)  # Atomic publication, never replace an existing target.
        finally:
            temporary.unlink(missing_ok=True)
            Path(name + "-wal").unlink(missing_ok=True)
            Path(name + "-shm").unlink(missing_ok=True)
    return target
