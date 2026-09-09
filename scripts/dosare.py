"""Local research dossiers, separate from replaceable collected source databases."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager, suppress
from datetime import UTC, date, datetime
from pathlib import Path

APPLICATION_ID = 0x4C445352
SCHEMA_VERSION = 3
ENGINE_VERSION = "matrice-dosar-v2"
MAX_REPORT_BYTES = 4_000_000


def cale(stare):
    if getattr(stare, "date_dir", None) is not None:
        raise ValueError("Dosarele persistente sunt disponibile numai în aplicația locală.")
    return Path(stare.initiative).with_suffix(".dosare.db")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Identificator invalid.")
    return value


def _text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("Text invalid sau prea lung.")
    value = value.strip()
    if required and not value:
        raise ValueError("Titlul este obligatoriu.")
    return value


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


@contextmanager
def _open(path, *, write=False):
    path = Path(path)
    if write:
        with suppress(FileExistsError):
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    con = sqlite3.connect(
        path.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=5
    )
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        app = con.execute("PRAGMA application_id").fetchone()[0]
        if write and version == 0 and app == 0:
            if con.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone():
                raise ValueError("Fișierul existent nu este un depozit de dosare.")
            # DDL and version marker commit together; executescript would break this transaction.
            con.execute(
                "CREATE TABLE dosare (id TEXT PRIMARY KEY, titlu TEXT NOT NULL, "
                "intrebare TEXT NOT NULL, domeniu TEXT NOT NULL, data_analizei TEXT, "
                "creat_la TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE rulari (id TEXT PRIMARY KEY, dosar_id TEXT NOT NULL "
                "REFERENCES dosare(id), creat_la TEXT NOT NULL, engine_version TEXT NOT NULL, "
                "sha256 TEXT NOT NULL, filtre_json TEXT NOT NULL, raport_json TEXT NOT NULL, "
                "dovezi_json TEXT NOT NULL, UNIQUE(dosar_id,sha256))"
            )
            con.execute(f"PRAGMA application_id={APPLICATION_ID}")
            version = 1
            app = APPLICATION_ID
        if version not in (1, 2, SCHEMA_VERSION) or app != APPLICATION_ID:
            raise ValueError("Schema depozitului de dosare nu este compatibilă.")
        if write and version == 1:
            con.execute(
                "CREATE TABLE revizuiri (id TEXT PRIMARY KEY, rulare_id TEXT NOT NULL "
                "REFERENCES rulari(id), constatare_id TEXT NOT NULL, revizie INTEGER NOT NULL, "
                "stare TEXT NOT NULL, evaluator TEXT NOT NULL, motiv TEXT NOT NULL, "
                "creat_la TEXT NOT NULL, UNIQUE(rulare_id,constatare_id,revizie))"
            )
            con.execute(
                "CREATE TRIGGER revizuiri_no_update BEFORE UPDATE ON revizuiri "
                "BEGIN SELECT RAISE(ABORT,'Review events are append-only'); END"
            )
            con.execute(
                "CREATE TRIGGER revizuiri_no_delete BEFORE DELETE ON revizuiri "
                "BEGIN SELECT RAISE(ABORT,'Review events are append-only'); END"
            )
            version = 2
        if write and version == 2:
            from scripts.verificari_dovezi import migreaza

            migreaza(con)
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def creeaza(path, request):
    if not isinstance(request, dict) or set(request) - {
        "id",
        "titlu",
        "intrebare",
        "domeniu",
        "data_analizei",
    }:
        raise ValueError("Cerere invalidă.")
    ident = _id(request.get("id"))  # Caller-generated retry token, also the stable dossier ID.
    title = _text(request.get("titlu"), 200, True)
    question = _text(request.get("intrebare", ""), 4000)
    domain = _text(request.get("domeniu", ""), 200)
    when = request.get("data_analizei")
    if when is not None:
        if not isinstance(when, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            raise ValueError("Data analizei trebuie să fie ISO YYYY-MM-DD.")
        date.fromisoformat(when)
    fields = (title, question, domain, when)
    with _open(path, write=True) as con:
        old = con.execute("SELECT * FROM dosare WHERE id=?", (ident,)).fetchone()
        if old:
            if tuple(old[k] for k in ("titlu", "intrebare", "domeniu", "data_analizei")) != fields:
                raise ValueError("Identificator reutilizat cu un conținut diferit.")
            return dict(old)
        con.execute(
            "INSERT INTO dosare VALUES (?,?,?,?,?,?)",
            (ident, *fields, datetime.now(UTC).isoformat()),
        )
        return dict(con.execute("SELECT * FROM dosare WHERE id=?", (ident,)).fetchone())


def lista(path, offset=0):
    if not isinstance(offset, int) or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    if not Path(path).exists():
        return {"dosare": [], "total": 0, "offset": offset, "limita": 50}
    with _open(path) as con:
        rows = con.execute(
            "SELECT * FROM dosare ORDER BY creat_la DESC,id LIMIT 50 OFFSET ?", (offset,)
        ).fetchall()
        return {
            "dosare": [dict(r) for r in rows],
            "total": con.execute("SELECT count(*) FROM dosare").fetchone()[0],
            "offset": offset,
            "limita": 50,
        }


def citeste(path, ident):
    ident = _id(ident)
    if not Path(path).exists():
        raise ValueError("Dosar inexistent.")
    with _open(path) as con:
        row = con.execute("SELECT * FROM dosare WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("Dosar inexistent.")
        return dict(row)


def rulari(path, ident, run_id=None):
    citeste(path, ident)
    with _open(path) as con:
        if run_id is not None:
            row = con.execute(
                "SELECT * FROM rulari WHERE dosar_id=? AND id=?", (ident, _id(run_id))
            ).fetchone()
            if not row:
                raise ValueError("Rulare inexistentă în acest dosar.")
            out = dict(row)
            for key in ("filtre", "raport", "dovezi"):
                out[key] = json.loads(out.pop(key + "_json"))
            return out
        rows = con.execute(
            "SELECT id,creat_la,engine_version,sha256 FROM rulari "
            "WHERE dosar_id=? ORDER BY creat_la DESC,id LIMIT 100",
            (ident,),
        ).fetchall()
        count = con.execute("SELECT count(*) FROM rulari WHERE dosar_id=?", (ident,)).fetchone()[0]
        return {"rulari": [dict(r) for r in rows], "total": count, "trunchiat": count > len(rows)}


def salveaza_rulare(stare, request):
    from scripts.servicii import _matrice_dosar

    if (
        not isinstance(request, dict)
        or not {"dosar_id", "filtre"} <= set(request)
        or set(request) - {"dosar_id", "filtre", "sursa_rulare_id", "proiecte"}
    ):
        raise ValueError("Cerere invalidă.")
    path = cale(stare)
    ident = request["dosar_id"]
    citeste(path, ident)
    filters = request["filtre"]
    if not isinstance(filters, dict) or set(filters) - {
        "emitent",
        "tip",
        "rang",
        "domeniu",
        "problema",
    }:
        raise ValueError("Filtre invalide.")
    filters = {k: _text(v, 300) for k, v in filters.items()}
    if not filters.get("emitent"):
        raise ValueError("Emitentul este obligatoriu.")
    parent = request.get("sursa_rulare_id")
    projects = request.get("proiecte")
    if "proiecte" in request:
        from scripts.dependente_proiecte import selectie

        projects = selectie(projects)
    if "sursa_rulare_id" in request:
        if "proiecte" in request:
            raise ValueError("Recalcularea foloseste sursele rularii originale.")
        original = rulari(path, ident, _id(parent))
        if original["filtre"] != filters:
            raise ValueError("Recalcularea trebuie sa pastreze filtrele rularii originale.")
        if original["raport"].get("selectie_proiecte"):
            from scripts.dependente_proiecte import actualizeaza

            projects = actualizeaza(
                stare,
                original["raport"]["selectie_proiecte"],
                original["dovezi"].get("manifest") or {},
            )
    if projects:
        from scripts.dependente_proiecte import citeste as snapshot
        from scripts.servicii import _conflicte_proiecte

        args = dict(filters)
        for side, ref in projects.items():
            doc = snapshot(stare, ref["plx_id"], ref["versiune_id"])
            if doc["stare"] != "capturat":
                raise ValueError("Versiunea importata nu are text verificabil.")
            args[f"plx_{side}"] = ref["plx_id"]
            args[f"versiune_{side}"] = ref["versiune_id"]
        report = _conflicte_proiecte(args, stare)
        if report.get("error"):
            raise ValueError(report["error"])
        report["selectie_proiecte"] = projects
    else:
        report = _matrice_dosar({k: [v] for k, v in filters.items()}, stare)
    if not report.get("gasit"):
        raise ValueError("Selecția nu produce un dosar de analiză.")
    # Preserve the evidence actually returned; do not present report hashes as source-byte hashes.
    evidence = {
        "acte": report.get("acte", {}),
        "referinte_ue": report.get("referinte_ue", []),
        "candidati": report.get("contradictii", {}).get("candidati", []),
        "limitare": "Dovezi din raport; nu arhivă integrală a versiunilor surselor oficiale.",
    }
    from scripts.dependente_dovezi import captureaza

    evidence["manifest"] = captureaza(stare, report)
    if evidence["referinte_ue"]:
        from scripts.instantanee_ue import captureaza as capture_eu

        evidence["surse_ue"] = capture_eu(stare, evidence["referinte_ue"])
    engine_version = "matrice-proiecte-v1" if projects else ENGINE_VERSION
    payload = _json(
        {"engine_version": engine_version, "filtre": filters, "raport": report, "dovezi": evidence}
    )
    if len(payload.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Raportul depășește limita de 4 MB; restrânge selecția.")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with _open(path, write=True) as con:
        con.execute(
            "INSERT OR IGNORE INTO rulari VALUES (?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                ident,
                datetime.now(UTC).isoformat(),
                engine_version,
                digest,
                _json(filters),
                _json(report),
                _json(evidence),
            ),
        )
        run_id = con.execute(
            "SELECT id FROM rulari WHERE dosar_id=? AND sha256=?", (ident, digest)
        ).fetchone()[0]
        if parent and parent != run_id:
            con.execute(
                "INSERT OR IGNORE INTO recalculari VALUES (?,?,?)",
                (parent, run_id, datetime.now(UTC).isoformat()),
            )
    return rulari(path, ident, run_id)


def backup(path, destination):
    """SQLite's backup API includes committed WAL data; never overwrite a destination."""
    destination = Path(destination)
    with _open(path) as source:
        # Exclusive creation prevents a race from overwriting another backup or source database.
        os.close(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        try:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
        except Exception:
            destination.unlink()
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    backup(args.db, args.backup)
