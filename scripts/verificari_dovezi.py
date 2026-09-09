"""Append-only local evidence checks and a paginated queue across research dossiers."""

import json
from pathlib import Path

from scripts import dosare


def migreaza(con):
    con.execute(
        "CREATE TABLE verificari_dovezi (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "id TEXT NOT NULL UNIQUE, rulare_id TEXT NOT NULL REFERENCES rulari(id), "
        "verificat_la TEXT NOT NULL, schimbate INTEGER NOT NULL, incomplete INTEGER NOT NULL, "
        "constatari INTEGER NOT NULL, rezultat_json TEXT NOT NULL)"
    )
    con.execute("CREATE INDEX verificari_rulare ON verificari_dovezi(rulare_id,seq DESC)")
    con.execute(
        "CREATE TABLE recalculari (sursa_id TEXT NOT NULL REFERENCES rulari(id), "
        "rulare_id TEXT NOT NULL REFERENCES rulari(id), creat_la TEXT NOT NULL, "
        "PRIMARY KEY(sursa_id,rulare_id), CHECK(sursa_id<>rulare_id))"
    )
    con.execute("CREATE INDEX recalculari_rulare ON recalculari(rulare_id)")
    for table in ("verificari_dovezi", "recalculari"):
        for operation in ("UPDATE", "DELETE"):
            con.execute(
                f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'Evidence history is append-only'); END"
            )


def _supported(con):
    return con.execute("PRAGMA user_version").fetchone()[0] >= 3


def _offset(offset):
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    return offset


def _result(row):
    return {"id": row["id"], **json.loads(row["rezultat_json"])}


def _retry(con, ident, run_id):
    if not _supported(con):
        return None
    row = con.execute("SELECT * FROM verificari_dovezi WHERE id=?", (ident,)).fetchone()
    if row is not None and row["rulare_id"] != run_id:
        raise ValueError("Identificator de verificare reutilizat pentru alta rulare.")
    return _result(row) if row else None


def salveaza(stare, request):
    from scripts.dependente_dovezi import verifica

    if not isinstance(request, dict) or set(request) != {"id", "dosar_id", "rulare_id"}:
        raise ValueError("Cerere invalida.")
    ident, run_id = dosare._id(request["id"]), dosare._id(request["rulare_id"])
    path = dosare.cale(stare)
    dosare.rulari(path, request["dosar_id"], run_id)
    with dosare._open(path) as con:
        old = _retry(con, ident, run_id)
        if old is not None:
            return old
    result = verifica(stare, request["dosar_id"], run_id)
    result["limitari"].append(
        "Verificare salvata explicit; nu certifica actualitatea ulterioara a corpusului."
    )
    payload = dosare._json(result)
    if len(payload.encode("utf-8")) > dosare.MAX_REPORT_BYTES:
        raise ValueError("Verificarea depaseste limita de 4 MB.")
    with dosare._open(path, write=True) as con:
        old = _retry(con, ident, run_id)
        if old is not None:
            return old
        con.execute(
            "INSERT INTO verificari_dovezi "
            "(id,rulare_id,verificat_la,schimbate,incomplete,constatari,rezultat_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                ident,
                run_id,
                result["verificat_la"],
                result["totaluri"]["schimbat"],
                sum(f["comparatie_incompleta"] for f in result["constatari"]),
                len(result["constatari"]),
                payload,
            ),
        )
    return {"id": ident, **result}


def istoric(path, dossier_id, run_id, offset=0, check_id=None):
    _offset(offset)
    dosare.rulari(path, dossier_id, dosare._id(run_id))
    if check_id is not None:
        dosare._id(check_id)
    out = {
        "verificari": [],
        "total": 0,
        "offset": offset,
        "limita": 20,
        "selectata": None,
        "origini": [],
        "origini_trunchiate": False,
    }
    with dosare._open(path) as con:
        if _supported(con):
            out["verificari"] = [
                dict(r)
                for r in con.execute(
                    "SELECT id,verificat_la,schimbate,incomplete,constatari FROM verificari_dovezi "
                    "WHERE rulare_id=? ORDER BY seq DESC LIMIT 20 OFFSET ?",
                    (run_id, offset),
                )
            ]
            out["total"] = con.execute(
                "SELECT count(*) FROM verificari_dovezi WHERE rulare_id=?", (run_id,)
            ).fetchone()[0]
            row = con.execute(
                "SELECT * FROM verificari_dovezi WHERE rulare_id=? "
                + ("AND id=? " if check_id else "")
                + "ORDER BY seq DESC LIMIT 1",
                (run_id, check_id) if check_id else (run_id,),
            ).fetchone()
            out["selectata"] = _result(row) if row else None
            origins = [
                dict(r)
                for r in con.execute(
                    "SELECT sursa_id,creat_la FROM recalculari WHERE rulare_id=? "
                    "ORDER BY creat_la DESC,sursa_id LIMIT 101",
                    (run_id,),
                )
            ]
            out["origini"], out["origini_trunchiate"] = origins[:100], len(origins) > 100
        if check_id and out["selectata"] is None:
            raise ValueError("Verificare inexistenta in aceasta rulare.")
    return out


def coada(path, offset=0, status="toate"):
    _offset(offset)
    filters = {
        "toate": "1",
        "schimbat": "c.schimbate>0",
        "indisponibil": "(c.incomplete>0 OR c.constatari=0)",
        "neverificat": "c.id IS NULL",
        "neschimbat": "c.schimbate=0 AND c.incomplete=0 AND c.constatari>0",
    }
    if status not in filters:
        raise ValueError("Filtru invalid.")
    out = {"rulari": [], "total": 0, "offset": offset, "limita": 50}
    if not Path(path).exists():
        return out
    with dosare._open(path) as con:
        checks = (
            "LEFT JOIN verificari_dovezi c ON c.seq=(SELECT seq FROM verificari_dovezi "
            "WHERE rulare_id=r.id ORDER BY seq DESC LIMIT 1) "
            if _supported(con)
            else "LEFT JOIN (SELECT NULL id,NULL verificat_la,NULL schimbate,NULL incomplete,"
            "NULL constatari) c ON 0 "
        )
        query = (
            "FROM rulari r JOIN dosare d ON d.id=r.dosar_id " + checks + "WHERE " + filters[status]
        )
        out["total"] = con.execute("SELECT count(*) " + query).fetchone()[0]
        out["rulari"] = [
            dict(r)
            for r in con.execute(
                "SELECT r.id rulare_id,r.dosar_id,d.titlu,r.creat_la,c.id verificare_id,"
                "c.verificat_la,c.schimbate,c.incomplete,c.constatari "
                + query
                + " ORDER BY COALESCE(c.verificat_la,r.creat_la) DESC,r.id LIMIT 50 OFFSET ?",
                (offset,),
            )
        ]
    return out
