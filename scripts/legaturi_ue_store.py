"""Append-only EU links. Schema-9 migration hook awaits the integrated schema-8 base."""

import json
from datetime import UTC, datetime

from scripts import dosare, legaturi_ue, propuneri, revizuiri

SCHEMA_VERSION = 9


def migreaza(con):
    """Called by the owning dossier migration transaction; never commits or stamps version."""
    con.execute(
        "CREATE TABLE legaturi_ue (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "id TEXT NOT NULL UNIQUE, propunere_id TEXT NOT NULL REFERENCES propuneri(id), "
        "creat_la TEXT NOT NULL, cerere_json TEXT NOT NULL, rezultat_json TEXT NOT NULL)"
    )
    con.execute("CREATE INDEX legaturi_ue_propunere ON legaturi_ue(propunere_id,seq DESC)")
    for operation in ("UPDATE", "DELETE"):
        con.execute(
            f"CREATE TRIGGER legaturi_ue_no_{operation.lower()} BEFORE {operation} ON legaturi_ue "
            "BEGIN SELECT RAISE(ABORT,'EU links are append-only'); END"
        )


def _supported(con):
    return con.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION


def _request(request):
    extra = {"id", "baza_sha256", "autor", "ipoteza", "obligatie", "motiv"}
    if not isinstance(request, dict) or set(request) != legaturi_ue.SELECTORS | extra:
        raise ValueError("Cerere de salvare a legaturii invalida.")
    selected = legaturi_ue.selection({k: request[k] for k in legaturi_ue.SELECTORS})
    if request["ipoteza"] not in legaturi_ue.HYPOTHESES:
        raise ValueError("Ipoteza nesuportata.")
    return {
        **selected,
        "id": dosare._id(request["id"]),
        "baza_sha256": legaturi_ue.digest(request["baza_sha256"]),
        "autor": dosare._text(request["autor"], 120, True),
        "ipoteza": request["ipoteza"],
        "obligatie": dosare._text(request["obligatie"], 2000, True),
        "motiv": dosare._text(request["motiv"], 4000, True),
    }


def _result(row):
    result = json.loads(row["rezultat_json"])
    if legaturi_ue.sha(result["baza"]) != result["baza_sha256"]:
        raise ValueError("Integritatea bazei legaturii este invalida.")
    return {"id": row["id"], "creat_la": row["creat_la"], **result}


def _retry(con, request, proposal):
    if not _supported(con):
        return None
    row = con.execute("SELECT * FROM legaturi_ue WHERE id=?", (request["id"],)).fetchone()
    if row is None:
        return None
    if row["propunere_id"] != proposal["id"] or row["cerere_json"] != dosare._json(request):
        raise ValueError("Identificator reutilizat cu alta legatura sau alta revizie.")
    result = _result(row)
    if result["baza"]["proposal_sha256"] != legaturi_ue.sha(proposal):
        raise ValueError("Baza legaturii nu corespunde propunerii salvate.")
    return result


def salveaza(stare, request):
    normalized = _request(request)
    selected = {k: normalized[k] for k in legaturi_ue.SELECTORS}
    path = dosare.cale(stare)
    proposal = propuneri.citeste(
        path,
        selected["dosar_id"],
        selected["rulare_id"],
        selected["constatare_id"],
        selected["revizie"],
    )["propunere"]
    with dosare._open(path) as con:
        old = _retry(con, normalized, proposal)
        if old:
            return old
    result = legaturi_ue.preview(stare, selected)
    if result["blockers"]:
        raise ValueError(
            "Legatura substantiva blocata: " + ", ".join(b["code"] for b in result["blockers"])
        )
    if result["baza_sha256"] != normalized["baza_sha256"]:
        raise ValueError("Baza s-a schimbat. Refa previzualizarea si confirma explicit.")
    result.update(
        scope="substantive_candidate",
        state="linked_hypothesis",
        substantive_candidate={
            k: normalized[k] for k in ("autor", "ipoteza", "obligatie", "motiv")
        },
    )
    payload = dosare._json(result)
    if len(payload.encode()) > dosare.MAX_REPORT_BYTES:
        raise ValueError("Legatura depaseste limita de 4 MB.")
    now = datetime.now(UTC).isoformat()
    with dosare._open(path, write=True) as con:
        if not _supported(con):
            raise ValueError("Salvarea legaturilor UE necesita schema 9 integrata.")
        old = _retry(con, normalized, proposal)
        if old:
            return old
        current_context = {}
        for target in result["baza"]["context"]:
            events = revizuiri._context_events(
                con, selected["rulare_id"], selected["constatare_id"], target
            )
            current_context[target] = events[0] if events else None
        if current_context != result["baza"]["context"]:
            raise ValueError("Contextul s-a schimbat. Refa previzualizarea.")
        con.execute(
            "INSERT INTO legaturi_ue(id,propunere_id,creat_la,cerere_json,rezultat_json) "
            "VALUES (?,?,?,?,?)",
            (normalized["id"], proposal["id"], now, dosare._json(normalized), payload),
        )
    return {"id": normalized["id"], "creat_la": now, **result}


def istoric(path, dossier_id, run_id, finding_id, revision, offset=0, link_id=None):
    propuneri._number(offset)
    proposal = propuneri.citeste(path, dossier_id, run_id, finding_id, revision)["propunere"]
    if link_id is not None:
        dosare._id(link_id)
    out = {
        "legaturi": [],
        "total": 0,
        "offset": offset,
        "limita": 20,
        "selectata": None,
        "revizie": revision,
        "limitari": legaturi_ue.LIMITATIONS,
    }
    with dosare._open(path) as con:
        if _supported(con):
            out["legaturi"] = [
                dict(r)
                for r in con.execute(
                    "SELECT id,creat_la,json_extract(rezultat_json,'$.substantive_candidate.ipoteza') "
                    "AS ipoteza FROM legaturi_ue WHERE propunere_id=? ORDER BY seq DESC LIMIT 20 OFFSET ?",
                    (proposal["id"], offset),
                )
            ]
            out["total"] = con.execute(
                "SELECT count(*) FROM legaturi_ue WHERE propunere_id=?", (proposal["id"],)
            ).fetchone()[0]
            row = con.execute(
                "SELECT * FROM legaturi_ue WHERE propunere_id=? "
                + ("AND id=? " if link_id else "")
                + "ORDER BY seq DESC LIMIT 1",
                (proposal["id"], link_id) if link_id else (proposal["id"],),
            ).fetchone()
            if row:
                out["selectata"] = _result(row)
                if out["selectata"]["baza"]["proposal_sha256"] != legaturi_ue.sha(proposal):
                    raise ValueError("Baza legaturii nu corespunde reviziei.")
    if link_id and out["selectata"] is None:
        raise ValueError("Legatura inexistenta pentru aceasta revizie.")
    if out["selectata"]:
        out["markdown"] = "# Legatura UE: ipoteza declarata\n\n" + propuneri._json_block(
            out["selectata"]
        )
    else:
        out["markdown"] = "# Nicio legatura UE salvata pentru aceasta revizie\n"
    return out


def citeste_cerere(path, qs):
    return istoric(
        path,
        qs.get("id", [None])[0],
        qs.get("rulare_id", [None])[0],
        qs.get("constatare_id", [None])[0],
        int(qs.get("revizie", ["0"])[0]),
        int(qs.get("offset", ["0"])[0]),
        qs.get("legatura_id", [None])[0],
    )
