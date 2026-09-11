"""Manual legislative gap notes stored in the private dossier database."""

from datetime import UTC, datetime
from pathlib import Path

from scripts import constatari_manuale, dosare

FIELDS = {
    "id",
    "dosar_id",
    "revizie",
    "title",
    "type",
    "act_id",
    "locator",
    "evidence_quote",
    "source_url",
    "source_hash",
    "reasoning",
    "status",
}


def _hash(value):
    value = dosare._text(value, 64)
    if value and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("Hash sursa invalid.")
    return value


def _url(value):
    value = dosare._text(value, 1000)
    if value and not value.startswith(("https://", "http://")):
        raise ValueError("URL sursa invalid.")
    return value


def _row(row):
    return {
        "id": row["id"],
        "dosar_id": row["dosar_id"],
        "title": row["titlu"],
        "type": row["tip"],
        "act_id": row["act_id"],
        "locator": row["locator"],
        "evidence_quote": row["citat_dovada"],
        "source_url": row["sursa_url"],
        "source_hash": row["sursa_sha256"],
        "reasoning": row["rationament"],
        "status": row["stare"],
        "revizie": row["revizie"],
        "creat_la": row["creat_la"],
        "modificat_la": row["modificat_la"],
    }


def _normalize(request):
    if not isinstance(request, dict) or set(request) != FIELDS:
        raise ValueError("Cerere invalidă.")
    if type(request["revizie"]) is not int or request["revizie"] < 0:
        raise ValueError("Revizie invalidă.")
    return {
        "id": dosare._id(request["id"]),
        "dosar_id": dosare._id(request["dosar_id"]),
        "title": dosare._text(request["title"], 200, True),
        "type": constatari_manuale.normalize_tip(request["type"]),
        "act_id": dosare._text(request["act_id"], 200),
        "locator": dosare._text(request["locator"], 120),
        "evidence_quote": dosare._text(request["evidence_quote"], 4000),
        "source_url": _url(request["source_url"]),
        "source_hash": _hash(request["source_hash"]),
        "reasoning": dosare._text(request["reasoning"], 8000),
        "status": constatari_manuale.normalize_stare(request["status"]),
        "revizie": request["revizie"],
    }


def _content(data):
    return tuple(
        data[key]
        for key in (
            "title",
            "type",
            "act_id",
            "locator",
            "evidence_quote",
            "source_url",
            "source_hash",
            "reasoning",
            "status",
        )
    )


def citeste(path, dossier_id, note_id):
    dossier_id = dosare._id(dossier_id)
    note_id = dosare._id(note_id)
    if not Path(path).exists():
        raise ValueError("Dosar inexistent.")
    with dosare._open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] < dosare.SCHEMA_VERSION:
            raise ValueError("Nota inexistentă în acest dosar.")
        row = con.execute(
            "SELECT * FROM note_manuale WHERE dosar_id=? AND id=?", (dossier_id, note_id)
        ).fetchone()
        if not row:
            raise ValueError("Nota inexistentă în acest dosar.")
        return _row(row)


def lista(path, dossier_id, offset=0, status=None):
    dossier_id = dosare._id(dossier_id)
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    if status is not None:
        status = constatari_manuale.normalize_stare(status)
    if not Path(path).exists():
        raise ValueError("Dosar inexistent.")
    dosare.citeste(path, dossier_id)
    where, params = "dosar_id=?", [dossier_id]
    if status is not None:
        where += " AND stare=?"
        params.append(status)
    with dosare._open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] < dosare.SCHEMA_VERSION:
            return {"note": [], "total": 0, "offset": offset, "limita": 50}
        rows = con.execute(
            f"SELECT * FROM note_manuale WHERE {where} ORDER BY modificat_la DESC,id "
            "LIMIT 50 OFFSET ?",
            (*params, offset),
        ).fetchall()
        total = con.execute(f"SELECT count(*) FROM note_manuale WHERE {where}", params).fetchone()[
            0
        ]
        return {"note": [_row(row) for row in rows], "total": total, "offset": offset, "limita": 50}


def salveaza(path, request):
    data = _normalize(request)
    now = datetime.now(UTC).isoformat()
    with dosare._open(path, write=True) as con:
        if not con.execute("SELECT 1 FROM dosare WHERE id=?", (data["dosar_id"],)).fetchone():
            raise ValueError("Dosar inexistent.")
        old = con.execute("SELECT * FROM note_manuale WHERE id=?", (data["id"],)).fetchone()
        if old and old["dosar_id"] != data["dosar_id"]:
            raise ValueError("Nota aparține altui dosar.")
        values = _content(data)
        if old:
            current = (
                old["titlu"],
                old["tip"],
                old["act_id"],
                old["locator"],
                old["citat_dovada"],
                old["sursa_url"],
                old["sursa_sha256"],
                old["rationament"],
                old["stare"],
            )
            if current != values:
                if data["revizie"] != old["revizie"]:
                    raise ValueError("Nota a fost modificată. Reîncarcă înainte de a reîncerca.")
                con.execute(
                    "UPDATE note_manuale SET titlu=?,tip=?,act_id=?,locator=?,citat_dovada=?,"
                    "sursa_url=?,sursa_sha256=?,rationament=?,stare=?,revizie=?,modificat_la=? "
                    "WHERE id=?",
                    (*values, old["revizie"] + 1, now, data["id"]),
                )
        else:
            if data["revizie"] != 0:
                raise ValueError("Revizie invalidă.")
            con.execute(
                "INSERT INTO note_manuale VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (data["id"], data["dosar_id"], *values, 0, now, now),
            )
    return citeste(path, data["dosar_id"], data["id"])
