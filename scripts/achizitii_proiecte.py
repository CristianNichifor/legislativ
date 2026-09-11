"""Local parliamentary source browser and explicit, recorded acquisition actions."""

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from scripts import documente_proiecte as documente
from scripts.lifecycle import normalize_stage_label, watchlist_lifecycle

PAGE_SIZE = 25
MAX_RECORDS = 100


def _readonly(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    budget = 0

    def stop():
        nonlocal budget
        budget += 1
        return budget > 20_000

    con.set_progress_handler(stop, 10_000)
    return con


def _initiative(stare, plx):
    if not isinstance(plx, str) or not 1 <= len(plx) <= 120:
        raise ValueError("Selecteaza o initiativa.")
    with closing(_readonly(stare.initiative)) as con:
        row = con.execute(
            "SELECT plx_id, titlu, stadiu, citit_la, cam, idp FROM initiative WHERE plx_id=?",
            (plx,),
        ).fetchone()
    if not row:
        raise ValueError("Initiativa nu exista in baza locala.")
    return dict(row)


def _metadata(row):
    out = dict(row)
    addressable = out["cam"] in (1, 2) and bool(re.fullmatch(r"\d{1,10}", out["idp"] or ""))
    out["fisa_url"] = (
        f"{documente.BASE}.proiect?cam={out['cam']}&idp={out['idp']}" if addressable else None
    )
    out["limba"] = None  # Parliamentary imports do not record an independently verified language.
    out["actualitate"] = "necunoscuta"
    out["lifecycle"] = normalize_stage_label(out.get("stadiu"))
    out["watchlist"] = watchlist_lifecycle(out)
    return out


def _local(stare, plx, detail=False):
    out = {"versiuni_total": 0, "versiuni": [], "incercari": [], "stare": "metadate"}
    path = documente.cale_store(stare)
    if not path.exists():
        return out
    with closing(_readonly(path)) as con:
        con.execute("BEGIN")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables.intersection({"documente", "achizitii"}):
            raise sqlite3.DatabaseError("Unrecognized import store")
        if "documente" in tables:
            out["versiuni_total"] = con.execute(
                "SELECT count(*) FROM documente WHERE plx_id=?", (plx,)
            ).fetchone()[0]
            if out["versiuni_total"]:
                out["stare"] = "importat"
            if detail:
                out["versiuni"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT id, url, label, sha256, preluat_la, status FROM documente "
                        "WHERE plx_id=? ORDER BY preluat_la DESC, id DESC LIMIT ?",
                        (plx, MAX_RECORDS),
                    )
                ]
        if "achizitii" in tables:
            rows = [
                dict(r)
                for r in con.execute(
                    "SELECT operatie, url, versiune, incercat_la, reusit_la, stare, eroare "
                    "FROM achizitii WHERE plx_id=? "
                    "ORDER BY incercat_la DESC, operatie, url LIMIT ?",
                    (plx, MAX_RECORDS + 1 if detail else 1),
                )
            ]
            out["ultima_incercare"] = rows[0] if rows else None
            if detail:
                out["incercari"] = rows[:MAX_RECORDS]
                out["incercari_trunchiate"] = len(rows) > MAX_RECORDS
        out["versiuni_trunchiate"] = out["versiuni_total"] > len(out["versiuni"])
    return out


def lista(stare, query="", offset=0):
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Cautare prea lunga.")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 100_000:
        raise ValueError("Pagina invalida.")
    # Escape LIKE metacharacters: searches are literal, not caller-controlled wildcard scans.
    needle = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with closing(_readonly(stare.initiative)) as con:
        rows = con.execute(
            "SELECT plx_id, titlu, stadiu, citit_la, cam, idp FROM initiative "
            "WHERE plx_id LIKE ? ESCAPE '\\' OR titlu LIKE ? ESCAPE '\\' "
            "ORDER BY plx_id LIMIT ? OFFSET ?",
            (needle, needle, PAGE_SIZE + 1, offset),
        ).fetchall()
    results = []
    for row in rows[:PAGE_SIZE]:
        item = _metadata(row)
        try:
            item.update(_local(stare, row["plx_id"]))
        except (OSError, sqlite3.Error):
            item.update(stare="indisponibil", versiuni_total=None)
        results.append(item)
    return {
        "mod": "local",
        "initiative": results,
        "offset": offset,
        "mai_multe": len(rows) > PAGE_SIZE,
    }


def detaliu(stare, plx):
    return {**_metadata(_initiative(stare, plx)), **_local(stare, plx, detail=True)}


def _record(stare, plx, operation, url, version, error=None):
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(documente.cale_store(stare), timeout=5) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS achizitii (plx_id TEXT NOT NULL, operatie TEXT NOT NULL, "
            "url TEXT NOT NULL, versiune TEXT, incercat_la TEXT NOT NULL, reusit_la TEXT, "
            "stare TEXT NOT NULL, eroare TEXT, PRIMARY KEY(plx_id, operatie, url))"
        )
        con.execute(
            "INSERT INTO achizitii VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(plx_id,operatie,url) DO UPDATE SET versiune=excluded.versiune, "
            "incercat_la=excluded.incercat_la, "
            "reusit_la=coalesce(excluded.reusit_la,achizitii.reusit_la), "
            "stare=excluded.stare, eroare=excluded.eroare",
            (
                plx,
                operation,
                url,
                version,
                now,
                None if error else now,
                "eroare" if error else "ok",
                error,
            ),
        )


def executa(stare, request):
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("operatie"), str)
        or request["operatie"]
        not in {
            "descopera",
            "importa",
            "actualizeaza",
        }
    ):
        raise ValueError("Operatie invalida.")
    plx, operation = request.get("plx"), request["operatie"]
    meta = _metadata(_initiative(stare, plx))
    if not meta["fisa_url"]:
        raise ValueError("Initiativa nu are o fisa parlamentara adresabila.")
    version = None
    if operation == "descopera":
        url = meta["fisa_url"]
    elif operation == "importa":
        url = documente.url_oficial(request.get("url"))
    else:
        version = request.get("versiune")
        if not isinstance(version, str) or len(version) != 64:
            raise ValueError("Selecteaza o versiune importata.")
        url = documente.citeste(stare, plx, version)["url"]
    try:
        if operation == "descopera":
            result = documente.lista(stare, plx)
            if result.get("avertisment"):
                raise OSError("Official source unavailable")
        elif operation == "importa":
            result = documente.importa(stare, plx, url)
        else:
            result = documente.verifica_actualizari(stare, plx, version)
    except (OSError, ValueError, sqlite3.Error) as exc:
        # Do not persist raw transport/database exceptions, which may contain local paths.
        if isinstance(exc, sqlite3.Error):
            error = "Depozitul local de importuri nu este disponibil."
        elif isinstance(exc, OSError):
            error = "Sursa oficiala nu este disponibila."
        else:
            error = "Documentul nu apare pe fisa sau formatul/extragerea nu este acceptat(a)."
        try:
            _record(stare, plx, operation, url, version, error)
        except (OSError, sqlite3.Error):
            raise ValueError(error + " Incercarea nu a putut fi inregistrata.") from exc
        raise ValueError(error) from exc
    try:
        _record(stare, plx, operation, url, version)
    except (OSError, sqlite3.Error):
        result["avertisment_achizitie"] = (
            "Rezultatul este disponibil, dar incercarea nu a fost inregistrata."
        )
    return result
