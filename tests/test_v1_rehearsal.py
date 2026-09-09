import json
import shutil
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import dosare
from scripts import v1_rehearsal as rehearsal


def test_rehearsal_repeatable_and_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal.tempfile, "tempdir", str(tmp_path))
    first = rehearsal.rehearse()
    assert rehearsal.rehearse() == first
    assert list(tmp_path.iterdir()) == []
    assert first["domain_acceptance"] == first["release_acceptance"] == "pending"
    assert first["workflow"]["synthetic_bridge"]
    assert first["workflow"]["proposal_revisions"] == 2
    assert first["workflow"]["retained_analysis_exports"] == 2
    assert first["workflow"]["reassessment"]["stare"] == "schimbat"
    assert first["workflow"]["metadata_recovery"] == {
        "archived_revision": 2,
        "restored_active_revision": 3,
        "recovery_rows": 3,
        "recoverable_drafts": 2,
        "tombstones": 1,
    }
    counts = first["workflow"]["restored_row_counts"]
    assert counts["analize_propuneri"] == 2
    assert counts["dosare_stare"] == 1 and counts["ciorne"] == 3
    if dosare.SCHEMA_VERSION >= 9:
        assert counts["legaturi_ue"] == 1
        assert first["workflow"]["eu_link"]["offline_retry_after_source_removal"]
    else:
        assert first["workflow"]["eu_link"]["status"] == "not_exercised_requires_schema9"
    assert first["upgrade"]["actual_schema"] == dosare.SCHEMA_VERSION
    assert first["upgrade"]["migration_exercised"] == (dosare.SCHEMA_VERSION > 7)


def test_fixture_tampering_fails_before_corpus_write(tmp_path):
    manifest = json.loads(rehearsal.MANIFEST.read_text())
    manifest["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="hash mismatch"):
        rehearsal.workflow(tmp_path, manifest)
    assert not (tmp_path / "corpus.db").exists()


def test_network_is_blocked():
    with rehearsal.offline(), pytest.raises(RuntimeError, match="Network forbidden"):
        socket.create_connection(("127.0.0.1", 9))


def test_rehearsal_runs_without_site_packages():
    program = (
        "import runpy,sys;sys.path.insert(0,"
        + repr(str(rehearsal.ROOT))
        + ");runpy.run_module('scripts.v1_rehearsal',run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", program],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    data = json.loads(result.stdout)
    assert data["status"] == "fixture_rehearsal_passed"
    assert data["workflow"]["actual_schema"] == dosare.SCHEMA_VERSION


def test_ambient_reports_are_not_read(tmp_path, monkeypatch):
    reports = tmp_path / "web/data"
    reports.mkdir(parents=True)
    for name in ("vid.json", "neconstitutional.json", "norme_lovite.json", "parlament.json"):
        (reports / name).write_text("[]")
    monkeypatch.chdir(tmp_path)
    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(reports), "Ambient report was read"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    result = rehearsal.rehearse()
    assert result["status"] == "fixture_rehearsal_passed"


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_restored_retry_matches_browser_request(tmp_path):
    with rehearsal.offline():
        rehearsal.workflow(tmp_path, json.loads(rehearsal.MANIFEST.read_text()))
    path = dosare.cale(rehearsal.state_at(tmp_path / "restored"))
    with sqlite3.connect(path) as con:
        row = con.execute(
            "SELECT id,dosar_id,continut_json FROM ciorne "
            "WHERE id != 'editor' AND continut_json != 'null'"
        ).fetchone()
    program = (
        "const assert=require('node:assert/strict');\n"
        + "\nconst [run,dossier,raw]="
        + json.dumps(row)
        + ";\n"
        + """
const [key,record]=JSON.parse(raw).drafts[0];
const values={titlu:record.values.titlu,text:record.values.text,motiv:record.values.motiv};
const payload={...values,dosar_id:dossier,rulare_id:run,
  constatare_id:key.slice('proposal:'.length),revizie:record.revision};
assert.equal(record.retry.fingerprint,JSON.stringify(payload));
assert.equal(record.retry.id,'9'.repeat(32));
"""
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


def test_backup_missing_recovery_table_fails(tmp_path, monkeypatch):
    backup = dosare.backup

    def incomplete(path, destination):
        backup(path, destination)
        with sqlite3.connect(destination) as con:
            con.execute("DROP TABLE ciorne")

    monkeypatch.setattr(dosare, "backup", incomplete)
    with rehearsal.offline(), pytest.raises(RuntimeError, match="Restore changed logical data"):
        rehearsal.workflow(tmp_path, json.loads(rehearsal.MANIFEST.read_text()))


@pytest.mark.skipif(dosare.SCHEMA_VERSION < 9, reason="EU link storage requires schema 9")
def test_backup_missing_eu_link_fails(tmp_path, monkeypatch):
    backup = dosare.backup

    def incomplete(path, destination):
        backup(path, destination)
        with sqlite3.connect(destination) as con:
            con.execute("DROP TABLE legaturi_ue")

    monkeypatch.setattr(dosare, "backup", incomplete)
    with rehearsal.offline(), pytest.raises(RuntimeError, match="Restore changed logical data"):
        rehearsal.workflow(tmp_path, json.loads(rehearsal.MANIFEST.read_text()))


def test_schema7_fixture_contains_real_old_structure_and_synthetic_history(tmp_path):
    path = tmp_path / "baseline.db"
    with sqlite3.connect(path) as con:
        con.executescript(rehearsal.BASELINE.read_text())
        assert con.execute("PRAGMA user_version").fetchone() == (7,)
        assert [r[1] for r in con.execute("PRAGMA table_info(dosare)")] == [
            "id",
            "titlu",
            "intrebare",
            "domeniu",
            "data_analizei",
            "creat_la",
        ]
        assert con.execute("SELECT count(*) FROM propuneri").fetchone() == (2,)
        assert con.execute("SELECT count(*) FROM analize_propuneri").fetchone() == (1,)
    before = rehearsal.sha(path)
    exports = rehearsal.historical_exports(path)
    assert len(exports) == 2 and exports[0]["analiza"] and exports[1]["analiza"] is None
    assert rehearsal.sha(path) == before
