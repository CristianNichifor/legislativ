"""Explicit EU source acquisition; local reads never import or migrate data."""

import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from scripts import articole_ue, cellar, instantanee_ue
from scripts.transport_cellar import TransportCellar, url_oficial

IMPORT_LOCK = threading.Lock()
MAX_PARTS = 10
PAGE_SIZE = 20
ARTICLE_PAGE_SIZE = 80
PROVISION_PAGE_SIZE = 120
LANGUAGE_LABELS = {
    "RON": "romana oficiala",
    "ENG": "engleza oficiala, fallback explicit cand textul romanesc compatibil lipseste",
}
IMPORT_CONTRACT = "celex-on-demand-source-v1"
ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS eu_achizitii (
 celex TEXT PRIMARY KEY, incercat_la TEXT NOT NULL, reusit_la TEXT,
 stare TEXT NOT NULL, eroare TEXT
)
"""

LANGUAGE_NOTES = {
    "official_ro": "Text oficial romanesc selectat din Cellar.",
    "official_en_fallback": (
        "Text oficial englez selectat doar ca fallback explicit; lipsa textului romanesc "
        "compatibil nu este concluzie juridica."
    ),
    "text_unavailable": (
        "Metadate Cellar disponibile, dar fara stream text RON/ENG compatibil; nu este "
        "concluzie juridica."
    ),
    "language_unavailable": (
        "Cellar nu a returnat manifestari pentru limbile cerute; sursa ramane indisponibila "
        "pentru aceasta incercare si nu este concluzie juridica."
    ),
}


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


def _article_summary(snapshot):
    return articole_ue.summary(snapshot, page_size=ARTICLE_PAGE_SIZE)


def _provision_summary(snapshot):
    if snapshot.get("stare") != "capturat":
        return {"total": 0, "randuri": [], "trunchiat": False}
    source = snapshot.get("sursa") or {}
    try:
        blocks = cellar.provizii_din_text(source["celex"], source["text"], source["limba"])
    except (KeyError, TypeError, ValueError):
        return {"total": 0, "randuri": [], "trunchiat": False, "stare": "indisponibil"}
    return {
        "total": len(blocks),
        "randuri": [
            {
                "locator": b.locator,
                "fel": b.fel,
                "titlu": b.titlu,
                "limba": b.limba,
                "ord": b.ord,
                "sha256": hashlib.sha256(b.text.encode()).hexdigest(),
            }
            for b in blocks[:PROVISION_PAGE_SIZE]
        ],
        "trunchiat": len(blocks) > PROVISION_PAGE_SIZE,
    }


def _source_metadata(snapshot):
    source = snapshot.get("sursa") or {}
    if snapshot.get("stare") != "capturat":
        return None
    return {
        "celex": source.get("celex"),
        "celex_url": source.get("sursa_url"),
        "item_url": source.get("item_url"),
        "work_uri": source.get("work_uri"),
        "expression_uri": source.get("expression_uri"),
        "manifestation_uri": source.get("manifestation_uri"),
        "language": source.get("limba"),
        "format": source.get("format"),
        "title": source.get("titlu"),
        "document_date": source.get("data_document"),
        "legal_type_uri": source.get("tip_uri"),
        "in_force": source.get("in_vigoare"),
        "read_at": source.get("citit_la"),
        "text_sha256": source.get("text_sha256"),
    }


def _manifestation_inventory(manifestations):
    counts = {}
    readable = []
    for m in manifestations:
        counts[m.limba] = counts.get(m.limba, 0) + 1
        if m.format in cellar.FORMATE_TEXT:
            readable.append(
                {
                    "language": m.limba,
                    "format": m.format,
                    "item_url": m.item_url,
                    "title": m.titlu,
                }
            )
    return {
        "total": len(manifestations),
        "languages": counts,
        "readable": readable[:20],
        "readable_truncated": len(readable) > 20,
    }


def _language_contract(language, preference=cellar.LIMBI_IMPLICITE):
    fallback = bool(language and preference and language != preference[0])
    state = "official_en_fallback" if fallback else "official_ro" if language == "RON" else ""
    return {
        "preferinta": list(preference),
        "aleasa": language or None,
        "eticheta": LANGUAGE_LABELS.get(language or "", "limba necunoscuta"),
        "fallback": fallback,
        "stare": state,
        "nota": LANGUAGE_NOTES.get(state, ""),
    }


def _missing_language_contract(state, preference=cellar.LIMBI_IMPLICITE):
    return {
        "preferinta": list(preference),
        "aleasa": None,
        "eticheta": "limba indisponibila",
        "fallback": False,
        "stare": state,
        "nota": LANGUAGE_NOTES[state],
    }


def _summary(snapshot):
    out = {
        **snapshot,
        "sursa": {k: v for k, v in snapshot.get("sursa", {}).items() if k != "text"},
        "articole": _article_summary(snapshot),
        "provizii": _provision_summary(snapshot),
    }
    source = snapshot.get("sursa") or {}
    out["limba_import"] = _language_contract(source.get("limba"))
    out["source_metadata"] = _source_metadata(snapshot)
    return out


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
            if attempt and out["stare"] == "neimportat" and attempt["stare"] == "indisponibil":
                out["stare"] = "indisponibil"
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


def _cerere_import(request):
    if not isinstance(request, dict):
        raise ValueError("Cerere de import invalida.")
    allowed = {"celex", "identifier", "limbi"}
    if not set(request) <= allowed:
        raise ValueError("Cerere de import invalida.")
    identifier = request.get("identifier", request.get("celex"))
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("Identificator CELEX invalid.")
    celex = celex_valid(cellar.normalizeaza_celex(identifier))
    raw_languages = request.get("limbi", "RON,ENG")
    values = raw_languages.split(",") if isinstance(raw_languages, str) else raw_languages
    if not isinstance(values, (list, tuple)) or any(not isinstance(x, str) for x in values):
        raise ValueError("Cerere de import invalida.")
    limbi = cellar._limbi(tuple(x.strip() for x in values))
    return identifier.strip(), celex, limbi


def _contract_payload(result, *, identifier, limbi):
    source_hash = result.get("text_sha256") or ""
    snapshot_id = result.get("instantanee")
    return {
        **result,
        "contract": IMPORT_CONTRACT,
        "source_identifier": identifier,
        "language_preference": list(limbi),
        "selected_language": result.get("limba"),
        "selected_language_label": result.get("limba_import", {}).get("eticheta", ""),
        "language_fallback": result.get("limba_import", {}).get("fallback", False),
        "language_state": result.get("limba_import", {}).get("stare", ""),
        "language_note": result.get("limba_import", {}).get("nota", ""),
        "source_hash": source_hash,
        "source_metadata": result.get("source_metadata"),
        "manifestari": result.get("manifestari")
        or {"total": 0, "languages": {}, "readable": [], "readable_truncated": False},
        "snapshot": {
            "id": snapshot_id,
            "text_sha256": source_hash,
            "source_hash": source_hash,
        }
        if snapshot_id
        else None,
    }


def importa(stare, request):
    identifier, celex, limbi = _cerere_import(request)
    if not IMPORT_LOCK.acquire(blocking=False):
        raise ValueError("Un import UE este deja in curs. Reincearca dupa terminarea lui.")
    try:
        return _contract_payload(_importa(stare, celex, limbi), identifier=identifier, limbi=limbi)
    finally:
        IMPORT_LOCK.release()


def _importa(stare, celex, limbi=cellar.LIMBI_IMPLICITE):
    try:
        transport = TransportCellar()
        try:
            manifestations = cellar.manifestari_celex(
                celex, limbi=limbi, opener=transport, timeout=15
            )
        except cellar.CelexNegasit:
            with cellar.deschide(stare.eu) as con:
                _attempt(con, celex, "indisponibil", LANGUAGE_NOTES["language_unavailable"])
            return {
                "celex": celex,
                "stare": "indisponibil",
                "schimbat": False,
                "manifestari": {
                    "total": 0,
                    "languages": {},
                    "readable": [],
                    "readable_truncated": False,
                },
                "limba_import": _missing_language_contract("language_unavailable", limbi),
                "nota": LANGUAGE_NOTES["language_unavailable"],
            }
        if len(manifestations) > 500:
            raise ValueError("Prea multe manifestari.")
        for m in manifestations:
            url_oficial(m.item_url)
        inventory = _manifestation_inventory(manifestations)
        with cellar.deschide(stare.eu) as con:
            cellar.scrie_manifestari(con, celex, manifestations)
        try:
            chosen = cellar.alege_manifestare_text(manifestations, limbi=limbi)
        except cellar.TextIndisponibil:
            with cellar.deschide(stare.eu) as con:
                _attempt(
                    con, celex, "metadate", "Metadate disponibile; fara text RON/ENG compatibil."
                )
            return {
                "celex": celex,
                "stare": "metadate",
                "schimbat": False,
                "manifestari": inventory,
                "limba_import": _missing_language_contract("text_unavailable", limbi),
                "nota": LANGUAGE_NOTES["text_unavailable"],
            }
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
            current = instantanee_ue.citeste_curenta(con, celex)
            _attempt(con, celex, "ok")
        return {
            "celex": celex,
            "stare": "ok",
            "limba": chosen.limba,
            "limba_import": _language_contract(chosen.limba, limbi),
            "instantanee": current.get("id"),
            "text_sha256": current.get("sursa", {}).get("text_sha256"),
            "source_metadata": _source_metadata(current),
            "manifestari": inventory,
            "articole": _article_summary(current),
            "provizii": _provision_summary(current),
            "nota": _language_contract(chosen.limba, limbi).get("nota", ""),
            "schimbat": changed,
        }
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
