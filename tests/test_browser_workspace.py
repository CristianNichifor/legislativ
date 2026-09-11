import sqlite3
from types import SimpleNamespace

import pytest

from scripts import browser_workspace as browser
from scripts import dosare
from tests import (
    test_interventii_propuneri,
    test_legaturi_ue,
    test_legaturi_ue_store,
    test_propuneri,
)

case = test_propuneri.case
structured = test_interventii_propuneri.structured
linked_case = test_legaturi_ue.linked_case


def test_trusted_path_does_not_change_report_source(tmp_path):
    state = SimpleNamespace(date_dir=tmp_path / "reports", initiative="public.db")
    with pytest.raises(ValueError):
        dosare.cale(state)
    state.dosare_db = tmp_path / "private.db"
    assert dosare.cale(state) == state.dosare_db
    assert state.date_dir == tmp_path / "reports"
    browser.initialize(state.dosare_db)
    with sqlite3.connect(state.dosare_db) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == dosare.SCHEMA_VERSION


def test_router_uses_shared_proposal_analysis_services(case):
    state, path, run, req = case
    state.dosare_db = path
    state.date_dir = path.parent / "reports"

    def route(suffix, body):
        return browser.route(state, "/api/dosare" + suffix, {}, body, "POST")

    proposal = route("/propuneri", req)
    assert proposal["text"] == req["text"]
    query = {k: [req[k]] for k in ("dosar_id", "rulare_id", "constatare_id")}
    # Shared request query uses id for the dossier identity.
    query["id"] = query.pop("dosar_id")
    out = browser.route(state, "/api/dosare/propuneri", query, {})
    assert out
    browser.validate(path)
    assert dosare.rulari(path, req["dosar_id"], req["rulare_id"]) == run


def test_recovery_rejects_foreign_and_corrupt_database(tmp_path):
    foreign = tmp_path / "foreign.db"
    with sqlite3.connect(foreign) as con:
        con.execute("CREATE TABLE private_data (value TEXT)")
    with pytest.raises(ValueError):
        browser.validate(foreign)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        browser.validate(broken)


def test_eu_routes_share_native_preview_save_history(linked_case):
    state, path, selection = linked_case
    state.dosare_db = path
    state.date_dir = path.parent / "public-reports"
    request = test_legaturi_ue_store.request(state, selection)
    result = browser.route(state, "/api/dosare/propuneri/legaturi-ue", {}, request, "POST")
    query = {k: [str(v)] for k, v in selection.items() if k != "dosar_id"}
    query["id"] = [selection["dosar_id"]]
    state.eu.unlink()
    history = browser.route(state, "/api/dosare/propuneri/legaturi-ue", query, {})
    assert history["selectata"] == result


def test_import_checkpoints_wal_mode(tmp_path):
    path = tmp_path / "wal.db"
    dosare.creeaza(path, {"id": "a" * 32, "titlu": "WAL backup"})
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA journal_mode=WAL")
    browser.validate(path)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert dosare.citeste(path, "a" * 32)["titlu"] == "WAL backup"


@pytest.mark.parametrize(
    "variant", ["minimal", "foreign", "missing", "view", "generated", "virtual"]
)
def test_import_rejects_spoofed_schema10(tmp_path, variant):
    path = tmp_path / "spoof.db"
    if variant not in {"minimal", "foreign"}:
        browser.initialize(path)
    with sqlite3.connect(path) as con:
        con.execute(f"PRAGMA application_id={dosare.APPLICATION_ID}")
        con.execute(f"PRAGMA user_version={dosare.SCHEMA_VERSION}")
        if variant == "foreign":
            con.execute("CREATE TABLE foreign_data(value)")
        elif variant == "missing":
            con.execute("DROP TABLE ciorne")
        elif variant == "view":
            con.execute("DROP TABLE ciorne")
            con.execute("CREATE VIEW ciorne AS SELECT * FROM dosare")
        elif variant == "generated":
            con.execute("ALTER TABLE ciorne ADD COLUMN extra GENERATED ALWAYS AS (1) VIRTUAL")
        elif variant == "virtual":
            con.execute("CREATE VIRTUAL TABLE unexpected USING fts5(value)")
    with pytest.raises(ValueError, match="Schema"):
        browser.validate(path)


def test_import_migrates_canonical_schema8(tmp_path):
    path = tmp_path / "v8.db"
    browser.initialize(path)
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE note_manuale")
        con.execute("DROP TABLE legaturi_ue")
        con.execute("PRAGMA user_version=8")
    browser.validate(path)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == dosare.SCHEMA_VERSION


def test_route_rejects_unsupported_method_and_acquisition(tmp_path):
    state = SimpleNamespace(dosare_db=tmp_path / "d.db")
    for method, suffix in [("DELETE", ""), ("POST", "/propuneri/surse")]:
        with pytest.raises(ValueError):
            browser.route(state, "/api/dosare" + suffix, {}, {}, method)


def test_build_copies_optional_parent_update_script(tmp_path, monkeypatch):
    from scripts import construieste_web as build

    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text('<head></head><body><script src="dataset-updates.js"></script>')
    (app / "browser-workspace.js").write_text("// workspace")
    (app / "browser-generation.js").write_text("// generations")
    (app / "dataset-updates.js").write_text("// parent update controls")
    web = tmp_path / "web"
    web.mkdir()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "WEB", web)
    build._pagina(felii_cautare=1)
    assert (web / "dataset-updates.js").read_text() == "// parent update controls"
    assert (web / "browser-workspace.js").is_file()
