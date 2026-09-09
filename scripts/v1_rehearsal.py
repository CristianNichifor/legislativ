"""Offline fixture rehearsal, never domain acceptance. Run with --help."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import socket
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts import analize_propuneri as analyses
from scripts import (
    depozit,
    dosare,
    etalon_real,
    interventii_propuneri,
    parsare,
    propuneri,
    revizuiri,
    servicii,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/v1_schema7.sql"
MANIFEST = ROOT / "data/v1_pilot.json"
IDENT = "a" * 32


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def offline():
    def denied(*args, **kwargs):
        raise RuntimeError("Network forbidden in fixture rehearsal")

    with (
        patch.object(socket.socket, "connect", denied),
        patch.object(socket.socket, "connect_ex", denied),
        patch.object(socket, "create_connection", denied),
        patch.object(socket, "getaddrinfo", denied),
    ):
        yield


def state_at(root):
    return servicii.Stare(
        **{k: str(root / f"{k}.db") for k in ("corpus", "initiative", "graf", "eu")}
    )


def snapshot(path):
    """Logical rows, including all history; ignore SQLite physical layout."""
    with closing(sqlite3.connect(path)) as con:
        require(con.execute("PRAGMA integrity_check").fetchone() == ("ok",), "Integrity failure")
        require(not con.execute("PRAGMA foreign_key_check").fetchall(), "Foreign key failure")
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            t: sorted(
                con.execute('SELECT * FROM "' + t.replace('"', '""') + '"').fetchall(), key=repr
            )
            for t in tables
        }


def schema(path):
    with closing(sqlite3.connect(path)) as con:
        return con.execute("PRAGMA user_version").fetchone()[0]


def upgrade(root):
    path = root / "upgrade.db"
    with closing(sqlite3.connect(path)) as con:
        con.executescript(BASELINE.read_text())
    require(schema(path) == 7, "Baseline must really be schema 7")
    before = snapshot(path)
    raw = sha(path)
    historical = historical_exports(path)
    require(sha(path) == raw, "Reading baseline changed it")
    rollback = root / "pre-upgrade.db"
    dosare.backup(path, rollback)
    dosare.creeaza(path, {"id": "f" * 32, "titlu": "Post-upgrade rehearsal"})
    require(schema(path) == dosare.SCHEMA_VERSION, "Migration did not reach runtime schema")
    after = snapshot(path)
    # New schema columns may be appended; compare the old named columns explicitly.
    with closing(sqlite3.connect(rollback)) as old, closing(sqlite3.connect(path)) as new:
        for table, rows in before.items():
            cols = [r[1] for r in old.execute(f'PRAGMA table_info("{table}")')]
            quoted = ",".join('"' + c + '"' for c in cols)
            actual = new.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
            require(all(row in actual for row in rows), f"Upgrade lost history: {table}")
    require(historical_exports(path) == historical, "Upgrade changed historical exports")
    require(snapshot(rollback) == before, "Rollback backup changed")
    require(historical_exports(rollback) == historical, "Rollback history unreadable")
    migrated_backup = root / "post-upgrade.db"
    dosare.backup(path, migrated_backup)
    require(snapshot(migrated_backup) == after, "Post-upgrade backup lost data")
    return {
        "baseline_schema": 7,
        "actual_schema": schema(path),
        "migration_exercised": schema(path) > 7,
        "baseline_sha256": sha(BASELINE),
        "preserved_tables": sorted(after),
        "historical_exports": len(historical),
    }


def historical_exports(path):
    with closing(sqlite3.connect(path)) as con:
        refs = con.execute(
            "SELECT r.dosar_id,p.rulare_id,p.constatare_id,p.revizie "
            "FROM propuneri p JOIN rulari r ON r.id=p.rulare_id ORDER BY p.revizie"
        ).fetchall()
    return [propuneri.exporta(path, *ref) for ref in refs]


def workflow(root, manifest):
    corpus = root / "corpus.db"
    sources = []
    parsed = []
    for entry in manifest["sources"]:
        path = ROOT / entry["path"]
        require(sha(path) == entry["sha256"], f"Fixture hash mismatch: {path.name}")
        act = parsare.din_fisier(path, url=entry["source_url"] or "")
        require(act.act.id == entry["act_id"], "Fixture identity mismatch")
        parsed.append(act)
        measurement = etalon_real.masoara_fisier(path)
        sources.append(
            {
                **entry,
                "provisions": len(act.provizii),
                "publisher_marks": measurement.marcaje,
                "marks_found": measurement.gasite,
            }
        )
    depozit.importa(corpus, parsed)
    state = state_at(root)
    path = dosare.cale(state)
    dossier = dosare.creeaza(path, {"id": IDENT, "titlu": "PROPOSED procurement fixture pilot"})
    request = {"dosar_id": IDENT, "filtre": {"emitent": "PARLAMENTUL"}}
    actual = dosare.salveaza_rulare(state, request)
    require(actual == dosare.salveaza_rulare(state, request), "Report retry duplicated")
    findings = revizuiri.constatari(actual)
    # A synthetic finding opens the proposal flow without inventing a legal defect.
    synthetic = {
        "gasit": True,
        "markdown": "SYNTHETIC workflow bridge; no legal finding",
        "contradictii": {
            "candidati": [
                {
                    "tip": "rehearsal",
                    "a": {
                        "act_id": "lege-98-2016",
                        "locator": "art1",
                        "text": "Synthetic workflow bridge, not extracted evidence",
                    },
                }
            ]
        },
    }
    with patch.object(servicii, "_matrice_dosar", return_value=synthetic):
        run = dosare.salveaza_rulare(state, request)
    finding = revizuiri.constatari(run)[0]["id"]
    preview = interventii_propuneri.pregateste(
        state,
        {
            "act_id": "lege-98-2016",
            "locator": "art1",
            "operatie": "modifica",
            "text_nou": "Text sintetic pentru repetitie, fara valoare juridica.",
            "articol_nou": "",
        },
    )
    source_before = sha(corpus)
    req = {
        "id": "b" * 32,
        "dosar_id": IDENT,
        "rulare_id": run["id"],
        "constatare_id": finding,
        "revizie": 0,
        "titlu": "SYNTHETIC proposal",
        "text": preview["text_compus"],
        "motiv": "Rehearsal only",
        "interventie": preview["cerere"],
    }
    first = propuneri.salveaza(path, req, state)
    analysis_req = {k: req[k] for k in ("dosar_id", "rulare_id", "constatare_id")}
    result = analyses.salveaza(state, {**analysis_req, "id": "d" * 32, "revizie": 1})
    require(
        result == analyses.salveaza(state, {**analysis_req, "id": "d" * 32, "revizie": 1}),
        "Analysis retry duplicated",
    )
    propuneri.salveaza(
        path, {**req, "id": "c" * 32, "revizie": 1, "motiv": "Second synthetic revision"}, state
    )
    args = (IDENT, run["id"], finding)
    require(analyses.istoric(path, *args, 2)["selectata"] is None, "Revision inherited analysis")
    require(propuneri.citeste(path, *args, 1)["propunere"] == first, "Historical draft lost")
    exports = historical_exports(path)
    require(exports[0]["analiza"] == result, "Historical analysis lost")
    require(sha(corpus) == source_before, "Proposal workflow modified corpus")
    before = snapshot(path)
    backup = root / "backup.db"
    dosare.backup(path, backup)
    restored_root = root / "restored"
    restored_root.mkdir()
    with (
        closing(sqlite3.connect(corpus)) as source,
        closing(sqlite3.connect(restored_root / "corpus.db")) as target,
    ):
        source.backup(target)
    require(snapshot(restored_root / "corpus.db") == snapshot(corpus), "Corpus restore changed")
    restored = dosare.cale(state_at(restored_root))
    shutil.copyfile(backup, restored)
    require(snapshot(restored) == before, "Restore changed logical data")
    require(historical_exports(restored) == exports, "Restore changed historical exports")
    require(dosare.citeste(restored, IDENT) == dossier, "Restored dossier changed")
    require(dosare.rulari(restored, IDENT, actual["id"]) == actual, "Restored report changed")
    require(dosare.rulari(restored, IDENT, run["id"]) == run, "Restored synthetic report changed")
    (restored_root / "corpus.db").unlink()
    require(historical_exports(restored) == exports, "Historical export needs live corpus")
    return {
        "sources": sources,
        "actual_report_findings": len(findings),
        "synthetic_bridge": True,
        "proposal_revisions": len(exports),
        "analysis_checks": {c["cheie"]: c["stare"] for c in result["controale"]},
        "restored_row_counts": {k: len(v) for k, v in before.items()},
        "actual_schema": schema(path),
    }


def rehearse():
    manifest = json.loads(MANIFEST.read_text())
    with tempfile.TemporaryDirectory(prefix="legislativ-v1-rehearsal-") as directory, offline():
        root = Path(directory)
        return {
            "status": "fixture_rehearsal_passed",
            "domain_acceptance": "pending",
            "release_acceptance": "pending",
            "pilot_status": manifest["status"],
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "network": "blocked; no model calls",
            "temporary_data": "removed on exit",
            "workflow": workflow(root, manifest),
            "upgrade": upgrade(root),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(rehearse(), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
