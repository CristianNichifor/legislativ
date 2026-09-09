"""Bounded, local-only dependencies on immutable imported parliamentary documents."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing

from scripts import documente_proiecte, dosare


def selectie(value):
    if not isinstance(value, dict) or set(value) != {"a", "b"}:
        raise ValueError("Selecteaza doua versiuni importate.")
    out = {}
    for side, ref in value.items():
        if not isinstance(ref, dict) or set(ref) != {"plx_id", "versiune_id"}:
            raise ValueError("Referinta de proiect invalida.")
        plx = dosare._text(ref["plx_id"], 200, True)
        ident = ref["versiune_id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{64}", ident):
            raise ValueError("Identificator de versiune invalid.")
        out[side] = {"plx_id": plx, "versiune_id": ident}
    if out["a"]["plx_id"] == out["b"]["plx_id"]:
        raise ValueError("Selecteaza initiative diferite.")
    return out


def citeste(stare, plx, ident, *, latest=False):
    base = {
        "sursa": "proiect_importat",
        "plx_id": plx,
        "versiune_id": ident,
        "nivel": "document",
        "stare": "sursa_indisponibila",
    }
    try:
        uri = documente_proiecte.cale_store(stare).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN")
            row = con.execute(
                "SELECT url FROM documente WHERE id=? AND plx_id=?", (ident, plx)
            ).fetchone()
            if row is None:
                return base
            url = row["url"]
            documente_proiecte.url_oficial(url)
            if latest:
                versions = con.execute(
                    "SELECT id,preluat_la FROM documente WHERE plx_id=? AND url=? "
                    "ORDER BY preluat_la DESC,id LIMIT 2",
                    (plx, url),
                ).fetchall()
                if len(versions) > 1 and versions[0]["preluat_la"] == versions[1]["preluat_la"]:
                    return {**base, "stare": "ordine_ambigua"}
                ident = versions[0]["id"]
            row = con.execute(
                "SELECT id,plx_id,url,label,sha256,preluat_la,status,"
                "length(octeti) bytes,length(CAST(text AS BLOB)) text_bytes FROM documente "
                "WHERE id=? AND plx_id=?",
                (ident, plx),
            ).fetchone()
            meta = dict(row)
            base.update(versiune_id=ident, metadate=meta)
            if (
                not meta["bytes"]
                or meta["bytes"] > documente_proiecte.MAX_BYTES
                or (meta["text_bytes"] or 0) > 2_000_000
            ):
                return {**base, "stare": "limita_depasita"}
            data = con.execute("SELECT octeti,text FROM documente WHERE id=?", (ident,)).fetchone()
            sha = hashlib.sha256(data["octeti"]).hexdigest()
            expected = hashlib.sha256(json.dumps([plx, url, sha]).encode()).hexdigest()
            if sha != meta["sha256"] or ident != expected:
                return {**base, "stare": "integritate_invalida"}
            base["sha256_octeti"] = sha
            if (
                meta["status"] != "extras"
                or not isinstance(data["text"], str)
                or not data["text"].strip()
            ):
                return {**base, "stare": "extragere_indisponibila"}
            return {
                **base,
                "stare": "capturat",
                "algoritm": "sha256-text-import-v1",
                "sha256_continut": hashlib.sha256(data["text"].encode("utf-8")).hexdigest(),
            }
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return base


def actualizeaza(stare, selection, manifest):
    out = {}
    baseline = {
        d["versiune_id"]: d
        for d in manifest.get("dependente", [])
        if d.get("sursa") == "proiect_importat"
    }
    for side, ref in selectie(selection).items():
        old = citeste(stare, ref["plx_id"], ref["versiune_id"])
        new = citeste(stare, ref["plx_id"], ref["versiune_id"], latest=True)
        if old["stare"] != "capturat" or new["stare"] != "capturat":
            raise ValueError(
                "Importurile nu pot fi comparate; verifica extragerea si integritatea."
            )
        retained = baseline.get(ref["versiune_id"])
        if retained and any(
            old.get(k) != retained.get(k) for k in ("sha256_octeti", "sha256_continut")
        ):
            raise ValueError("Versiunea originala nu mai corespunde dovezii salvate.")
        out[side] = {"plx_id": ref["plx_id"], "versiune_id": new["versiune_id"]}
    return out


def compara(stare, old):
    retained = citeste(stare, old["plx_id"], old["versiune_id"])
    current = citeste(stare, old["plx_id"], old["versiune_id"], latest=True)
    valid = (
        retained["stare"] == old.get("stare") == "capturat"
        and old.get("algoritm") == "sha256-text-import-v1"
        and all(retained.get(k) == old.get(k) for k in ("sha256_octeti", "sha256_continut"))
    )
    bytes_changed = (
        old.get("sha256_octeti") != current["sha256_octeti"]
        if valid and current.get("sha256_octeti")
        else None
    )
    text_changed = (
        old.get("sha256_continut") != current["sha256_continut"]
        if valid and current.get("sha256_continut")
        else None
    )
    status = "indisponibil"
    if valid and current["stare"] == "capturat":
        status = "schimbat" if bytes_changed or text_changed else "neschimbat"
    return {
        "id": old["id"],
        "stare": status,
        "salvat": old,
        "curent": current,
        "octeti_schimbati": bytes_changed,
        "text_schimbat": text_changed,
        "metadate_schimbate": old.get("metadate") != current.get("metadate"),
    }
