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
SCHEMA_VERSION = 8
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
        if version not in (1, 2, 3, 4, 5, 6, 7, SCHEMA_VERSION) or app != APPLICATION_ID:
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
            version = 3
        if write and version == 3:
            con.execute(
                "CREATE TABLE contexte_juridice (id TEXT PRIMARY KEY, rulare_id TEXT NOT NULL "
                "REFERENCES rulari(id), constatare_id TEXT NOT NULL, tinta TEXT NOT NULL, "
                "revizie INTEGER NOT NULL, evaluator TEXT NOT NULL, motiv TEXT NOT NULL, "
                "context_json TEXT NOT NULL, creat_la TEXT NOT NULL, "
                "UNIQUE(rulare_id,constatare_id,tinta,revizie))"
            )
            for operation in ("UPDATE", "DELETE"):
                con.execute(
                    f"CREATE TRIGGER contexte_no_{operation.lower()} BEFORE {operation} "
                    "ON contexte_juridice BEGIN "
                    "SELECT RAISE(ABORT,'Legal context is append-only'); END"
                )
            version = 4
        if write and version == 4:
            con.execute(
                "CREATE TABLE propuneri (id TEXT PRIMARY KEY, rulare_id TEXT NOT NULL "
                "REFERENCES rulari(id), constatare_id TEXT NOT NULL, revizie INTEGER NOT NULL, "
                "raport_sha256 TEXT NOT NULL, titlu TEXT NOT NULL, text TEXT NOT NULL, "
                "motiv TEXT NOT NULL, creat_la TEXT NOT NULL, "
                "UNIQUE(rulare_id,constatare_id,revizie))"
            )
            for operation in ("UPDATE", "DELETE"):
                con.execute(
                    f"CREATE TRIGGER propuneri_no_{operation.lower()} BEFORE {operation} "
                    "ON propuneri BEGIN SELECT RAISE(ABORT,'Proposals are append-only'); END"
                )
            version = 5
        if write and version == 5:
            con.execute(
                "CREATE TABLE interventii_propuneri (id TEXT PRIMARY KEY REFERENCES propuneri(id), "
                "continut_json TEXT NOT NULL)"
            )
            for operation in ("UPDATE", "DELETE"):
                con.execute(
                    f"CREATE TRIGGER interventii_no_{operation.lower()} BEFORE {operation} "
                    "ON interventii_propuneri BEGIN "
                    "SELECT RAISE(ABORT,'Proposal interventions are append-only'); END"
                )
            version = 6
        if write and version == 6:
            con.execute(
                "CREATE TABLE analize_propuneri (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "id TEXT NOT NULL UNIQUE, propunere_id TEXT NOT NULL REFERENCES propuneri(id), "
                "creat_la TEXT NOT NULL, rezultat_json TEXT NOT NULL)"
            )
            con.execute(
                "CREATE INDEX analize_propunere ON analize_propuneri(propunere_id,seq DESC)"
            )
            for operation in ("UPDATE", "DELETE"):
                con.execute(
                    f"CREATE TRIGGER analize_propuneri_no_{operation.lower()} BEFORE {operation} "
                    "ON analize_propuneri BEGIN "
                    "SELECT RAISE(ABORT,'Proposal analyses are append-only'); END"
                )
            version = 7
        if write and version == 7:
            con.execute(
                "CREATE TABLE dosare_stare (id TEXT PRIMARY KEY REFERENCES dosare(id), "
                "titlu_initial TEXT NOT NULL, arhivat INTEGER NOT NULL CHECK(arhivat IN (0,1)), "
                "revizie INTEGER NOT NULL)"
            )
            con.execute(
                "CREATE TABLE ciorne (id TEXT PRIMARY KEY, dosar_id TEXT REFERENCES dosare(id), "
                "rulare_id TEXT REFERENCES rulari(id), continut_json TEXT, "
                "revizie INTEGER NOT NULL, modificat_la TEXT NOT NULL)"
            )
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
            initial = con.execute(
                "SELECT titlu_initial FROM dosare_stare WHERE id=?", (ident,)
            ).fetchone()
            if (
                initial[0] if initial else old["titlu"],
                old["intrebare"],
                old["domeniu"],
                old["data_analizei"],
            ) != fields:
                raise ValueError("Identificator reutilizat cu un conținut diferit.")
            return dict(old)
        con.execute(
            "INSERT INTO dosare VALUES (?,?,?,?,?,?)",
            (ident, *fields, datetime.now(UTC).isoformat()),
        )
        return dict(con.execute("SELECT * FROM dosare WHERE id=?", (ident,)).fetchone())


