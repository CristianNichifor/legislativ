"""Immutable local EU text observations, not legal versions or compliance findings."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

FIELDS = (
    "celex",
    "work_uri",
    "expression_uri",
    "manifestation_uri",
    "limba",
    "format",
    "titlu",
    "data_document",
    "tip_uri",
    "in_vigoare",
    "item_url",
    "sursa_url",
    "text",
    "text_sha256",
    "citit_la",
)
MAX_SNAPSHOT_BYTES = 8_000_000
MAX_DOSSIER_BYTES = 2_000_000
MAX_REFERENCES = 20
LIMITATION = (
    "Instantanee ale textului extras local, nu ale octetilor descarcati. "
    "Referinte contextuale, nu constatari de incompatibilitate UE. "
    "Nu sunt incluse in verificarea dependentelor constatarilor. "
    "Data documentului si data colectarii nu stabilesc aplicabilitatea juridica."
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS eu_instantanee (
    id TEXT PRIMARY KEY,
    celex TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eu_instantanee_celex ON eu_instantanee(celex);
CREATE TRIGGER IF NOT EXISTS eu_instantanee_no_update BEFORE UPDATE ON eu_instantanee
BEGIN SELECT RAISE(ABORT, 'EU snapshots are append-only'); END;
CREATE TRIGGER IF NOT EXISTS eu_instantanee_no_delete BEFORE DELETE ON eu_instantanee
BEGIN SELECT RAISE(ABORT, 'EU snapshots are append-only'); END;
"""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def citeste_curenta(con, celex, *, budget=MAX_SNAPSHOT_BYTES):
    # Bound every column before materializing text or potentially corrupt metadata.
    sizes = con.execute(
        "SELECT "
        + ",".join(f"length(CAST({f} AS BLOB))" for f in FIELDS)
        + " FROM eu_acte WHERE celex=?",
        (celex,),
    ).fetchone()
    base = {"celex": celex, "stare": "act_negasit"}
    if sizes is None:
        return base
    if sum(n or 0 for n in sizes) > budget:
        return {**base, "stare": "limita_depasita"}
    row = con.execute(
        "SELECT " + ",".join(FIELDS) + " FROM eu_acte WHERE celex=?",
        (celex,),
    ).fetchone()
    data = dict(zip(FIELDS, row, strict=True))
    for key, value in data.items():
        if key == "in_vigoare":
            if value not in (None, 0, 1):
                return {**base, "stare": "integritate_invalida"}
        elif value is not None and not isinstance(value, str):
            return {**base, "stare": "integritate_invalida"}
    if not data["text"] or not data["text"].strip():
        return {**base, "stare": "text_indisponibil"}
    if hashlib.sha256(data["text"].encode()).hexdigest() != data["text_sha256"]:
        return {**base, "stare": "integritate_invalida"}
    if any(
        not data[k]
        for k in (
            "work_uri",
            "expression_uri",
            "manifestation_uri",
            "limba",
            "format",
            "item_url",
            "sursa_url",
            "citit_la",
        )
    ):
        return {**base, "stare": "provenienta_incompleta"}
    payload = {"schema_version": 1, "algoritm": "sha256-json-text-ue-v1", "sursa": data}
    encoded = _json(payload).encode()
    snapshot = {
        **base,
        "stare": "capturat",
        "id": hashlib.sha256(encoded).hexdigest(),
        **payload,
    }
    if len(_json(snapshot).encode()) > budget:
        return {**base, "stare": "limita_depasita"}
    return snapshot


def arhiveaza_curenta(con, celex):
    """Called inside the import transaction, before and after replacing the current row."""
    snapshot = citeste_curenta(con, celex)
    if snapshot["stare"] == "act_negasit":
        return
    if snapshot["stare"] != "capturat":
        raise ValueError("Textul UE nu poate fi arhivat: " + snapshot["stare"])
    encoded = _json(snapshot)
    existing = con.execute(
        "SELECT snapshot_json FROM eu_instantanee WHERE id=?", (snapshot["id"],)
    ).fetchone()
    if existing is not None and existing[0] != encoded:
        raise ValueError("Instantaneea UE existenta are integritate invalida.")
    con.execute(
        "INSERT INTO eu_instantanee VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
        (snapshot["id"], celex, encoded),
    )


def captureaza(stare, references):
    """Read one local SQLite snapshot; never import, migrate, or backfill old dossiers."""
    from scripts.cellar import normalizeaza_celex

    result = {"schema_version": 1, "instantanee": [], "limitare": LIMITATION}
    ids = []
    for ref in references[:MAX_REFERENCES]:
        try:
            celex = normalizeaza_celex(ref.get("celex", ""))
        except (ValueError, TypeError, AttributeError):
            result["instantanee"].append({"stare": "referinta_invalida"})
            continue
        if celex not in ids:
            ids.append(celex)
    result["trunchiat"] = len(references) > MAX_REFERENCES
    captured = []
    try:
        path = Path(stare.eu).resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as con:
            con.execute("BEGIN")
            remaining = MAX_DOSSIER_BYTES
            for celex in ids:
                snapshot = citeste_curenta(con, celex, budget=remaining)
                if snapshot["stare"] == "capturat":
                    remaining -= len(_json(snapshot).encode())
                captured.append(snapshot)
    except (OSError, sqlite3.Error, AttributeError, TypeError, ValueError):
        captured = [{"celex": celex, "stare": "sursa_indisponibila"} for celex in ids]
    result["instantanee"].extend(captured)
    return result
