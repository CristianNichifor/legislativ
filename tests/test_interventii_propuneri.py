import sqlite3

import pytest

from scripts import dosare, interventii_propuneri, propuneri
from tests import test_propuneri
from tests.test_dosare import request as http

case = test_propuneri.case


@pytest.fixture
def structured(case):
    state, path, run, req = case
    state.corpus = path.with_name("corpus.db")
    with sqlite3.connect(state.corpus) as con:
        con.execute("CREATE TABLE acte(id TEXT, sursa_url TEXT, citit_la TEXT)")
        con.execute(
            "INSERT INTO acte VALUES ('lege-98-2016','https://legislatie.just.ro/test','2026-01-01')"
        )
        con.execute(
            "CREATE TABLE provizii(act_id TEXT,locator TEXT,ord INTEGER,text TEXT,"
            "vigoare_de_la TEXT,vigoare_pana_la TEXT)"
        )
        con.execute(
            "INSERT INTO provizii VALUES ('lege-98-2016','art1',1,'Original local text',NULL,NULL)"
        )
    intent = {
        "act_id": "lege-98-2016",
        "locator": "art1",
        "operatie": "modifica",
        "text_nou": "Text nou.",
        "articol_nou": "",
    }
    return state, path, run, req, intent


@pytest.mark.parametrize("operation", ["modifica", "abroga", "introduce"])
def test_preview_save_resume_export_and_unchanged_sources(structured, operation):
    state, path, run, req, intent = structured
    intent["operatie"] = operation
    if operation == "abroga":
        intent["text_nou"] = ""
    if operation == "introduce":
        intent["articol_nou"] = "1^1"
    before = state.corpus.read_bytes()
    preview = interventii_propuneri.pregateste(state, intent)
    assert preview["inainte"] == "Original local text" and not preview["verificare"]
    assert preview["dupa"] == intent["text_nou"]
    request = {**req, "text": preview["text_compus"], "interventie": preview["cerere"]}
    saved = propuneri.salveaza(path, request, state)
    assert saved["interventie"] == preview
    assert (
        propuneri.citeste(path, req["dosar_id"], run["id"], req["constatare_id"])["propunere"]
        == saved
    )
    assert propuneri.salveaza(path, request, state) == saved
    exported = propuneri.exporta(path, req["dosar_id"], run["id"], req["constatare_id"], 1)
    assert "Original local text" in exported["markdown"]
    assert exported["rulare"] == run
    assert before == state.corpus.read_bytes()
    backup = path.with_name("backup.db")
    dosare.backup(path, backup)
    assert (
        propuneri.citeste(backup, req["dosar_id"], run["id"], req["constatare_id"])["propunere"]
        == saved
    )
    with sqlite3.connect(path) as con:
        for sql in (
            "DELETE FROM interventii_propuneri",
            "UPDATE interventii_propuneri SET continut_json='{}'",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)


def test_stale_target_rejected_but_committed_retry_uses_original_snapshot(structured):
    state, path, _, req, intent = structured
    preview = interventii_propuneri.pregateste(state, intent)
    request = {**req, "text": preview["text_compus"], "interventie": preview["cerere"]}
    saved = propuneri.salveaza(path, request, state)
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed source'")
    assert propuneri.salveaza(path, request, state) == saved
    with pytest.raises(ValueError, match="schimbat"):
        propuneri.salveaza(path, {**request, "id": "c" * 32, "revizie": 1}, state)
    with pytest.raises(ValueError):
        propuneri.salveaza(path, {**request, "motiv": "Different retry"}, state)


@pytest.mark.parametrize(
    "patch",
    [
        {"act_id": "A"},
        {"locator": ""},
        {"locator": "art1.art2"},
        {"locator": "artII"},
        {"operatie": "unknown"},
        {"text_nou": ""},
        {"text_nou": "x" * 12001},
        {"articol_nou": "2"},
        {"extra": "x"},
        {"operatie": "abroga"},
        {"operatie": "introduce", "articol_nou": "1"},
    ],
)
def test_invalid_ambiguous_or_colliding_targets(structured, patch):
    state, _, _, _, intent = structured
    with pytest.raises(ValueError):
        interventii_propuneri.pregateste(state, {**intent, **patch})


def test_missing_duplicate_or_oversized_source(structured):
    state, _, _, _, intent = structured
    with pytest.raises(ValueError):
        interventii_propuneri.pregateste(state, {**intent, "locator": "art999"})
    with sqlite3.connect(state.corpus) as con:
        con.execute(
            "INSERT INTO provizii VALUES ('lege-98-2016','art1',2,'Conflicting text',NULL,NULL)"
        )
    with pytest.raises(ValueError, match="ambigue"):
        interventii_propuneri.pregateste(state, intent)
    with sqlite3.connect(state.corpus) as con:
        con.execute("DELETE FROM provizii WHERE ord=2")
        con.execute("UPDATE provizii SET text=?", ("x" * 80001,))
    with pytest.raises(ValueError, match="limita"):
        interventii_propuneri.pregateste(state, intent)


def test_v5_failed_save_rolls_back_migration_and_legacy_remains_readable(structured):
    state, path, _, req, intent = structured
    propuneri.salveaza(path, req)
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE ciorne")
        con.execute("DROP TABLE legaturi_ue")
        con.execute("DROP TABLE dosare_stare")
        con.execute("DROP TABLE analize_propuneri")
        con.execute("DROP TABLE interventii_propuneri")
        con.execute("PRAGMA user_version=5")
    original = path.read_bytes()
    assert "interventie" not in test_propuneri.read(path, req)["propunere"]
    assert path.read_bytes() == original
    preview = interventii_propuneri.pregateste(state, intent)
    request = {
        **req,
        "id": "c" * 32,
        "revizie": 1,
        "text": preview["text_compus"],
        "interventie": preview["cerere"],
    }
    with pytest.raises(ValueError):
        propuneri.salveaza(path, {**request, "text": "Forged wording"}, state)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5
    assert propuneri.salveaza(path, request, state)["interventie"] == preview


def test_http_preview_boundaries_and_server_derived_snapshot(structured):
    state, path, _, req, intent = structured
    url = "/api/dosare/propuneri/previzualizare"
    request = {k: req[k] for k in ("dosar_id", "rulare_id", "constatare_id")}
    request["interventie"] = intent
    assert http(state, "POST", url, request, origin="https://evil.test")[0] == 403
    assert http(state, "POST", url, request, host="evil:8123")[0] == 403
    assert http(state, "POST", url, request, length=80001)[0] == 413
    assert http(state, "POST", url, {**request, "dosar_id": "e" * 32})[0] == 400
    code, preview = http(state, "POST", url, request)
    assert code == 200
    assert test_propuneri.read(path, req)["propunere"] is None
    assert (
        http(
            state,
            "POST",
            "/api/dosare/propuneri",
            {**req, "text": preview["text_compus"], "interventie": preview["cerere"]},
        )[0]
        == 200
    )
    state.date_dir = "static"
    assert http(state, "POST", url, request)[0] == 400