def lista(path, offset=0, stare="active"):
    if not isinstance(offset, int) or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    if stare not in ("active", "arhivate", "toate"):
        raise ValueError("Filtru invalid.")
    if not Path(path).exists():
        return {"dosare": [], "total": 0, "offset": offset, "limita": 50}
    with _open(path) as con:
        modern = con.execute("PRAGMA user_version").fetchone()[0] >= 8
        source = "dosare d LEFT JOIN dosare_stare s ON d.id=s.id" if modern else "dosare d"
        archived = "coalesce(s.arhivat,0)" if modern else "0"
        where = "1" if stare == "toate" else f"{archived}={int(stare == 'arhivate')}"
        rows = con.execute(
            f"SELECT d.*, {archived} AS arhivat FROM {source} WHERE {where} "
            "ORDER BY d.creat_la DESC,d.id LIMIT 50 OFFSET ?",
            (offset,),
        ).fetchall()
        return {
            "dosare": [dict(r) for r in rows],
            "total": con.execute(f"SELECT count(*) FROM {source} WHERE {where}").fetchone()[0],
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


def metadata(path, ident):
    ident = _id(ident)
    if not Path(path).exists():
        raise ValueError("Dosar inexistent.")
    with _open(path) as con:
        dossier = con.execute("SELECT * FROM dosare WHERE id=?", (ident,)).fetchone()
        if not dossier:
            raise ValueError("Dosar inexistent.")
        result = {**dict(dossier), "arhivat": False, "revizie": 0}
        if con.execute("PRAGMA user_version").fetchone()[0] >= 8:
            row = con.execute(
                "SELECT arhivat,revizie FROM dosare_stare WHERE id=?", (ident,)
            ).fetchone()
            if row:
                result.update(arhivat=bool(row[0]), revizie=row[1])
    return result


def modifica(path, request):
    if not isinstance(request, dict) or set(request) != {"id", "titlu", "arhivat", "revizie"}:
        raise ValueError("Cerere invalidă.")
    ident, title = _id(request["id"]), _text(request["titlu"], 200, True)
    if (
        type(request["arhivat"]) is not bool
        or type(request["revizie"]) is not int
        or request["revizie"] < 0
    ):
        raise ValueError("Stare sau revizie invalidă.")
    with _open(path, write=True) as con:
        old = con.execute("SELECT titlu FROM dosare WHERE id=?", (ident,)).fetchone()
        if not old:
            raise ValueError("Dosar inexistent.")
        state = con.execute("SELECT * FROM dosare_stare WHERE id=?", (ident,)).fetchone()
        revision = state["revizie"] if state else 0
        archived = bool(state["arhivat"]) if state else False
        # Exact lost-response retries are harmless; stale differing edits must reload.
        if (old[0], archived) != (title, request["arhivat"]):
            if request["revizie"] != revision:
                raise ValueError(
                    "Dosarul a fost modificat. Reîncarcă metadatele înainte de a reîncerca."
                )
            con.execute("UPDATE dosare SET titlu=? WHERE id=?", (title, ident))
            con.execute(
                "INSERT INTO dosare_stare VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "arhivat=excluded.arhivat,revizie=excluded.revizie",
                (
                    ident,
                    state["titlu_initial"] if state else old[0],
                    int(request["arhivat"]),
                    revision + 1,
                ),
            )
    return metadata(path, ident)


def citeste_ciorna(path, ident):
    if ident != "editor":
        _id(ident)
    empty = {"id": ident, "revizie": 0, "continut": None}
    if not Path(path).exists():
        return empty
    with _open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] < 8:
            return empty
        row = con.execute("SELECT * FROM ciorne WHERE id=?", (ident,)).fetchone()
        if not row:
            return empty
        result = dict(row)
        result["continut"] = json.loads(result.pop("continut_json"))
        return result


def lista_ciorne(path, offset=0):
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset invalid.")
    if not Path(path).exists():
        return {"ciorne": [], "total": 0}
    with _open(path) as con:
        if con.execute("PRAGMA user_version").fetchone()[0] < 8:
            return {"ciorne": [], "total": 0}
        rows = con.execute(
            "SELECT c.id,c.dosar_id,c.modificat_la,d.titlu FROM ciorne c "
            "LEFT JOIN dosare d ON d.id=c.dosar_id WHERE c.continut_json != 'null' "
            "ORDER BY c.modificat_la DESC,c.id LIMIT 50 OFFSET ?",
            (offset,),
        ).fetchall()
        total = con.execute("SELECT count(*) FROM ciorne WHERE continut_json != 'null'").fetchone()[
            0
        ]
        return {"ciorne": [dict(row) for row in rows], "total": total}


def salveaza_ciorna(path, request):
    if not isinstance(request, dict) or set(request) != {"id", "dosar_id", "revizie", "continut"}:
        raise ValueError("Cerere invalidă.")
    ident = request["id"]
    if ident != "editor":
        _id(ident)
        _id(request["dosar_id"])
    elif request["dosar_id"] is not None:
        raise ValueError("Editorul nu aparține unui dosar.")
    content = request["continut"]
    if content is not None and (
        not isinstance(content, dict)
        or type(content.get("versiune")) is not int
        or content["versiune"] != 1
    ):
        raise ValueError("Format de ciornă incompatibil.")
    encoded = _json(content)
    if len(encoded.encode("utf-8")) > 200_000:
        raise ValueError("Ciorna depășește limita de 200 KB.")
    if type(request["revizie"]) is not int or request["revizie"] < 0:
        raise ValueError("Revizie invalidă.")
    with _open(path, write=True) as con:
        if (
            ident != "editor"
            and not con.execute(
                "SELECT 1 FROM rulari WHERE id=? AND dosar_id=?", (ident, request["dosar_id"])
            ).fetchone()
        ):
            raise ValueError("Rulare inexistentă în acest dosar.")
        old = con.execute("SELECT * FROM ciorne WHERE id=?", (ident,)).fetchone()
        revision = old["revizie"] if old else 0
        if not old or old["continut_json"] != encoded:
            if revision != request["revizie"]:
                raise ValueError(
                    "Ciorna a fost modificată. Reîncarcă copia locală înainte de a reîncerca."
                )
            con.execute(
                "INSERT INTO ciorne VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "continut_json=excluded.continut_json,revizie=excluded.revizie,modificat_la=excluded.modificat_la",
                (
                    ident,
                    request["dosar_id"],
                    None if ident == "editor" else ident,
                    encoded,
                    revision + 1,
                    datetime.now(UTC).isoformat(),
                ),
            )
    return citeste_ciorna(path, ident)


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
        archived = con.execute("SELECT arhivat FROM dosare_stare WHERE id=?", (ident,)).fetchone()
        if archived and archived[0]:
            raise ValueError("Dosarul este arhivat. Restaurează-l înainte de a salva analize noi.")
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
