"""Private dossier watchlists joined to local source-registry state."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from scripts import dosare
from scripts.source_registry import ATTENTION_STATES
from scripts.source_registry import cale as registry_path

KINDS = {
    "act": "Act normativ",
    "project": "Proiect legislativ",
    "celex": "CELEX",
    "domain": "Domeniu",
    "keyword": "Cuvânt cheie",
}
MAX_VALUE = 300


def _kind(value) -> str:
    value = dosare._text(value, 40, True)
    if value not in KINDS:
        raise ValueError("Tip watchlist invalid.")
    return value


def _value(value) -> str:
    text = dosare._text(value, MAX_VALUE, True)
    if any(ord(ch) < 32 for ch in text):
        raise ValueError("Valoare watchlist invalidă.")
    return text


def _label(value) -> str:
    return dosare._text(value or "", 300)


def _review_note(value) -> str:
    return dosare._text(value or "", 500)


def _id(value=None) -> str:
    if value in (None, ""):
        return uuid.uuid4().hex
    return dosare._id(value)


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["tip_label"] = KINDS.get(out["tip"], out["tip"])
    out["revizuit"] = bool(out.get("revizuit_la"))
    return out


def _registry_matches(stare, rows: list[dict]) -> dict[str, dict]:
    path = registry_path(stare)
    if not rows or not Path(path).exists():
        return {}
    pairs = []
    for row in rows:
        if row["tip"] == "celex":
            pairs.append(("ue_cellar", row["valoare"]))
        elif row["tip"] == "project":
            pairs.extend((family, row["valoare"]) for family in ("parlament", "camera", "senat"))
        elif row["tip"] == "act":
            pairs.append(("legislatie_ro", row["valoare"]))
    if not pairs:
        return {}
    where = " OR ".join("(family=? AND identifier=?)" for _ in pairs)
    params = [item for pair in pairs for item in pair]
    try:
        with closing(sqlite3.connect(path)) as con:
            con.row_factory = sqlite3.Row
            records = [
                dict(r)
                for r in con.execute(
                    "SELECT id,family,identifier,url,label,state,last_hash,parser_version,"
                    "last_attempt_at,last_error,updated_at FROM source_registry WHERE " + where,
                    params,
                )
            ]
    except (OSError, sqlite3.Error):
        return {}
    matches = {}
    for record in records:
        for row in rows:
            same_kind = (
                (row["tip"] == "celex" and record["family"] == "ue_cellar")
                or (
                    row["tip"] == "project" and record["family"] in {"parlament", "camera", "senat"}
                )
                or (row["tip"] == "act" and record["family"] == "legislatie_ro")
            )
            if same_kind and record["identifier"] == row["valoare"]:
                current = matches.get(row["id"])
                if current is None or (
                    record["state"] in ATTENTION_STATES
                    and current.get("state") not in ATTENTION_STATES
                ):
                    matches[row["id"]] = record
    return matches


def _feed_item(row: dict, registry: dict | None) -> dict:
    source_state = registry.get("state") if registry else "not_registered"
    reviewed_at = row.get("revizuit_la") or ""
    updated_at = registry.get("updated_at") if registry else ""
    changed_after_review = bool(updated_at and (not reviewed_at or updated_at > reviewed_at))
    needs_attention = bool(
        source_state in ATTENTION_STATES
        and changed_after_review
        or source_state == "not_registered"
    )
    return {
        **row,
        "source_state": source_state,
        "source": registry or {},
        "needs_attention": needs_attention,
        "changed_after_review": changed_after_review,
        "actiuni": {
            "open_dossier": True,
            "rerun_analysis": row["tip"] in {"act", "project"},
            "create_note": True,
            "mark_reviewed": needs_attention,
        },
    }


def lista(path, dossier_id: str, offset: int = 0) -> dict:
    dossier_id = dosare._id(dossier_id)
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    dosare.citeste(path, dossier_id)
    with dosare._open(path) as con:
        rows = [
            _row(r)
            for r in con.execute(
                "SELECT * FROM watchlist_dosare WHERE dosar_id=? ORDER BY creat_la DESC,id "
                "LIMIT 50 OFFSET ?",
                (dossier_id, offset),
            )
        ]
        total = con.execute(
            "SELECT count(*) FROM watchlist_dosare WHERE dosar_id=?", (dossier_id,)
        ).fetchone()[0]
    return {"watchlist": rows, "total": total, "offset": offset, "kinds": KINDS}


def feed(stare, path, dossier_id: str, offset: int = 0) -> dict:
    page = lista(path, dossier_id, offset)
    matches = _registry_matches(stare, page["watchlist"])
    items = [_feed_item(row, matches.get(row["id"])) for row in page["watchlist"]]
    return {
        **page,
        "items": items,
        "attention": sum(1 for item in items if item["needs_attention"]),
        "limitari": [
            "Feed-ul citește starea locală a registrului de surse; nu sincronizează surse.",
            "Domeniile și cuvintele cheie sunt urmărite ca intenție, fără sursă publică unică.",
        ],
    }


def adauga(path, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {
        "id",
        "dosar_id",
        "tip",
        "valoare",
        "eticheta",
    }:
        raise ValueError("Cerere watchlist invalidă.")
    dossier_id = dosare._id(request.get("dosar_id"))
    kind = _kind(request.get("tip"))
    value = _value(request.get("valoare"))
    label = _label(request.get("eticheta")) or value
    ident = _id(request.get("id"))
    stamp = datetime.now(UTC).isoformat()
    with dosare._open(path, write=True) as con:
        if not con.execute("SELECT 1 FROM dosare WHERE id=?", (dossier_id,)).fetchone():
            raise ValueError("Dosar inexistent.")
        con.execute(
            "INSERT INTO watchlist_dosare "
            "(id,dosar_id,tip,valoare,eticheta,creat_la) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(dosar_id,tip,valoare) DO UPDATE SET eticheta=excluded.eticheta",
            (ident, dossier_id, kind, value, label, stamp),
        )
        row = con.execute(
            "SELECT * FROM watchlist_dosare WHERE dosar_id=? AND tip=? AND valoare=?",
            (dossier_id, kind, value),
        ).fetchone()
        return _row(row)


def marcheaza_revizuit(path, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"id", "dosar_id", "nota"}:
        raise ValueError("Cerere watchlist invalidă.")
    ident = dosare._id(request.get("id"))
    dossier_id = dosare._id(request.get("dosar_id"))
    note = _review_note(request.get("nota"))
    stamp = datetime.now(UTC).isoformat()
    with dosare._open(path, write=True) as con:
        row = con.execute(
            "SELECT * FROM watchlist_dosare WHERE id=? AND dosar_id=?", (ident, dossier_id)
        ).fetchone()
        if not row:
            raise ValueError("Element watchlist inexistent.")
        con.execute(
            "UPDATE watchlist_dosare SET revizuit_la=?,nota_revizie=? WHERE id=?",
            (stamp, note, ident),
        )
        return _row(con.execute("SELECT * FROM watchlist_dosare WHERE id=?", (ident,)).fetchone())


def sterge(path, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"id", "dosar_id"}:
        raise ValueError("Cerere watchlist invalidă.")
    ident = dosare._id(request.get("id"))
    dossier_id = dosare._id(request.get("dosar_id"))
    with dosare._open(path, write=True) as con:
        cur = con.execute(
            "DELETE FROM watchlist_dosare WHERE id=? AND dosar_id=?", (ident, dossier_id)
        )
        if cur.rowcount != 1:
            raise ValueError("Element watchlist inexistent.")
    return {"id": ident, "sters": True}


def executa(path, request: dict) -> dict:
    action = dosare._text(request.get("action", "add"), 40) if isinstance(request, dict) else ""
    action = action or "add"
    data = {k: v for k, v in request.items() if k != "action"} if isinstance(request, dict) else {}
    if action == "add":
        return adauga(path, data)
    if action == "review":
        return marcheaza_revizuit(path, data)
    if action == "delete":
        return sterge(path, data)
    raise ValueError("Acțiune watchlist invalidă.")
