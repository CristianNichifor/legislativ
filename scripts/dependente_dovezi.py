"""Versioned, read-only corpus dependencies captured when saving a research run."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts import dosare

MAX_PROVISIONS = 2000
MAX_TEXT_BYTES = 2_000_000


def _digest(value):
    return hashlib.sha256(dosare._json(value).encode("utf-8")).hexdigest()


def _references(finding):
    evidence = finding["dovada"]
    if finding["tip"] == "contradictie":
        return [evidence.get(side) or {} for side in ("a", "b")]
    return [evidence]


def _capture(con, reference):
    act_id, locator = reference
    result = {
        "sursa": "corpus",
        "act_id": act_id,
        "locator": locator,
        "nivel": "prevedere" if locator else "act",
        "stare": "referinta_incompleta",
    }
    if not act_id:
        return result
    if con is None:
        return {**result, "stare": "sursa_indisponibila"}
    act = con.execute(
        "SELECT id, sursa_url, citit_la, id_portal, id_act_portal FROM acte WHERE id=?",
        (act_id,),
    ).fetchone()
    if act is None:
        return {**result, "stare": "act_negasit"}
    result["metadate"] = dict(act)
    clause = " AND locator=?" if locator else ""
    params = (act_id, locator) if locator else (act_id,)
    rows = con.execute(
        "SELECT locator, ord, text, vigoare_de_la, vigoare_pana_la FROM provizii "
        f"WHERE act_id=?{clause} ORDER BY ord LIMIT ?",
        (*params, MAX_PROVISIONS + 1),
    )
    retained, size = [], 0
    for row in rows:
        value = dict(row)
        size += len(dosare._json(value).encode("utf-8"))
        if len(retained) == MAX_PROVISIONS or size > MAX_TEXT_BYTES:
            return {**result, "stare": "limita_depasita"}
        retained.append(value)
    if not retained:
        return {**result, "stare": "prevederi_negasite"}
    return {
        **result,
        "stare": "capturat",
        "numar_prevederi": len(retained),
        "sha256_continut": _digest(retained),
        "algoritm": "sha256-json-prevederi-v1",
    }


def captureaza(stare, report):
    from scripts.revizuiri import constatari

    findings = constatari({"raport": report})
    dependencies, links = {}, []
    for finding in findings:
        identifiers = []
        for source in _references(finding):
            reference = (source.get("act_id") or None, source.get("locator") or None)
            ident = _digest(["corpus", *reference])[:32]
            dependencies.setdefault(ident, reference)
            if ident not in identifiers:
                identifiers.append(ident)
        links.append({"constatare_id": finding["id"], "dependente": identifiers})

    def capture(con):
        result = []
        for ident, reference in dependencies.items():
            try:
                value = _capture(con, reference)
            except sqlite3.Error:
                value = {**_capture(None, reference), "stare": "sursa_indisponibila"}
            result.append({"id": ident, **value})
        return result

    path = getattr(stare, "corpus", None)
    try:
        if path is None:
            records = capture(None)
        else:
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as con:
                con.row_factory = sqlite3.Row
                # All dependency reads share one snapshot; never migrate or fetch sources.
                con.execute("BEGIN")
                records = capture(con)
    except (OSError, sqlite3.Error):
        records = capture(None)
    return {
        "schema_version": 1,
        "dependente": records,
        "constatari": links,
        "limitari": [
            "Amprente ale corpusului la salvare, nu ale octetilor documentelor oficiale.",
            "Raportul si manifestul sunt citite separat; nu certifica aceeasi versiune a sursei.",
            "Identificare exacta dupa act_id; fara rezolvare aproximativa a citarilor.",
            "Fara locator se amprenteaza toate prevederile actului, nu un articol dedus.",
            "Numai dependentele corpus ale exemplelor pastrate; nu dovada exhaustivitatii.",
            "Referintele UE, deciziile CCR si proiectele nu au dependente sursa capturate aici.",
        ],
    }
