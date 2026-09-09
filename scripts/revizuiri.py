"""Human review of immutable saved findings; never an authoritative legal verdict."""

import hashlib
from datetime import UTC, datetime

from scripts import dosare

STARI = {
    "unreviewed": "Neanalizat",
    "needs_evidence": "Necesită dovezi",
    "confirmed_by_reviewer": "Confirmat de evaluator",
    "dismissed": "Respins de evaluator",
}


def constatari(run):
    report = run["raport"]
    examples = (report.get("rand") or {}).get("exemple") or {}
    groups = {
        "lacuna": examples.get("viduri", []),
        "ccr": examples.get("neconstitutionale", []),
        "contradictie": (report.get("contradictii") or {}).get("candidati", []),
        "proiect": (report.get("conflicte_proiecte") or {}).get("candidati", []),
    }
    found = {}
    for kind, entries in groups.items():
        for evidence in entries:
            payload = {"tip": kind, "dovada": evidence}
            ident = hashlib.sha256(dosare._json(payload).encode()).hexdigest()[:32]
            found.setdefault(ident, {"id": ident, **payload})
    return list(found.values())


def _events(con, run_id, ident):
    if con.execute("PRAGMA user_version").fetchone()[0] == 1:
        return []
    return [
        dict(r)
        for r in con.execute(
            "SELECT * FROM revizuiri WHERE rulare_id=? AND constatare_id=? "
            "ORDER BY revizie DESC LIMIT 21",
            (run_id, ident),
        )
    ]


def lista(path, dossier_id, run_id):
    dosare._id(run_id)
    run = dosare.rulari(path, dossier_id, run_id)
    findings = constatari(run)
    manifest = run["dovezi"].get("manifest")
    with dosare._open(path) as con:
        for finding in findings:
            events = _events(con, run_id, finding["id"])
            latest = events[0] if events else None
            finding.update(
                {
                    "stare": latest["stare"] if latest else "unreviewed",
                    "revizie": latest["revizie"] if latest else 0,
                    "istoric": events[:20],
                    "istoric_trunchiat": len(events) > 20,
                }
            )
    limitations = [
        "Deciziile sunt evaluări umane, nu hotărâri sau verdicte juridice oficiale.",
        "Evaluatorul este o etichetă declarată, nu o identitate autentificată.",
        "Sunt revizuibile numai exemplele și candidații păstrați în această rulare.",
        "Deciziile nu se transferă automat la altă rulare sau altă versiune a dovezilor.",
    ]
    lines = [
        f"# Revizuire: {dossier_id}",
        f"Rulare: {run_id}",
        f"Salvată: {run['creat_la']} | SHA-256 raport: {run['sha256']}",
    ]
    for f in findings:
        lines += [
            f"## {f['tip']} / {f['id']}",
            f"Stare: {STARI[f['stare']]}",
            "Dovadă salvată:",
            dosare._json(f["dovada"]),
        ]
        for e in reversed(f["istoric"]):
            lines.append(
                f"Revizia {e['revizie']} | {e['creat_la']} | {e['evaluator']} | "
                f"{STARI[e['stare']]}\n\n{e['motiv']}"
            )
        if f["istoric_trunchiat"]:
            lines.append(
                "Istoric parțial: ultimele 20 de evenimente; baza păstrează toate reviziile."
            )
    lines += [
        "# Dependente ale dovezilor",
        dosare._json(manifest)
        if manifest is not None
        else "Manifest necapturat pentru aceasta rulare.",
    ]
    lines += limitations + ["# Raportul salvat", run["raport"].get("markdown", "")]
    return {
        "schema_version": 1,
        "rulare_id": run_id,
        "constatari": findings,
        "limitari": limitations,
        "rulare": run,
        "markdown": "\n\n".join(lines),
    }


def salveaza(path, request):
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "rulare_id",
        "constatare_id",
        "revizie",
        "stare",
        "evaluator",
        "motiv",
    }:
        raise ValueError("Cerere de revizuire invalidă.")
    ident = dosare._id(request["id"])
    dossier_id = dosare._id(request["dosar_id"])
    run_id = dosare._id(request["rulare_id"])
    finding_id = dosare._id(request["constatare_id"])
    revision = request["revizie"]
    if type(revision) is not int or revision < 0 or revision > 1_000_000:
        raise ValueError("Revizie invalidă.")
    status = request["stare"]
    if not isinstance(status, str) or status not in STARI:
        raise ValueError("Stare de revizuire invalidă.")
    reviewer = dosare._text(request["evaluator"], 120)
    reason = dosare._text(request["motiv"], 2000)
    if not reviewer or not reason:
        raise ValueError("Evaluatorul și motivarea sunt obligatorii.")
    run = dosare.rulari(path, dossier_id, run_id)
    if finding_id not in {f["id"] for f in constatari(run)}:
        raise ValueError("Constatarea nu aparține acestei rulări.")
    with dosare._open(path, write=True) as con:
        existing = con.execute("SELECT * FROM revizuiri WHERE id=?", (ident,)).fetchone()
        fields = (run_id, finding_id, revision + 1, status, reviewer, reason)
        if existing:
            if (
                tuple(
                    existing[k]
                    for k in (
                        "rulare_id",
                        "constatare_id",
                        "revizie",
                        "stare",
                        "evaluator",
                        "motiv",
                    )
                )
                != fields
            ):
                raise ValueError("Identificator de revizuire reutilizat cu alt conținut.")
            return dict(existing)
        events = _events(con, run_id, finding_id)
        if (events[0]["revizie"] if events else 0) != revision:
            raise ValueError("Revizuirea s-a schimbat. Reîncarcă înainte de a salva.")
        con.execute(
            "INSERT INTO revizuiri VALUES (?,?,?,?,?,?,?,?)",
            (ident, *fields, datetime.now(UTC).isoformat()),
        )
        return dict(con.execute("SELECT * FROM revizuiri WHERE id=?", (ident,)).fetchone())


def istoric(path, dossier_id, run_id, finding_id, offset=0):
    dosare._id(run_id)
    dosare._id(finding_id)
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    run = dosare.rulari(path, dossier_id, run_id)
    if finding_id not in {f["id"] for f in constatari(run)}:
        raise ValueError("Constatarea nu aparține acestei rulări.")
    with dosare._open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] == 1:
            return {"evenimente": [], "total": 0, "offset": offset}
        rows = con.execute(
            "SELECT * FROM revizuiri WHERE rulare_id=? AND constatare_id=? "
            "ORDER BY revizie DESC LIMIT 20 OFFSET ?",
            (run_id, finding_id, offset),
        ).fetchall()
        total = con.execute(
            "SELECT count(*) FROM revizuiri WHERE rulare_id=? AND constatare_id=?",
            (run_id, finding_id),
        ).fetchone()[0]
        return {"evenimente": [dict(r) for r in rows], "total": total, "offset": offset}
