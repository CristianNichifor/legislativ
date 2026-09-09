import io
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from scripts import dosare
from scripts.server import face_handler

ID = "a" * 32
OTHER = "b" * 32


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def create(state, ident=ID):
    return dosare.creeaza(dosare.cale(state), {"id": ident, "titlu": "Cercetare"})


def test_create_read_retry_and_isolation(state):
    path = dosare.cale(state)
    assert dosare.lista(path)["total"] == 0 and not path.exists()
    with pytest.raises(ValueError):
        dosare.citeste(path, ID)
    first = create(state)
    assert create(state) == first == dosare.citeste(path, ID)
    assert not state.initiative.exists()
    with pytest.raises(ValueError):
        dosare.creeaza(path, {"id": ID, "titlu": "Different"})
    assert dosare.lista(path)["total"] == 1
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 4
        assert con.execute("PRAGMA application_id").fetchone()[0] == dosare.APPLICATION_ID


@pytest.mark.parametrize(
    "patch",
    [
        {"id": "../x"},
        {"titlu": " "},
        {"titlu": "x" * 201},
        {"data_analizei": "2026-02-30"},
        {"unexpected": 1},
    ],
)
def test_invalid_create_does_not_initialize(state, patch):
    with pytest.raises(ValueError):
        dosare.creeaza(dosare.cale(state), {"id": ID, "titlu": "A", **patch})
    assert not dosare.cale(state).exists()


def test_foreign_future_schema_and_atomic_migration(state):
    path = dosare.cale(state)

    def interrupt():
        with dosare._open(path, write=True):
            raise RuntimeError("interrupted")

    pytest.raises(RuntimeError, interrupt)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 0
        assert con.execute("SELECT name FROM sqlite_master").fetchall() == []
    create(state)
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA user_version=5")
    for operation in (lambda: create(state), lambda: dosare.lista(path)):
        with pytest.raises(ValueError, match="compatibil"):
            operation()
    other = path.with_name("foreign.db")
    with sqlite3.connect(other) as con:
        con.execute("CREATE TABLE important(value)")
    with pytest.raises(ValueError, match="existent"):
        dosare.creeaza(other, {"id": ID, "titlu": "A"})


def test_runs_preserve_generated_evidence_and_deduplicate(state, monkeypatch):
    create(state)
    report = {
        "gasit": True,
        "acte": {"acte": [{"act_id": "lege-1-2020"}]},
        "contradictii": {"candidati": [{"tip": "test", "a": {"locator": "art1"}}]},
        "limitari": ["Partial"],
        "markdown": "Report",
    }
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    request = {"dosar_id": ID, "filtre": {"emitent": "Parlamentul"}}
    first = dosare.salveaza_rulare(state, request)
    assert dosare.salveaza_rulare(state, request) == first
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: dosare.salveaza_rulare(state, request), range(2))) == [
            first,
            first,
        ]
    assert first["dovezi"]["candidati"][0]["a"]["locator"] == "art1"
    report["markdown"] = "New report"
    second = dosare.salveaza_rulare(state, request)
    assert first["id"] != second["id"]
    path = dosare.cale(state)
    assert dosare.rulari(path, ID, first["id"])["raport"]["markdown"] == "Report"
    assert dosare.rulari(path, ID)["total"] == 2
    restored = path.with_name("restored.db")
    dosare.backup(path, restored)
    assert dosare.rulari(restored, ID, first["id"]) == first
    create(state, OTHER)
    with pytest.raises(ValueError):
        dosare.rulari(path, OTHER, first["id"])
    with pytest.raises(ValueError):
        dosare.salveaza_rulare(state, {**request, "raport": report})
    monkeypatch.setattr(dosare, "MAX_REPORT_BYTES", 2)
    with pytest.raises(ValueError, match="4 MB"):
        dosare.salveaza_rulare(state, request)


def test_concurrent_create_and_backup_restore(state, tmp_path):
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: create(state), range(2)))
    assert rows[0] == rows[1]
    path = dosare.cale(state)
    target = tmp_path / "backup?#.db"
    dosare.backup(path, target)
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert target.stat().st_mode & 0o777 == 0o600
    assert dosare.citeste(target, ID) == rows[0]
    with pytest.raises(FileExistsError):
        dosare.backup(path, target)
    assert dosare.lista(target)["total"] == 1


def test_pagination_and_invalid_run_filters(state, monkeypatch):
    create(state)
    assert dosare.lista(dosare.cale(state), 1)["dosare"] == []
    with pytest.raises(ValueError):
        dosare.lista(dosare.cale(state), -1)

    def unexpected(*args):
        pytest.fail("Invalid input reached the analysis engine")

    monkeypatch.setattr("scripts.servicii._matrice_dosar", unexpected)
    for filters in ({}, {"emitent": False}, {"emitent": "A", "path": "/tmp/x"}):
        with pytest.raises(ValueError):
            dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": filters})


def request(state, method, url, body=None, host="localhost:8123", origin=None, length=None):
    handler = object.__new__(face_handler(state))
    handler.path = url
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {"Host": host, "Content-Length": str(len(raw) if length is None else length)}
    if origin:
        handler.headers["Origin"] = origin
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_http_boundaries(state):
    body = {"id": ID, "titlu": "A"}
    assert request(state, "POST", "/api/dosare", body, origin="https://evil.test")[0] == 403
    assert request(state, "GET", "/api/dosare", host="evil.test:8123")[0] == 403
    assert request(state, "POST", "/api/dosare", body, length=16001)[0] == 413
    assert request(state, "POST", "/api/dosare", body, length=-1)[0] == 400
    assert request(state, "POST", "/api/dosare", body)[0] == 200
    assert request(state, "GET", "/api/dosare")[1]["total"] == 1
    assert request(state, "GET", "/api/dosare?id=" + ID)[1]["titlu"] == "A"
    assert request(state, "GET", "/api/dosare?offset=bad")[0] == 400
    assert request(state, "GET", "/api/dosare/rulari?id=" + ID)[1]["total"] == 0
    assert request(state, "GET", "/api/dosare/revizuiri?id=" + ID)[0] == 400
    assert request(state, "GET", "/api/dosare/dovezi?id=" + ID)[0] == 400
    assert request(state, "GET", "/api/dosare/dovezi", host="evil.test:8123")[0] == 403
    assert request(state, "GET", "/api/dosare/dovezi", origin="https://evil.test")[0] == 403
    for route in ("/api/dosare/verificari", "/api/dosare/coada"):
        assert request(state, "GET", route, host="evil.test:8123")[0] == 403
        assert request(state, "GET", route, origin="https://evil.test")[0] == 403
    assert (
        request(state, "POST", "/api/dosare/verificari", {}, origin="https://evil.test")[0] == 403
    )
    assert request(state, "POST", "/api/dosare/verificari", {}, length=16001)[0] == 413
    assert request(state, "POST", "/api/dosare/verificari", {})[0] == 400
    assert request(state, "GET", "/api/dosare/coada")[1]["total"] == 0
    assert request(state, "POST", "/api/dosare/revizuiri", {}, origin="https://evil.test")[0] == 403
    assert request(state, "POST", "/api/dosare/rulari", {"dosar_id": OTHER, "filtre": {}})[0] == 400
    state.date_dir = "static"
    assert request(state, "GET", "/api/dosare/coada")[0] == 400
    assert request(state, "GET", "/api/dosare/verificari")[0] == 400
    assert request(state, "POST", "/api/dosare/verificari", {})[0] == 400
    assert request(state, "GET", "/api/dosare/dovezi?id=" + ID)[0] == 400
    assert request(state, "POST", "/api/dosare", body)[0] == 400
