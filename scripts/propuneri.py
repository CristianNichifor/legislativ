"""Editable proposal revisions linked to one immutable saved finding, without review gates."""

import json
import re
from datetime import UTC, datetime

from scripts import dosare, revizuiri

MAX_REQUEST_BYTES = 80_000


def _finding(path, dossier_id, run_id, finding_id):
    dossier_id, run_id, finding_id = map(dosare._id, (dossier_id, run_id, finding_id))
    run = dosare.rulari(path, dossier_id, run_id)
    finding = next((f for f in revizuiri.constatari(run) if f["id"] == finding_id), None)
    if finding is None:
        raise ValueError("Constatarea nu apartine acestei rulari.")
    return run, finding


def _current(con, run_id, finding_id):
    if con.execute("PRAGMA user_version").fetchone()[0] < 5:
        return None
    row = con.execute(
        "SELECT * FROM propuneri WHERE rulare_id=? AND constatare_id=? "
        "ORDER BY revizie DESC LIMIT 1",
        (run_id, finding_id),
    ).fetchone()
    return dict(row) if row else None


def _number(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 1_000_001:
        raise ValueError("Revizie sau offset invalid.")
    return value


def citeste(path, dossier_id, run_id, finding_id, revision=None):
    if revision is not None:
        _number(revision, 1)
    run, finding = _finding(path, dossier_id, run_id, finding_id)
    with dosare._open(path) as con:
        current = _current(con, run_id, finding_id)
        if revision is not None:
            row = (
                con.execute(
                    "SELECT * FROM propuneri WHERE rulare_id=? AND constatare_id=? AND revizie=?",
                    (run_id, finding_id, revision),
                ).fetchone()
                if current
                else None
            )
            if row is None:
                raise ValueError("Revizia propunerii nu exista.")
            current = dict(row)
    if current and current["raport_sha256"] != run["sha256"]:
        raise ValueError("Baza propunerii nu corespunde raportului salvat.")
    return {
        "propunere": current,
        "constatare": finding,
        "baza": {
            "dosar_id": dossier_id,
            "rulare_id": run_id,
            "constatare_id": finding_id,
            "raport_sha256": run["sha256"],
            "creat_la": run["creat_la"],
        },
    }


def lista(path, dossier_id, offset=0):
    _number(offset)
    dosare.citeste(path, dossier_id)
    with dosare._open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] < 5:
            return {"propuneri": [], "total": 0, "offset": offset, "limita": 50}
        where = (
            " FROM propuneri p JOIN rulari r ON r.id=p.rulare_id WHERE r.dosar_id=? "
            "AND NOT EXISTS (SELECT 1 FROM propuneri newer WHERE newer.rulare_id=p.rulare_id "
            "AND newer.constatare_id=p.constatare_id AND newer.revizie>p.revizie)"
        )
        rows = con.execute(
            "SELECT p.id,p.rulare_id,p.constatare_id,p.titlu,p.revizie,p.creat_la,"
            "r.creat_la AS rulare_creata_la"
            + where
            + " ORDER BY p.creat_la DESC,p.id LIMIT 50 OFFSET ?",
            (dossier_id, offset),
        ).fetchall()
        return {
            "propuneri": [dict(row) for row in rows],
            "total": con.execute("SELECT count(*)" + where, (dossier_id,)).fetchone()[0],
            "offset": offset,
            "limita": 50,
        }


def istoric(path, dossier_id, run_id, finding_id, offset=0):
    _number(offset)
    _finding(path, dossier_id, run_id, finding_id)
    with dosare._open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] < 5:
            return {"revizii": [], "total": 0, "offset": offset, "limita": 20}
        params = (run_id, finding_id)
        where = " FROM propuneri WHERE rulare_id=? AND constatare_id=?"
        rows = con.execute(
            "SELECT id,revizie,titlu,creat_la" + where + " ORDER BY revizie DESC LIMIT 20 OFFSET ?",
            (*params, offset),
        ).fetchall()
        return {
            "revizii": [dict(row) for row in rows],
            "total": con.execute("SELECT count(*)" + where, params).fetchone()[0],
            "offset": offset,
            "limita": 20,
        }


def _block(value, language=""):
    # Saved/user text cannot close its own Markdown fence or inject active markup.
    fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", value)), default=0))
    return f"{fence}{language}\n{value}\n{fence}"


