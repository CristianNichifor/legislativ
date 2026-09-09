"""Bounded deterministic checks tied to immutable proposal revisions and source snapshots."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts import dosare, propuneri
from scripts.definitii import definitii, jargon
from scripts.redactare import conformitate, interventii_conflictuale
from scripts.referinte import referinte
from scripts.termene import obligatii

ENGINE = "analiza-propunere-v1"
MAX_ACTS = 20
MAX_ROWS = 500
MAX_SOURCE_BYTES = 400_000
MAX_RESULTS = 100
MAX_TERMS = 40
MAX_TERM_CHAR_PAIRS = 120_000


def _sha(value):
    return hashlib.sha256(dosare._json(value).encode()).hexdigest()


def _sources(stare, ids):
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
                        (ident, MAX_ROWS + 1),
                    )
                    locators = set()
                    for row in rows:
                        value = dict(row)
                        length = len(dosare._json(value).encode())
                        if len(source["prevederi"]) == MAX_ROWS or size + length > MAX_SOURCE_BYTES:
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
        # Never mix a failed acquisition with apparently complete source coverage.
        records = [{"act_id": ident, "stare": "indisponibil", "prevederi": []} for ident in ids]
    for record in records:
        record["sha256"] = _sha(record)
    return records


def _check(key, label, findings, *, status="verificat", note="", kind="semnale"):
    truncated = len(findings) > MAX_RESULTS
    return {
        "cheie": key,
        "eticheta": label,
        "stare": "partial" if truncated and status == "verificat" else status,
        "tip_rezultate": kind,
        "rezultate": findings[:MAX_RESULTS],
        "total": len(findings),
        "trunchiat": truncated,
        "limitare": note,
    }


def executa(stare, proposal):
    text = dosare._text(proposal["text"], 12000, True)
    checks = [
        _check(
            "redactare",
            "Forma si limbaj",
            [{**asdict(a), "explicatie": a.explicatie} for a in conformitate(text)],
            note="Reguli de redactare suportate; nu toate cerintele legistice.",
        ),
        _check(
            "conflicte_interne",
            "Operatii conflictuale in propunere",
            [
                {**asdict(c), "fel": c.fel, "explicatie": c.explicatie}
                for c in interventii_conflictuale(text)
            ],
            note="Coliziuni sintactice intre operatii recunoscute; "
            "nu contradictii intre toate legile.",
        ),
        _check(
            "termene",
            "Obligatii si termene extrase",
            [
                {
                    "fragment": o.text,
                    "instrument": o.tip_asteptat,
                    "institutie": o.institutie_text,
                    "termen_zile": o.termen_zile,
                    "ancora": o.ancora,
                    "data_limita": o.data_limita.isoformat() if o.data_limita else None,
                }
                for o in obligatii(text)
            ],
            kind="inventar",
            note="Inventar, nu incalcari constatate. "
            "Nu deduce data aplicarii sau depasirea termenului.",
        ),
    ]
    refs = referinte(text)
    acts = {r.act.id: r.act for r in refs if r.act}
    ids = sorted(acts)[:MAX_ACTS]
    sources = _sources(stare, ids)
    source_map = {s["act_id"]: s for s in sources}
    incomplete = len(acts) > MAX_ACTS or any(s["stare"] != "verificat" for s in sources)
    citation_results = []
    for ref in refs[:MAX_RESULTS]:
        source = source_map.get(ref.act.id) if ref.act else None
        matches = (
            [
                p
                for p in source["prevederi"]
                if p["locator"] == ref.locator.id and (p["text"] or "").strip()
            ]
            if source
            else []
        )
        available = bool(
            source
            and source["stare"] == "verificat"
            and (matches if ref.locator else source["prevederi"])
        )
        citation_results.append(
            {
                "fragment": ref.text,
                "act_id": ref.act.id if ref.act else None,
                "locator": ref.locator.id,
                "stare": "verificat" if available else "indisponibil" if ref.act else "nesuportat",
                "sursa_sha256": source["sha256"] if source else None,
                "motiv": "Regasita in sursa locala capturata."
                if available
                else "Referinta nerezolvata exact; nu dovedeste inexistenta normei.",
            }
        )
    citation_status = (
        "partial"
        if incomplete
        or len(refs) > MAX_RESULTS
        or any(r["stare"] != "verificat" for r in citation_results)
        else "verificat"
    )
    if not acts:
        citation_status = "nesuportat"
    elif ids and all(s["stare"] == "indisponibil" for s in sources):
        citation_status = "indisponibil"
    checks.append(
        _check(
            "citari",
            "Acoperirea citarilor locale",
            citation_results,
            status=citation_status,
            kind="inventar",
            note="Potriviri exacte, fara aliasuri sau context implicit. "
            "Prezenta nu certifica aplicabilitatea.",
        )
    )
    checks[-1].update(total=len(refs), trunchiat=len(refs) > MAX_RESULTS)
    # Bound the existing terminology engine's term-by-text comparison workload.
    term_limit = min(MAX_TERMS, max(1, MAX_TERM_CHAR_PAIRS // len(text)))
    terms = []
    seen_terms = set()
    for source in sources:
        for row in source["prevederi"]:
            if len(terms) > term_limit:
                break
            for term in definitii(row["text"] or "", act=acts[source["act_id"]]):
                term_key = (source["act_id"], term.termen, term.definitie)
                if term_key in seen_terms:
                    continue
                seen_terms.add(term_key)
                terms.append((term, source["act_id"], row["locator"], source["sha256"]))
                if len(terms) > term_limit:
                    break
    term_sources = {id(t): (act, loc, sha) for t, act, loc, sha in terms[:term_limit]}
    hits = [
        {
            "fragment": h.fragment,
            "termen": h.termen.termen,
            "definitie": h.termen.definitie,
            "regula": h.regula,
            "scor": h.scor,
            "explicatie": h.explicatie,
            "act_id": term_sources[id(h.termen)][0],
            "locator": term_sources[id(h.termen)][1],
            "sursa_sha256": term_sources[id(h.termen)][2],
        }
        for h in jargon(text, [t for t, *_ in terms[:term_limit]])
    ]
    term_status = "partial" if incomplete or len(terms) > term_limit else "verificat"
    if not terms:
        term_status = "indisponibil" if incomplete else "nesuportat"
    checks.append(
        _check(
            "terminologie",
            "Terminologie in actele citate",
            hits,
            status=term_status,
            note="Euristic, numai definitii recunoscute in actele citate; "
            "nu stabileste identitatea domeniilor sau exceptiilor.",
        )
    )
    checks.extend(
        _check(key, label, [], status="nesuportat", note=note)
        for key, label, note in [
            (
                "compatibilitate",
                "Compatibilitate juridica generala",
                "Nu se stabileste compatibilitatea cu toate legile sau dreptul UE.",
            ),
            (
                "vid",
                "Obligatii neimplementate",
                "Nu se calculeaza un raport complet de implementare din corpus "
                "pentru aceasta revizie.",
            ),
            (
                "ccr",
                "Constitutionalitate",
                "Registrul si textele CCR nu sunt capturate de aceasta analiza.",
            ),
            (
                "proiecte",
                "Suprapuneri parlamentare",
                "Versiunile proiectelor parlamentare nu sunt capturate de aceasta analiza.",
            ),
        ]
    )
    return {
        "schema_version": 1,
        "engine_version": ENGINE,
        "creat_la": datetime.now(UTC).isoformat(),
        "baza": {
            "propunere_id": proposal["id"],
            "revizie": proposal["revizie"],
            "rulare_id": proposal["rulare_id"],
            "constatare_id": proposal["constatare_id"],
            "raport_sha256": proposal["raport_sha256"],
            "propunere_sha256": _sha(proposal),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
        "text_analizat": text,
        "controale": checks,
        "surse": sources,
        "surse_sha256": _sha(sources),
        "acoperire": {
            "acte_recunoscute": len(acts),
            "acte_selectate": len(ids),
            "limita_acte": MAX_ACTS,
            "limita_randuri_per_act": MAX_ROWS,
            "limita_octeti_surse": MAX_SOURCE_BYTES,
            "limita_termeni": MAX_TERMS,
            "limita_termeni_aplicata": term_limit,
            "termeni_comparati": min(len(terms), term_limit),
            "limita_perechi_termen_caracter": MAX_TERM_CHAR_PAIRS,
        },
        "limitari": [
            "Analiza determinista a reviziei salvate, fara AI sau descarcari.",
            "Surse locale capturate la verificare, separat de dovada istorica si tinta propunerii.",
            "Niciun semnal nu inseamna validitate juridica. Acoperirea este limitata.",
            (
                "Modificarile nesalvate nu sunt analizate. "
                "Rezultatul nu certifica actualitatea ulterioara."
            ),
        ],
    }


def _supported(con):
    return con.execute("PRAGMA user_version").fetchone()[0] >= 7


def _result(row):
    return {"id": row["id"], **json.loads(row["rezultat_json"])}


def _retry(con, ident, proposal_id):
    if not _supported(con):
        return None
    row = con.execute("SELECT * FROM analize_propuneri WHERE id=?", (ident,)).fetchone()
    if row and row["propunere_id"] != proposal_id:
        raise ValueError("Identificator reutilizat pentru alta revizie.")
    return _result(row) if row else None


def salveaza(stare, request):
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "rulare_id",
        "constatare_id",
        "revizie",
    }:
        raise ValueError("Cerere de analiza invalida.")
    ident = dosare._id(request["id"])
    propuneri._number(request["revizie"], 1)
    path = dosare.cale(stare)
    proposal = propuneri.citeste(
        path,
        request["dosar_id"],
        request["rulare_id"],
        request["constatare_id"],
        request["revizie"],
    )["propunere"]
    with dosare._open(path) as con:
        old = _retry(con, ident, proposal["id"])
        if old:
            return old
    result = executa(stare, proposal)
    payload = dosare._json(result)
    if len(payload.encode()) > dosare.MAX_REPORT_BYTES:
        raise ValueError("Analiza depaseste limita de 4 MB.")
    with dosare._open(path, write=True) as con:
        old = _retry(con, ident, proposal["id"])
        if old:
            return old
        con.execute(
            "INSERT INTO analize_propuneri(id,propunere_id,creat_la,rezultat_json) "
            "VALUES (?,?,?,?)",
            (ident, proposal["id"], result["creat_la"], payload),
        )
    return {"id": ident, **result}


def istoric(path, dossier_id, run_id, finding_id, revision, offset=0, analysis_id=None):
    return propuneri.analize(path, dossier_id, run_id, finding_id, revision, offset, analysis_id)


def citeste_cerere(path, qs):
    return istoric(
        path,
        qs.get("id", [None])[0],
        qs.get("rulare_id", [None])[0],
        qs.get("constatare_id", [None])[0],
        int(qs.get("revizie", ["0"])[0]),
        int(qs.get("offset", ["0"])[0]),
        qs.get("analiza_id", [None])[0],
    )
