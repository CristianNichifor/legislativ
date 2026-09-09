"""Read-only comparisons of retained proposal dependencies, never legal freshness verdicts."""

import difflib
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from scripts import dosare, interventii_propuneri, propuneri

ENGINE = "analiza-propunere-v1"
MAX_ACTS = 20
MAX_ROWS = 500
MAX_SOURCE_BYTES = 400_000
MAX_TEXT = 8000
MAX_DIFF_LINES = 200


def sha(value):
    return hashlib.sha256(dosare._json(value).encode()).hexdigest()


def captura(stare, ids, *, max_rows=MAX_ROWS, max_bytes=MAX_SOURCE_BYTES):
    records, size = [], 0
    path = getattr(stare, "corpus", None)
    try:
        if path is None:
            raise OSError("No corpus")
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN")
            for ident in ids:
                meta = con.execute(
                    "SELECT id,sursa_url,citit_la FROM acte WHERE id=?", (ident,)
                ).fetchone()
                source = {"act_id": ident, "stare": "indisponibil", "prevederi": []}
                if meta is not None:
                    source["metadate"] = dict(meta)
                    source["stare"] = "verificat"
                    rows = con.execute(
                        "SELECT locator,ord,text,vigoare_de_la,vigoare_pana_la FROM provizii "
                        "WHERE act_id=? ORDER BY ord LIMIT ?",
                        (ident, max_rows + 1),
                    )
                    locators = set()
                    for row in rows:
                        value = dict(row)
                        length = len(dosare._json(value).encode())
                        if len(source["prevederi"]) == max_rows or size + length > max_bytes:
                            source["stare"] = "partial"
                            break
                        source["prevederi"].append(value)
                        if not (value["text"] or "").strip() or value["locator"] in locators:
                            source["stare"] = "partial"
                        locators.add(value["locator"])
                        size += length
                    if not source["prevederi"] and source["stare"] != "partial":
                        source["stare"] = "indisponibil"
                records.append(source)
    except (OSError, sqlite3.Error):
        records = [{"act_id": ident, "stare": "indisponibil", "prevederi": []} for ident in ids]
    for record in records:
        record["sha256"] = sha(record)
    return records


def _fragment(rows):
    text = "\n".join(str(r["locator"]) + "\n" + (r["text"] or "") for r in rows)
    return text[:MAX_TEXT], len(text) > MAX_TEXT


def _pair(before, after, *, kind="analiza", locator=None):
    complete = before.get("stare") == after.get("stare") == "verificat"
    old_rows, new_rows = before.get("prevederi", []), after.get("prevederi", [])
    old_hash, new_hash = sha(old_rows), sha(new_rows)
    status = ("neschimbat" if old_hash == new_hash else "schimbat") if complete else "indisponibil"
    old_text, old_cut = _fragment(old_rows)
    new_text, new_cut = _fragment(new_rows)
    delta = (
        list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="retinut",
                tofile="local",
                lineterm="",
            )
        )
        if complete and status == "schimbat"
        else []
    )
    return {
        "tip": kind,
        "act_id": before["act_id"],
        "locator": locator,
        "stare": status,
        "baza_stare": before.get("stare"),
        "curent_stare": after.get("stare"),
        "sha256_retinut": old_hash if before.get("stare") == "verificat" else None,
        "sha256_curent": new_hash if after.get("stare") == "verificat" else None,
        "metadate_retinute": before.get("metadate"),
        "metadate_curente": after.get("metadate"),
        "metadate_schimbate": before.get("metadate") != after.get("metadate") if complete else None,
        "inainte": old_text,
        "dupa": new_text,
        "diferente": delta[:MAX_DIFF_LINES],
        "text_trunchiat": old_cut or new_cut,
        "diferente_trunchiate": len(delta) > MAX_DIFF_LINES,
        "motiv": "Comparatie a randurilor locale capturate, inclusiv date si ordine."
        if complete
        else "Baza sau sursa curenta lipseste, este partiala ori ambigua.",
    }


