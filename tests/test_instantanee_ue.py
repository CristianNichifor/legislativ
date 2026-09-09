import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts import cellar, dosare, instantanee_ue, revizuiri
from tests.test_cellar import EU_TEXT, _manifestare
from tests.test_dosare import ID, create


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(
        eu=tmp_path / "eu?#.db", initiative=tmp_path / "initiative.db", date_dir=None
    )


def write(state, text=EU_TEXT, language="RON", celex="32018R1805"):
    m = replace(
        _manifestare(), celex=celex, limba=language, expression_uri="expression/" + language
    )
    with cellar.deschide(str(state.eu)) as con:
        cellar.scrie_celex(con, celex, [m], m, text)


def capture(state, *ids):
    return instantanee_ue.captureaza(state, [{"celex": c} for c in ids or ["32018R1805"]])


def test_import_preserves_old_text_language_and_provenance(state):
    write(state)
    old = capture(state)["instantanee"][0]
    write(state, "Article 1\nA replacement English text for the imported regulation.", "ENG")
    new = capture(state)["instantanee"][0]
    assert old["id"] != new["id"]
    assert old["sursa"]["limba"] == "RON" and new["sursa"]["limba"] == "ENG"
    assert old["sursa"]["text"] == EU_TEXT
    assert new["sursa"]["text_sha256"] == hashlib.sha256(new["sursa"]["text"].encode()).hexdigest()
    with sqlite3.connect(state.eu) as con:
        stored = dict(con.execute("SELECT id, snapshot_json FROM eu_instantanee"))
        assert json.loads(stored[old["id"]]) == old
        assert json.loads(stored[new["id"]]) == new
        for sql in ("DELETE FROM eu_instantanee", "UPDATE eu_instantanee SET celex='other'"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)


def test_failed_import_rolls_back_current_index_and_snapshot(state, monkeypatch):
    write(state)
    old = capture(state)
    with cellar.deschide(str(state.eu)) as con:
        before = con.execute("SELECT * FROM eu_provizii").fetchall()
        original = instantanee_ue.arhiveaza_curenta
        calls = 0

        def fail_after_update(c, celex):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("simulated archive failure")
            original(c, celex)

        monkeypatch.setattr(instantanee_ue, "arhiveaza_curenta", fail_after_update)
        m = _manifestare()
        with pytest.raises(ValueError, match="simulated"):
            cellar.scrie_celex(
                con, m.celex, [m], m, "Article 1\nChanged content in EU legislation."
            )
        assert con.execute("SELECT * FROM eu_provizii").fetchall() == before
        assert con.execute("SELECT count(*) FROM eu_instantanee").fetchone()[0] == 1
    assert capture(state) == old


def test_outer_transaction_rollback_preserves_no_import(state):
    def abort_import():
        with cellar.deschide(str(state.eu)) as con:
            m = _manifestare()
            cellar.scrie_celex(con, m.celex, [m], m, EU_TEXT)
            raise RuntimeError("abort")

    pytest.raises(RuntimeError, abort_import)
    assert capture(state)["instantanee"][0]["stare"] == "act_negasit"


def test_legacy_read_no_migration_then_import_archives_previous(state):
    with sqlite3.connect(state.eu) as con:
        con.row_factory = sqlite3.Row
        con.executescript(cellar.SCHEMA)
        m = _manifestare()
        cellar._scrie_celex(con, m.celex, [m], m, EU_TEXT)
    old = capture(state)["instantanee"][0]
    with sqlite3.connect(state.eu) as con:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='eu_instantanee'").fetchall()
    write(state, EU_TEXT + "\nAn additional provision.")
    with sqlite3.connect(state.eu) as con:
        assert con.execute("SELECT 1 FROM eu_instantanee WHERE id=?", (old["id"],)).fetchone()


@pytest.mark.parametrize("failure", ["missing", "schema", "hash", "blob", "empty", "metadata"])
def test_unavailable_not_a_successful_snapshot(state, failure):
    expected = "sursa_indisponibila"
    if failure == "schema":
        with sqlite3.connect(state.eu):
            pass
    elif failure != "missing":
        write(state)
        field, value, expected = {
            "hash": ("text_sha256", "bad", "integritate_invalida"),
            "blob": ("text", b"bytes", "integritate_invalida"),
            "empty": ("text", "", "text_indisponibil"),
            "metadata": ("expression_uri", "", "provenienta_incompleta"),
        }[failure]
        with sqlite3.connect(state.eu) as con:
            con.execute(f"UPDATE eu_acte SET {field}=?", (value,))
    result = capture(state)["instantanee"][0]
    assert result == {"celex": "32018R1805", "stare": expected}
    if failure == "missing":
        assert not state.eu.exists()


def test_capture_bounds_deduplicates_and_does_not_hash_partial_text(state, monkeypatch):
    write(state)
    write(state, celex="32014L0024")
    first = capture(state)["instantanee"][0]
    monkeypatch.setattr(
        instantanee_ue, "MAX_DOSSIER_BYTES", len(instantanee_ue._json(first).encode())
    )
    result = capture(state, "32018R1805", "32018R1805", "32014L0024", "32004R0261")
    assert [s["stare"] for s in result["instantanee"]] == [
        "capturat",
        "limita_depasita",
        "act_negasit",
    ]
    assert "id" not in result["instantanee"][1]
    monkeypatch.setattr(instantanee_ue, "MAX_REFERENCES", 1)
    assert capture(state, "32018R1805", "32014L0024")["trunchiat"]
    assert capture(state, "invalid?")["instantanee"] == [{"stare": "referinta_invalida"}]


def test_saved_dossier_survives_source_replacement_deletion_and_backup(state, monkeypatch):
    write(state)
    create(state)
    report = {"gasit": True, "referinte_ue": [{"celex": "32018R1805"}], "markdown": "Report"}
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    request = {"dosar_id": ID, "filtre": {"emitent": "Parlamentul"}}
    old = dosare.salveaza_rulare(state, request)
    assert dosare.salveaza_rulare(state, request) == old
    write(state, EU_TEXT + "\nNew wording.")
    new = dosare.salveaza_rulare(state, request)
    assert new["id"] != old["id"]
    state.eu.unlink()
    path = dosare.cale(state)
    assert dosare.rulari(path, ID, old["id"]) == old
    review = revizuiri.lista(path, ID, old["id"])
    assert review["constatari"] == []
    assert "sha256-json-text-ue-v1" in review["markdown"]
    destination = path.with_name("backup.db")
    dosare.backup(path, destination)
    assert dosare.rulari(destination, ID, old["id"]) == old
    assert not state.eu.exists()
