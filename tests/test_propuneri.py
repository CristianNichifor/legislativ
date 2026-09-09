import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from scripts import dosare, propuneri, revizuiri
from tests.test_dosare import request as http

ID = "a" * 32


@pytest.fixture
def case(tmp_path, monkeypatch):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)
    path = dosare.cale(state)
    dosare.creeaza(path, {"id": ID, "titlu": "Proposal fixture"})
    report = {
        "gasit": True,
        "contradictii": {
            "candidati": [
                {
                    "tip": "definitie",
                    "a": {"act_id": "A", "locator": "art1", "text": "Retained A"},
                    "b": {"act_id": "B", "locator": "art2", "text": "Retained B"},
                }
            ]
        },
        "markdown": "Saved fixture, not legal analysis",
    }
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "P"}})
    req = {
        "id": "b" * 32,
        "dosar_id": ID,
        "rulare_id": run["id"],
        "constatare_id": revizuiri.constatari(run)[0]["id"],
        "revizie": 0,
        "titlu": "Amendment",
        "text": "",
        "motiv": "",
    }
    return state, path, run, req


def read(path, req):
    return propuneri.citeste(path, req["dosar_id"], req["rulare_id"], req["constatare_id"])


def test_create_resume_revise_without_review_preserves_basis_and_backup(case):
    state, path, run, req = case
    before = revizuiri.lista(path, ID, run["id"])
    assert read(path, req)["propunere"] is None
    first = propuneri.salveaza(path, req)
    assert first["revizie"] == 1 and first["text"] == ""
    assert read(path, req)["propunere"] == first
    second = propuneri.salveaza(
        path,
        {**req, "id": "c" * 32, "revizie": 1, "text": "New text <script>", "motiv": "Rationale"},
    )
    assert read(path, req)["propunere"] == second
    assert second["raport_sha256"] == run["sha256"]
    assert revizuiri.lista(path, ID, run["id"]) == before
    assert read(path, req)["constatare"] == revizuiri.constatari(run)[0]
    assert propuneri.salveaza(path, req) == first  # Retry after a later revision.
    backup = path.with_name("backup.db")
    dosare.backup(path, backup)
    assert read(backup, req) == read(path, req)
    new = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "Other"}})
    assert read(path, {**req, "rulare_id": new["id"]})["propunere"] is None
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT count(*) FROM propuneri").fetchone()[0] == 2
        for sql in ("DELETE FROM propuneri", "UPDATE propuneri SET text='x'"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)


@pytest.mark.parametrize(
    "patch",
    [
        {"revizie": True},
        {"revizie": -1},
        {"revizie": 1_000_001},
        {"titlu": " "},
        {"titlu": "x" * 201},
        {"text": "x" * 12001},
        {"motiv": "x" * 4001},
        {"text": None},
        {"text": "\x00"},
        {"id": "bad"},
        {"constatare_id": "e" * 32},
        {"rulare_id": "e" * 32},
        {"dosar_id": "f" * 32},
        {"raport_sha256": "client-forgery"},
    ],
)
def test_invalid_request_does_not_write(case, patch):
    _, path, _, req = case
    with pytest.raises(ValueError):
        propuneri.salveaza(path, {**req, **patch})
    assert read(path, req)["propunere"] is None


def test_ownership_and_request_shape(case):
    _, path, _, req = case
    dosare.creeaza(path, {"id": "f" * 32, "titlu": "Other"})
    for bad in (None, [], {}, {**req, "dosar_id": "f" * 32}):
        with pytest.raises(ValueError):
            propuneri.salveaza(path, bad)
    with pytest.raises(ValueError):
        read(path, {**req, "dosar_id": "f" * 32})


def test_retry_and_concurrent_conflict(case):
    _, path, _, req = case
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: propuneri.salveaza(path, req), range(2)))
    assert rows[0] == rows[1]
    with pytest.raises(ValueError, match="reutilizat"):
        propuneri.salveaza(path, {**req, "text": "Different"})

    def save(ident):
        try:
            return propuneri.salveaza(path, {**req, "id": ident, "revizie": 1})
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(save, ["c" * 32, "d" * 32]))
    assert sum(isinstance(row, dict) for row in rows) == 1
    assert "schimbat" in next(row for row in rows if isinstance(row, str))


def test_v4_reads_without_migration_and_failed_write_rolls_back(case):
    _, path, _, req = case
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE propuneri")
        con.execute("PRAGMA user_version=4")
    before = path.read_bytes()
    assert read(path, req)["propunere"] is None
    assert before == path.read_bytes()
    with pytest.raises(ValueError, match="schimbat"):
        propuneri.salveaza(path, {**req, "revizie": 1})
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 4
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='propuneri'").fetchone()
    propuneri.salveaza(path, req)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5


def test_http_local_origin_limits_and_static(case):
    state, _, _, req = case
    url = "/api/dosare/propuneri"
    assert http(state, "POST", url, req, origin="https://evil.test")[0] == 403
    assert http(state, "GET", url, host="evil:8123")[0] == 403
    assert http(state, "POST", url, req, length=80001)[0] == 413
    assert http(state, "POST", "/api/dosare", req, length=16001)[0] == 413
    req["text"] = "a" * 12000
    req["motiv"] = "b" * 4000
    assert http(state, "POST", url, req)[0] == 200  # More than the old 16KB limit.
    query = f"?id={ID}&rulare_id={req['rulare_id']}&constatare_id={req['constatare_id']}"
    assert http(state, "GET", url + query)[1]["propunere"]["text"] == req["text"]
    state.date_dir = "static"
    assert http(state, "GET", url + query)[0] == 400
    assert http(state, "POST", url, req)[0] == 400