def _json_block(value):
    return _block(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), "json")


def exporta(path, dossier_id, run_id, finding_id, revision):
    _number(revision, 1)
    data = citeste(path, dossier_id, run_id, finding_id, revision)
    run = dosare.rulari(path, dossier_id, run_id)
    proposal = data["propunere"]
    limitations = [
        "Text propus de autor, nu legislatie in vigoare si nu concluzie juridica verificata.",
        "Exportul contine numai revizia salvata selectata, nu modificarile nesalvate.",
        "Dovezile sunt cele pastrate in rularea originala, nu surse actualizate la export.",
        "Referintele UE ale rularii sunt contextuale, nu constatari de incompatibilitate.",
        "Absenta unei dovezi nu dovedeste absenta unei norme sau a unei exceptii.",
    ]
    sections = [
        "# Propunere de modificare",
        *limitations,
        "## Titlu propus",
        _block(proposal["titlu"]),
        "## Text propus (nu text legal in vigoare)",
        _block(proposal["text"]),
        "## Motivarea autorului",
        _block(proposal["motiv"]),
        "## Revizie salvata",
        _json_block({k: proposal[k] for k in ("id", "revizie", "creat_la")}),
        "## Baza exacta",
        _json_block(data["baza"]),
        "## Constatarea si dovezile originale",
        _json_block(data["constatare"]),
        "## Surse si referinte pastrate in rulare (context complet)",
        _json_block(run["dovezi"]),
    ]
    return {
        "schema_version": 1,
        **data,
        "rulare": run,
        "limitari": limitations,
        "markdown": "\n\n".join(sections) + "\n",
    }


def citeste_cerere(path, qs):
    mode = qs.get("mod", [""])[0]
    dossier_id = qs.get("id", [None])[0]
    if mode == "lista":
        return lista(path, dossier_id, int(qs.get("offset", ["0"])[0]))
    params = (path, dossier_id, qs.get("rulare_id", [None])[0], qs.get("constatare_id", [None])[0])
    if mode == "istoric":
        return istoric(*params, int(qs.get("offset", ["0"])[0]))
    if mode == "export":
        return exporta(*params, int(qs.get("revizie", ["0"])[0]))
    if mode:
        raise ValueError("Operatie de propunere necunoscuta.")
    return citeste(*params, int(qs["revizie"][0]) if "revizie" in qs else None)


def salveaza(path, request):
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "rulare_id",
        "constatare_id",
        "revizie",
        "titlu",
        "text",
        "motiv",
    }:
        raise ValueError("Cerere de propunere invalida.")
    ident = dosare._id(request["id"])
    revision = request["revizie"]
    if type(revision) is not int or not 0 <= revision <= 1_000_000:
        raise ValueError("Revizie invalida.")
    title = dosare._text(request["titlu"], 200, True)
    text = dosare._text(request["text"], 12000)
    reason = dosare._text(request["motiv"], 4000)
    if len(dosare._json(request).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Propunerea depaseste limita de 80 KB.")
    run, finding = _finding(
        path, request["dosar_id"], request["rulare_id"], request["constatare_id"]
    )
    fields = (run["id"], finding["id"], revision + 1, run["sha256"], title, text, reason)
    with dosare._open(path, write=True) as con:
        old = con.execute("SELECT * FROM propuneri WHERE id=?", (ident,)).fetchone()
        if old:
            if (
                tuple(
                    old[k]
                    for k in (
                        "rulare_id",
                        "constatare_id",
                        "revizie",
                        "raport_sha256",
                        "titlu",
                        "text",
                        "motiv",
                    )
                )
                != fields
            ):
                raise ValueError("Identificator reutilizat cu alta propunere.")
            return dict(old)
        current = _current(con, run["id"], finding["id"])
        if (current["revizie"] if current else 0) != revision:
            raise ValueError(
                "Propunerea s-a schimbat. Notele locale au fost pastrate; "
                "reincarca pentru comparare."
            )
        con.execute(
            "INSERT INTO propuneri VALUES (?,?,?,?,?,?,?,?,?)",
            (ident, *fields, datetime.now(UTC).isoformat()),
        )
        return dict(con.execute("SELECT * FROM propuneri WHERE id=?", (ident,)).fetchone())
