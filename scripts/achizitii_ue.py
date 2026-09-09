"""Explicit EU source acquisition; local reads never import or migrate data."""

import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from scripts import cellar, instantanee_ue
from scripts.transport_cellar import TransportCellar, url_oficial

IMPORT_LOCK = threading.Lock()
MAX_PARTS = 10
PAGE_SIZE = 20
ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS eu_achizitii (
 celex TEXT PRIMARY KEY, incercat_la TEXT NOT NULL, reusit_la TEXT,
 stare TEXT NOT NULL, eroare TEXT
)
"""


def celex_valid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Z()._-]{5,50}", value):
        raise ValueError("Identificator CELEX invalid.")
    return value


def _attempt(con, celex, status, error=None):
    con.execute(ATTEMPT_SCHEMA)
    now = datetime.now(UTC).isoformat()
    con.execute(
        "INSERT INTO eu_achizitii VALUES (?,?,?,?,?) ON CONFLICT(celex) DO UPDATE SET "
        "incercat_la=excluded.incercat_la, "
        "reusit_la=coalesce(excluded.reusit_la,eu_achizitii.reusit_la), "
        "stare=excluded.stare, eroare=excluded.eroare",
        (celex, now, now if status == "ok" else None, status, error),
    )


def _summary(snapshot):
    return {
        **snapshot,
        "sursa": {k: v for k, v in snapshot.get("sursa", {}).items() if k != "text"},
    }


def detaliu(stare, celex, *, offset=0, snapshot_id=None):
    celex = celex_valid(celex)
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 100_000:
        raise ValueError("Pagina invalida.")
    if snapshot_id is not None and (
        not isinstance(snapshot_id, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_id)
    ):
        raise ValueError("Instantanee invalida.")
    out = {
        "celex": celex,
        "stare": "neimportat",
        "curenta": None,
        "incercare": None,
        "manifestari": [],
        "instantanee": [],
        "mai_multe": False,
        "offset": offset,
    }
    path = Path(stare.eu)
    if not path.exists():
        if snapshot_id:
            raise ValueError("Instantaneea nu exista.")
        return out
    with cellar.deschide(path, readonly=True) as con:
        budget = 0

        def stop():
            nonlocal budget
            budget += 1
            return budget > 20_000

        con.set_progress_handler(stop, 10_000)
        con.execute("BEGIN")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "eu_acte" not in tables:
            raise sqlite3.DatabaseError("EU source schema unavailable")
        current = instantanee_ue.citeste_curenta(con, celex)
        if snapshot_id:
            if current.get("id") == snapshot_id:
                return current
            if "eu_instantanee" not in tables:
                raise ValueError("Instantaneea nu exista.")
            row = con.execute(
                "SELECT snapshot_json FROM eu_instantanee WHERE celex=? AND id=? "
                "AND length(CAST(snapshot_json AS BLOB))<=?",
                (celex, snapshot_id, instantanee_ue.MAX_SNAPSHOT_BYTES),
            ).fetchone()
            if not row:
                raise ValueError("Instantaneea nu exista sau depaseste limita.")
            data = json.loads(row[0])
            payload = {k: data[k] for k in ("schema_version", "algoritm", "sursa")}
            digest = hashlib.sha256(instantanee_ue._json(payload).encode()).hexdigest()
            source = data["sursa"]
            if (
                digest != snapshot_id
                or data.get("id") != snapshot_id
                or data.get("celex") != celex
                or source["celex"] != celex
                or hashlib.sha256(source["text"].encode()).hexdigest() != source["text_sha256"]
            ):
                raise ValueError("Integritatea instantaneei este invalida.")
            return data
        out["curenta"] = _summary(current)
        if current["stare"] == "capturat":
            out["stare"] = "text_disponibil"
        elif current["stare"] != "act_negasit":
            out["stare"] = current["stare"]
        if "eu_manifestari" in tables:
            rows = con.execute(
                "SELECT limba,format,titlu,item_url FROM eu_manifestari WHERE celex=? "
                "ORDER BY limba,format,item_url LIMIT 101",
                (celex,),
            ).fetchall()
            out["manifestari"] = [dict(r) for r in rows[:100]]
            out["manifestari_trunchiate"] = len(rows) > 100
            if rows and out["stare"] == "neimportat":
                out["stare"] = "metadate"
        if "eu_achizitii" in tables:
            attempt = con.execute("SELECT * FROM eu_achizitii WHERE celex=?", (celex,)).fetchone()
            out["incercare"] = dict(attempt) if attempt else None
        if "eu_instantanee" in tables:
            rows = con.execute(
                "SELECT id,json_extract(snapshot_json,'$.sursa.limba') AS limba, "
                "json_extract(snapshot_json,'$.sursa.citit_la') AS citit_la, "
                "json_extract(snapshot_json,'$.sursa.text_sha256') AS text_sha256 "
                "FROM eu_instantanee WHERE celex=? ORDER BY citit_la DESC,id DESC LIMIT ? OFFSET ?",
                (celex, PAGE_SIZE + 1, offset),
            ).fetchall()
            out["instantanee"] = [dict(r) for r in rows[:PAGE_SIZE]]
            out["mai_multe"] = len(rows) > PAGE_SIZE
    return out


def importa(stare, request):
    if not isinstance(request, dict) or set(request) != {"celex"}:
        raise ValueError("Cerere de import invalida.")
    celex = celex_valid(request["celex"])
    if not IMPORT_LOCK.acquire(blocking=False):
        raise ValueError("Un import UE este deja in curs. Reincearca dupa terminarea lui.")
    try:
        return _importa(stare, celex)
    finally:
        IMPORT_LOCK.release()


def _importa(stare, celex):
    try:
        transport = TransportCellar()
        manifestations = cellar.manifestari_celex(celex, opener=transport, timeout=15)
        if len(manifestations) > 500:
            raise ValueError("Prea multe manifestari.")
        for m in manifestations:
            url_oficial(m.item_url)
        with cellar.deschide(stare.eu) as con:
            cellar.scrie_manifestari(con, celex, manifestations)
        try:
            chosen = cellar.alege_manifestare_text(manifestations)
        except cellar.TextIndisponibil:
            with cellar.deschide(stare.eu) as con:
                _attempt(
                    con, celex, "metadate", "Metadate disponibile; fara text RON/ENG compatibil."
                )
            return {"celex": celex, "stare": "metadate", "schimbat": False}
        parts = cellar._parti_manifestare(chosen, manifestations)
        if len(parts) > MAX_PARTS or any(p.limba != chosen.limba for p in parts):
            raise ValueError("Manifestare prea mare sau incoerenta.")
        # The CLI tolerates unreadable parts; an interactive update must never replace a
        # complete local text with only the successfully parsed parts of a failed download.
        text = "\n\n".join(cellar.descarca_text(p, opener=transport, timeout=15) for p in parts)
        transport.check_time()
        with cellar.deschide(stare.eu) as con:
            con.execute("BEGIN IMMEDIATE")
            previous = instantanee_ue.citeste_curenta(con, celex)
            source = previous.get("sursa", {})
            expected = {
                k: getattr(chosen, k)
                for k in (
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
                )
            }
            expected.update(
                text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                sursa_url=cellar.CELEX_URI.format(celex=celex),
            )
            changed = any(source.get(k) != v for k, v in expected.items())
            if changed:
                cellar.scrie_celex(con, celex, manifestations, chosen, text)
            else:
                instantanee_ue.arhiveaza_curenta(con, celex)
                cellar.scrie_manifestari(con, celex, manifestations)
            _attempt(con, celex, "ok")
        return {"celex": celex, "stare": "ok", "limba": chosen.limba, "schimbat": changed}
    except (
        OSError,
        ValueError,
        sqlite3.Error,
        cellar.CellarError,
        TypeError,
        LookupError,
        AttributeError,
    ) as exc:
        error = (
            "Preluarea UE a esuat sau sursa depaseste limitele disponibile. "
            "Textul local a fost pastrat."
        )
        try:
            with cellar.deschide(stare.eu) as con:
                _attempt(con, celex, "eroare", error)
        except (OSError, sqlite3.Error):
            error += " Incercarea nu a putut fi inregistrata."
        raise ValueError(error) from exc
