"""Editable proposal revisions linked to one immutable saved finding, without review gates."""

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


def citeste(path, dossier_id, run_id, finding_id):
    run, finding = _finding(path, dossier_id, run_id, finding_id)
    with dosare._open(path) as con:
        current = _current(con, run_id, finding_id)
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
