"""Human review of immutable saved findings; never an authoritative legal verdict."""

import hashlib
import json
import re
from datetime import UTC, date, datetime

from scripts import dosare

STARI = {
    "unreviewed": "Neanalizat",
    "needs_evidence": "Necesită dovezi",
    "confirmed_by_reviewer": "Confirmat de evaluator",
    "dismissed": "Respins de evaluator",
}

CONTEXT_FIELDS = (
    "aplicabil_de_la",
    "aplicabil_pana_la",
    "teritoriu",
    "destinatari",
    "exceptii",
    "tranzitorii",
    "clasificare",
)


def _context_targets(finding):
    if finding["tip"] in ("contradictie", "proiect"):
        targets = tuple(side for side in ("a", "b") if finding["dovada"].get(side))
        return targets or ("constatare",)
    return ("constatare",)


def _context_events(con, run_id, finding_id, target, offset=0):
    if con.execute("PRAGMA user_version").fetchone()[0] < 4:
        return []
    events = []
    for row in con.execute(
        "SELECT * FROM contexte_juridice WHERE rulare_id=? AND constatare_id=? AND tinta=? "
        "ORDER BY revizie DESC LIMIT 21 OFFSET ?",
        (run_id, finding_id, target, offset),
    ):
        event = dict(row)
        event["context"] = json.loads(event.pop("context_json"))
        events.append(event)
    return events


def _context_value(value):
    if not isinstance(value, dict) or set(value) != set(CONTEXT_FIELDS):
        raise ValueError("Campuri de context invalide.")
    out = {}
    for key, entry in value.items():
        if not isinstance(entry, dict) or set(entry) != {"valoare", "citare"}:
            raise ValueError("Fiecare camp necesita valoare si citare.")
        text = dosare._text(entry["valoare"], 500)
        citation = dosare._text(entry["citare"], 300)
        if bool(text) != bool(citation):
            raise ValueError(
                "Valorile declarate necesita citare; campurile necunoscute raman goale."
            )
        if key.startswith("aplicabil_") and text:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                raise ValueError("Data trebuie sa fie YYYY-MM-DD.")
            date.fromisoformat(text)
        if key == "clasificare" and text not in ("", "organica", "ordinara", "alta"):
            raise ValueError("Clasificare invalida.")
        out[key] = {"valoare": text, "citare": citation}
    start, end = (out[k]["valoare"] for k in ("aplicabil_de_la", "aplicabil_pana_la"))
    if start and end and start > end:
        raise ValueError("Intervalul de aplicabilitate este inversat.")
    return out


def _context_finding(path, dossier_id, run_id, finding_id, target):
    run = dosare.rulari(path, dossier_id, dosare._id(run_id))
    dosare._id(finding_id)
    finding = next((f for f in constatari(run) if f["id"] == finding_id), None)
    if finding is None or target not in _context_targets(finding):
        raise ValueError("Constatare sau tinta inexistenta in aceasta rulare.")


def context_salveaza(path, request):
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "rulare_id",
        "constatare_id",
        "tinta",
        "revizie",
        "evaluator",
        "motiv",
        "context",
    }:
        raise ValueError("Cerere de context invalida.")
    ident = dosare._id(request["id"])
    run_id, finding_id, target = request["rulare_id"], request["constatare_id"], request["tinta"]
    _context_finding(path, request["dosar_id"], run_id, finding_id, target)
    revision = request["revizie"]
    if type(revision) is not int or not 0 <= revision <= 1_000_000:
        raise ValueError("Revizie invalida.")
    reviewer = dosare._text(request["evaluator"], 120)
    reason = dosare._text(request["motiv"], 2000)
    if not reviewer or not reason:
        raise ValueError("Evaluatorul si motivarea sunt obligatorii.")
    value = _context_value(request["context"])
    fields = (run_id, finding_id, target, revision + 1, reviewer, reason, dosare._json(value))
    if len(dosare._json(request).encode()) > 16000:
        raise ValueError("Contextul depaseste limita de 16 KB.")
    with dosare._open(path, write=True) as con:
        old = con.execute("SELECT * FROM contexte_juridice WHERE id=?", (ident,)).fetchone()
        if old is not None:
            if (
                tuple(
                    old[k]
                    for k in (
                        "rulare_id",
                        "constatare_id",
                        "tinta",
                        "revizie",
                        "evaluator",
                        "motiv",
                        "context_json",
                    )
                )
                != fields
            ):
                raise ValueError("Identificator reutilizat cu alt context.")
        else:
            events = _context_events(con, run_id, finding_id, target)
            if (events[0]["revizie"] if events else 0) != revision:
                raise ValueError("Contextul s-a schimbat. Reincarca inainte de a salva.")
            con.execute(
                "INSERT INTO contexte_juridice VALUES (?,?,?,?,?,?,?,?,?)",
                (ident, *fields, datetime.now(UTC).isoformat()),
            )
        return {"id": ident, "revizie": revision + 1}


def context_istoric(path, dossier_id, run_id, finding_id, target, offset=0):
    _context_finding(path, dossier_id, run_id, finding_id, target)
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    with dosare._open(path) as con:
        events = _context_events(con, run_id, finding_id, target, offset)
        return {"evenimente": events[:20], "mai_multe": len(events) > 20, "offset": offset}


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
            finding["context_juridic"] = {}
            for target in _context_targets(finding):
                contexts = _context_events(con, run_id, finding["id"], target)
                finding["context_juridic"][target] = {
                    "curent": contexts[0] if contexts else None,
                    "istoric": contexts[:20],
                    "istoric_trunchiat": len(contexts) > 20,
                }
    limitations = [
        "Deciziile sunt evaluări umane, nu hotărâri sau verdicte juridice oficiale.",
        "Evaluatorul este o etichetă declarată, nu o identitate autentificată.",
        "Sunt revizuibile numai exemplele și candidații păstrați în această rulare.",
        "Deciziile nu se transferă automat la altă rulare sau altă versiune a dovezilor.",
        "Contextul juridic este declarat de evaluator, cu citari neverificate automat. "
        + "Nu modifica detectorii, deciziile sau verificarile dovezilor.",
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
        lines += [
            "Context juridic declarat (maximum 20 de revizii per tinta):",
            dosare._json(f["context_juridic"]),
        ]
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
    if run["dovezi"].get("referinte_ue"):
        lines += [
            "# Surse UE contextuale salvate",
            dosare._json(run["dovezi"]["surse_ue"])
            if "surse_ue" in run["dovezi"]
            else "Instantanee UE necapturate pentru aceasta rulare.",
        ]
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