def compara(stare, proposal, baseline, *, current_sources=None):
    dependencies = []
    limitations = [
        "Comparatie locala, fara descarcari sau verdict juridic.",
        "Neschimbat inseamna continut capturat egal, nu legislatie actuala sau aplicabila.",
        "Metadatele sunt comparate separat de text, datele de vigoare si ordinea randurilor.",
        "Fragmentele si diferentele sunt limitate; originalele salvate nu sunt inlocuite.",
    ]
    compatible = (
        baseline
        and baseline.get("engine_version") == ENGINE
        and baseline.get("schema_version") == 1
    )
    if baseline:
        old = baseline.get("surse", [])
        if compatible and len(old) <= MAX_ACTS and sha(old) == baseline.get("surse_sha256"):
            valid_hashes = all(
                s.get("sha256") == sha({k: v for k, v in s.items() if k != "sha256"}) for s in old
            )
            if valid_hashes:
                fresh = (
                    current_sources
                    if current_sources is not None
                    else captura(stare, [s["act_id"] for s in old])
                )
                current_map = {s["act_id"]: s for s in fresh}
                dependencies.extend(
                    _pair(s, current_map.get(s["act_id"], {"stare": "indisponibil"})) for s in old
                )
            else:
                compatible = False
        else:
            compatible = False
        if not compatible:
            limitations.append("Contractul sau amprenta analizei de baza nu permite comparatia.")
    intervention = proposal.get("interventie")
    if intervention and intervention.get("schema_version") == 1:
        snapshot = intervention["tinta"]
        intent = intervention["cerere"]
        old = {
            "act_id": intent["act_id"],
            "stare": "verificat",
            "metadate": snapshot["act"],
            "prevederi": snapshot["prevederi"],
        }
        if sha(snapshot) != intent["sha256_tinta"]:
            old["stare"] = "indisponibil"
        try:
            fresh = interventii_propuneri._snapshot(stare, intent)
            new = {"stare": "verificat", "metadate": fresh["act"], "prevederi": fresh["prevederi"]}
            error = None
        except (ValueError, OSError, sqlite3.Error) as exc:
            new, error = {"stare": "indisponibil"}, str(exc)
        target = _pair(old, new, kind="tinta_structurata", locator=intent["locator"])
        if error:
            target["motiv"] = error
        dependencies.append(target)
    elif intervention:
        limitations.append("Contractul tintei structurate nu este suportat.")
    counts = {
        s: sum(d["stare"] == s for d in dependencies)
        for s in ("schimbat", "neschimbat", "indisponibil")
    }
    unsupported = bool(
        (baseline and not compatible) or (intervention and intervention.get("schema_version") != 1)
    )
    incomplete = unsupported or not dependencies or bool(counts["indisponibil"])
    if compatible and baseline.get("acoperire", {}).get("acte_recunoscute", 0) > len(
        baseline.get("surse", [])
    ):
        incomplete = True
        limitations.append("Analiza de baza a omis acte peste limita de captura.")
    status = (
        "schimbat"
        if counts["schimbat"]
        else "nesuportat"
        if unsupported or not dependencies
        else "indisponibil"
        if incomplete
        else "neschimbat"
    )
    return {
        "schema_version": 1,
        "verificat_la": datetime.now(UTC).isoformat(),
        "propunere_id": proposal["id"],
        "revizie": proposal["revizie"],
        "propunere_sha256": sha(proposal),
        "analiza_baza_id": baseline["id"] if baseline else None,
        "surse_baza_sha256": baseline.get("surse_sha256") if baseline else None,
        "stare": status,
        "comparatie_incompleta": incomplete,
        "totaluri": counts,
        "dependente": dependencies,
        "limitari": limitations,
    }


def verifica(stare, dossier_id, run_id, finding_id, revision, analysis_id=None):
    path = dosare.cale(stare)
    data = propuneri.citeste(path, dossier_id, run_id, finding_id, revision)
    baseline = propuneri.analize(
        path, dossier_id, run_id, finding_id, revision, analysis_id=analysis_id
    )["selectata"]
    result = compara(stare, data["propunere"], baseline)
    result["salvata"] = False
    return result


def citeste_cerere(stare, qs):
    return verifica(
        stare,
        qs.get("id", [None])[0],
        qs.get("rulare_id", [None])[0],
        qs.get("constatare_id", [None])[0],
        int(qs.get("revizie", ["0"])[0]),
        qs.get("analiza_id", [None])[0],
    )
