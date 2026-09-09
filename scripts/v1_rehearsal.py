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
    surse_propuneri,
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


class RehearsalState(servicii.Stare):
    def _incarca_raport(self, nume):
        """This fixture corpus has no precomputed reports; never read ambient cwd data."""
        return []


def state_at(root):
    return RehearsalState(
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


def analysis_exports(path):
    with closing(sqlite3.connect(path)) as con:
        refs = con.execute(
            "SELECT r.dosar_id,p.rulare_id,p.constatare_id,p.revizie,a.id "
            "FROM analize_propuneri a JOIN propuneri p ON p.id=a.propunere_id "
            "JOIN rulari r ON r.id=p.rulare_id ORDER BY a.seq"
        ).fetchall()
    return [propuneri.exporta(path, *ref) for ref in refs]


def populate_eu_link(state, args):
    if dosare.SCHEMA_VERSION < 9:
        return None
    from scripts import achizitii_ue, legaturi_ue
    from scripts import legaturi_ue_store as store
    from tests.test_instantanee_ue import write

    body = "Obligatie sintetica pentru repetitie, fara valoare juridica."
    write(state, "REGULAMENT SINTETIC DE TEST\nArticolul 1\nObligatii de test\n" + body)
    selected = dict(zip(("dosar_id", "rulare_id", "constatare_id"), args, strict=True)) | {
        "revizie": 1,
        "celex": "32018R1805",
        "locator": "art1",
        "instantanee": achizitii_ue.detaliu(state, "32018R1805")["curenta"]["id"],
    }
    preview = legaturi_ue.preview(state, selected)
    require(preview["state"] == "ready_for_explicit_link", "Synthetic EU body was not usable")
    request = selected | {
        "id": "8" * 32,
        "baza_sha256": preview["baza_sha256"],
        "autor": "SYNTHETIC rehearsal author",
        "ipoteza": "potential_gap",
        "obligatie": body,
        "motiv": "Synthetic fixture only; no legal assessment.",
    }
    saved = store.salveaza(state, request)
    history = store.istoric(dosare.cale(state), *args, 1, link_id=saved["id"])
    require(
        history["selectata"] == saved and body in history["markdown"],
        "EU history/export lost retained obligation",
    )
    return request, saved, history


def verify_eu_link(state, args, link):
    if link is None:
        return
    from scripts import legaturi_ue_store as store

    request, saved, history = link
    path = dosare.cale(state)
    require(
        store.istoric(path, *args, 1, link_id=saved["id"]) == history,
        "EU exact-revision history/export changed",
    )
    require(store.istoric(path, *args, 1)["total"] == 1, "EU retry duplicated link")
    require(store.istoric(path, *args, 2)["total"] == 0, "EU link leaked to another revision")
    try:
        store.istoric(path, *args, 2, link_id=saved["id"])
    except ValueError:
        pass
    else:
        raise RuntimeError("EU historical link accepted for wrong revision")
    require(store.salveaza(state, request) == saved, "EU retry changed retained link")


def populate_history(state, path, args, baseline, first, original_export, actual):
    # Deliberately mutate only the disposable imported corpus, never the committed fixture.
    with closing(sqlite3.connect(state.corpus)) as con, con:
        con.execute(
            "UPDATE provizii SET text=? WHERE act_id=? AND locator=?",
            ("SYNTHETIC source change for reassessment rehearsal.", "lege-98-2016", "art1"),
        )
    raw = sha(path)
    comparison = surse_propuneri.verifica(state, *args, 1, baseline["id"])
    require(comparison["stare"] == "schimbat", "Synthetic source change was not detected")
    require(sha(path) == raw, "Read-only source comparison wrote dossier data")
    request = dict(zip(("dosar_id", "rulare_id", "constatare_id"), args, strict=True)) | {
        "id": "e" * 32,
        "revizie": 1,
        "analiza_baza_id": baseline["id"],
    }
    reassessed = analyses.salveaza(state, request)
    require(reassessed["reevaluare"]["salvata"], "Reassessment was not saved")
    require(reassessed["reevaluare"]["stare"] == "schimbat", "Reassessment lost source delta")
    require(analyses.salveaza(state, request) == reassessed, "Reassessment retry duplicated")
    require(
        propuneri.exporta(path, *args, 1, baseline["id"]) == original_export,
        "Reassessment changed original historical export",
    )
    require(
        propuneri.citeste(path, *args, 1)["propunere"] == first,
        "Reassessment rewrote saved proposal",
    )
    require(
        analyses.istoric(path, *args, 2)["selectata"] is None,
        "Reassessment leaked to a later proposal revision",
    )

    renamed = dosare.modifica(
        path, {"id": IDENT, "titlu": "PROPOSED renamed rehearsal", "arhivat": False, "revizie": 0}
    )
    archive_request = {
        "id": IDENT,
        "titlu": renamed["titlu"],
        "arhivat": True,
        "revizie": renamed["revizie"],
    }
    archived = dosare.modifica(path, archive_request)
    require(dosare.modifica(path, archive_request) == archived, "Archive retry changed metadata")
    require(dosare.lista(path)["total"] == 0, "Archived dossier remains in active list")
    require(dosare.lista(path, stare="arhivate")["total"] == 1, "Archived dossier missing")

    draft_values = {
        "titlu": "SYNTHETIC unfinished proposal",
        "text": "SYNTHETIC unfinished proposal",
        "motiv": "Rehearsal only",
    }
    retry_payload = {
        **draft_values,
        "dosar_id": args[0],
        "rulare_id": args[1],
        "constatare_id": args[2],
        "revizie": 2,
    }
    # Match JSON.stringify on the browser's ordered FormData-derived request.
    retry_fingerprint = json.dumps(retry_payload, ensure_ascii=False, separators=(",", ":"))
    contents = {
        "editor": {"versiune": 1, "text": "SYNTHETIC unfinished editor draft"},
        args[1]: {
            "versiune": 1,
            "drafts": [
                [
                    f"proposal:{args[2]}",
                    {
                        "revision": 2,
                        "values": draft_values,
                        "retry": {"id": "9" * 32, "fingerprint": retry_fingerprint},
                    },
                ]
            ],
            "transactions": [],
        },
        actual["id"]: {"versiune": 1, "drafts": [], "transactions": []},
    }
    recovery = {}
    for ident, content in contents.items():
        body = {
            "id": ident,
            "dosar_id": None if ident == "editor" else IDENT,
            "revizie": 0,
            "continut": content,
        }
        saved = dosare.salveaza_ciorna(path, body)
        require(dosare.salveaza_ciorna(path, body) == saved, "Recovery retry changed record")
        if ident == actual["id"]:
            saved = dosare.salveaza_ciorna(
                path, {**body, "revizie": saved["revizie"], "continut": None}
            )
        recovery[ident] = saved
    require(dosare.lista_ciorne(path)["total"] == 2, "Recovery tombstone was listed")
    return archived, recovery, request, reassessed


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
    eu_link = populate_eu_link(state, args)
    archived, recovery, reassessment_request, reassessed = populate_history(
        state, path, args, result, first, exports[0], actual
    )
    dossier = dosare.citeste(path, IDENT)
    exports = historical_exports(path)
    retained_analyses = analysis_exports(path)
    require(len(retained_analyses) == 2, "Expected baseline and reassessment history")
    recovery_list = dosare.lista_ciorne(path)
    before = snapshot(path)
    if eu_link:
        require(len(before["legaturi_ue"]) == 1, "EU link missing from full-row backup")
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
    if eu_link:
        with (
            closing(sqlite3.connect(state.eu)) as source,
            closing(sqlite3.connect(restored_root / "eu.db")) as target,
        ):
            source.backup(target)
        require(snapshot(restored_root / "eu.db") == snapshot(state.eu), "EU restore changed")
    restored = dosare.cale(state_at(restored_root))
    shutil.copyfile(backup, restored)
    require(snapshot(restored) == before, "Restore changed logical data")
    require(historical_exports(restored) == exports, "Restore changed historical exports")
    require(analysis_exports(restored) == retained_analyses, "Restore lost an analysis version")
    require(dosare.metadata(restored, IDENT) == archived, "Restore lost archived metadata")
    require(dosare.lista_ciorne(restored) == recovery_list, "Restore changed recovery library")
    for ident, saved in recovery.items():
        require(dosare.citeste_ciorna(restored, ident) == saved, "Restore changed recovery data")
    require(dosare.citeste(restored, IDENT) == dossier, "Restored dossier changed")
    require(dosare.rulari(restored, IDENT, actual["id"]) == actual, "Restored report changed")
    require(dosare.rulari(restored, IDENT, run["id"]) == run, "Restored synthetic report changed")
    verify_eu_link(state_at(restored_root), args, eu_link)
    (restored_root / "corpus.db").unlink()
    if eu_link:
        (restored_root / "eu.db").unlink()
    verify_eu_link(state_at(restored_root), args, eu_link)
    require(historical_exports(restored) == exports, "Historical export needs live corpus")
    require(analysis_exports(restored) == retained_analyses, "Analysis history needs live corpus")
    require(
        analyses.salveaza(state_at(restored_root), reassessment_request) == reassessed,
        "Restored reassessment retry changed retained result",
    )
    unarchived = dosare.modifica(
        restored,
        {
            "id": IDENT,
            "titlu": archived["titlu"],
            "arhivat": False,
            "revizie": archived["revizie"],
        },
    )
    require(
        not unarchived["arhivat"] and dosare.lista(restored)["total"] == 1,
        "Restored dossier cannot be unarchived",
    )
    for ident, saved in recovery.items():
        require(dosare.citeste_ciorna(restored, ident) == saved, "Unarchive changed recovery data")
    return {
        "sources": sources,
        "actual_report_findings": len(findings),
        "synthetic_bridge": True,
        "proposal_revisions": len(exports),
        "retained_analysis_exports": len(retained_analyses),
        "eu_link": {
            "status": "synthetic_link_verified" if eu_link else "not_exercised_requires_schema9",
            "fixture_kind": "synthetic_text_and_provenance_not_authentic_eu_law",
            "retained_links": 1 if eu_link else 0,
            "offline_retry_after_source_removal": bool(eu_link),
        },
        "reassessment": {
            "source_change": "synthetic_temp_corpus_only",
            "stare": reassessed["reevaluare"]["stare"],
            "comparatie_incompleta": reassessed["reevaluare"]["comparatie_incompleta"],
            "original_export_preserved": True,
            "offline_retry_preserved": True,
        },
        "metadata_recovery": {
            "archived_revision": archived["revizie"],
            "restored_active_revision": unarchived["revizie"],
            "recovery_rows": len(recovery),
            "recoverable_drafts": 2,
            "tombstones": 1,
        },
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
            "precomputed_reports": "explicitly empty; ambient cwd reports are not read",
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
