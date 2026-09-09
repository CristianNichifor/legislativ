import json
import socket
import sqlite3

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
