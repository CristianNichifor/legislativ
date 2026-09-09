import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import achizitii_proiecte as ap
from scripts import depozit
from scripts import documente_proiecte as dp
from scripts.server import face_handler

URL = "https://www.cdep.ro/proiecte/a.docx"


@pytest.fixture
def state(tmp_path, monkeypatch):
    state = SimpleNamespace(initiative=tmp_path / "initiative?#.db")
    with depozit.deschide(state.initiative) as con:
        con.executemany(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,citit_la) "
            "VALUES (?,2,'123',?,'2026-01-01')",
            [(f"plx-{i:03}", "Proiect " + str(i)) for i in range(30)],
        )
        con.commit()
    monkeypatch.setattr(dp, "extrage", lambda _: {"status": "extras", "text": "Retained text"})
    monkeypatch.setattr(
        dp,
        "descarca",
        lambda url, *args: f'<a href="{URL}">Document</a>'.encode() if "idp=" in url else b"bytes",
    )
    return state


def action(state, operation, **kwargs):
    return ap.executa(state, {"plx": "plx-000", "operatie": operation, **kwargs})


def test_local_browsing_paginates_and_does_not_fetch_or_write(state, monkeypatch):
    def unexpected(*args):
        raise AssertionError("Network used")

    monkeypatch.setattr(dp, "descarca", unexpected)
    before = state.initiative.read_bytes()
    first = ap.lista(state)
    assert len(first["initiative"]) == 25 and first["mai_multe"]
    second = ap.lista(state, offset=25)
    assert len(second["initiative"]) == 5 and not second["mai_multe"]
    assert ap.lista(state, "%")["initiative"] == []
    assert ap.lista(state, "plx-007")["initiative"][0]["plx_id"] == "plx-007"
    detail = ap.detaliu(state, "plx-000")
    assert detail["stare"] == "metadate" and detail["limba"] is None
    assert detail["actualitate"] == "necunoscuta" and detail["versiuni"] == []
    assert state.initiative.read_bytes() == before
    assert not dp.cale_store(state).exists()


def test_discovery_only_store_remains_compatible_with_existing_importer(state):
    action(state, "descopera")
    assert dp.versiuni(state, "plx-000") == []
    result = action(state, "importa", url=URL)
    assert result["text"] == "Retained text"
    assert len(dp.versiuni(state, "plx-000")) == 1
    detail = ap.detaliu(state, "plx-000")
    assert detail["versiuni_total"] == 1
    assert len(detail["incercari"]) == 2
    assert all(r["stare"] == "ok" and r["reusit_la"] for r in detail["incercari"])


def test_failure_preserves_previous_success_and_immutable_import_retry(state, monkeypatch):
    first = action(state, "importa", url=URL)
    before = ap.detaliu(state, "plx-000")
    successful = before["incercari"][0]["reusit_la"]
    download = dp.descarca

    def offline(*args):
        raise OSError("secret local path /private/file")

    monkeypatch.setattr(dp, "descarca", offline)
    with pytest.raises(ValueError, match="Sursa") as error:
        action(state, "importa", url=URL)
    assert "private" not in str(error.value)
    failed = ap.detaliu(state, "plx-000")
    assert failed["ultima_incercare"]["stare"] == "eroare"
    assert failed["ultima_incercare"]["reusit_la"] == successful
    assert dp.citeste(state, "plx-000", first["id"]) == first
    monkeypatch.setattr(dp, "descarca", download)
    assert action(state, "importa", url=URL) == first
    retried = ap.detaliu(state, "plx-000")
    assert retried["versiuni_total"] == 1 and len(retried["incercari"]) == 1
    assert retried["ultima_incercare"]["stare"] == "ok"


def test_update_failure_can_retry_exact_version_and_keep_old_text(state, monkeypatch):
    first = action(state, "importa", url=URL)
    unchanged = action(state, "actualizeaza", versiune=first["id"])
    assert not unchanged["schimbat"]
    download = dp.descarca
    monkeypatch.setattr(
        dp, "descarca", lambda url, *args: download(url) if "idp=" in url else b"new"
    )
    changed = action(state, "actualizeaza", versiune=first["id"])
    assert changed["schimbat"] and changed["versiune"]["id"] != first["id"]
    assert ap.detaliu(state, "plx-000")["ultima_incercare"]["versiune"] == first["id"]
    assert dp.citeste(state, "plx-000", first["id"]) == first


def test_discovery_offline_history_is_not_recorded_as_success(state, monkeypatch):
    action(state, "importa", url=URL)
    monkeypatch.setattr(dp, "descarca", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ValueError):
        action(state, "descopera")
    detail = ap.detaliu(state, "plx-000")
    assert detail["versiuni_total"] == 1
    assert detail["ultima_incercare"]["operatie"] == "descopera"
    assert detail["ultima_incercare"]["reusit_la"] is None


def test_missing_and_corrupt_stores_are_not_reported_as_zero(state):
    dp.cale_store(state).write_bytes(b"broken sqlite")
    row = ap.lista(state)["initiative"][0]
    assert row["stare"] == "indisponibil" and row["versiuni_total"] is None
    with pytest.raises(sqlite3.DatabaseError):
        ap.detaliu(state, "plx-000")
    state.initiative.unlink()
    with pytest.raises(sqlite3.Error):
        ap.lista(state)
    assert not state.initiative.exists()


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"operatie": []}, {"operatie": {}}, {"operatie": "delete"}]
)
def test_reject_invalid_actions(state, payload):
    with pytest.raises(ValueError):
        ap.executa(state, payload)
    assert not dp.cale_store(state).exists()


def test_reject_url_and_foreign_version_before_attempt_record(state):
    with pytest.raises(ValueError):
        action(state, "importa", url="https://evil.test/a.pdf")
    assert not dp.cale_store(state).exists()
    first = action(state, "importa", url=URL)
    with pytest.raises(ValueError):
        ap.executa(state, {"plx": "plx-001", "operatie": "actualizeaza", "versiune": first["id"]})
    assert ap.detaliu(state, "plx-001")["incercari"] == []


def test_extraction_states_and_attempts_are_distinct(state, monkeypatch):
    monkeypatch.setattr(dp, "extrage", lambda _: {"status": "ocr_necesar", "text": ""})
    action(state, "importa", url=URL)
    d = ap.detaliu(state, "plx-000")
    assert d["versiuni"][0]["status"] == "ocr_necesar"
    assert d["incercari"][0]["stare"] == "ok"


def test_reader_does_not_modify_legacy_store_and_bounds_history(state):
    first = dp.importa(state, "plx-000", URL)
    with sqlite3.connect(dp.cale_store(state)) as con:
        con.executemany(
            "INSERT INTO documente SELECT ?,plx_id,url,label,sha256,preluat_la,status,text,octeti "
            "FROM documente WHERE id=?",
            [(f"{i:064}", first["id"]) for i in range(101)],
        )
    before = dp.cale_store(state).read_bytes()
    d = ap.detaliu(state, "plx-000")
    assert d["versiuni_total"] == 102 and len(d["versiuni"]) == 100
    assert d["versiuni_trunchiate"] and not d["incercari"]
    assert dp.cale_store(state).read_bytes() == before


def test_recording_failure_does_not_report_successful_import_as_failed(state, monkeypatch):
    monkeypatch.setattr(
        ap, "_record", lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError())
    )
    result = action(state, "importa", url=URL)
    assert result["avertisment_achizitie"]
    assert dp.citeste(state, "plx-000", result["id"])["text"] == result["text"]


def request(state, method, query="", body=None, host="localhost:8123", origin=None, length=None):
    handler = object.__new__(face_handler(state))
    handler.path = "/api/surse-proiecte" + query
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {
        "Host": host,
        "Content-Length": str(length if length is not None else len(raw)),
    }
    if origin:
        handler.headers["Origin"] = origin
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_http_validation_locality_and_generic_errors(state):
    for method in ("GET", "POST"):
        assert request(state, method, origin="https://evil.test")[0] == 403
        assert request(state, method, host="evil.test:8123")[0] == 403
    assert request(state, "POST", length=16001)[0] == 413
    assert request(state, "POST", body={"operatie": []})[0] == 400
    for q in ("?offset=bad", "?offset=-1", "?q=" + "x" * 201):
        assert request(state, "GET", q)[0] == 400
    assert request(state, "GET")[0] == 200
    assert request(state, "GET", "?plx=plx-000")[1]["stare"] == "metadate"
    imported = request(state, "POST", body={"plx": "plx-000", "operatie": "importa", "url": URL})
    assert imported[0] == 200
    assert request(state, "GET", "?plx=plx-000&versiune=" + imported[1]["id"])[1]["text"]
    assert request(state, "GET", "?plx=plx-001&versiune=" + imported[1]["id"])[0] == 400
    dp.cale_store(state).write_bytes(b"broken")
    code, error = request(state, "GET", "?plx=plx-000")
    assert code == 503 and "error" in error and str(state.initiative) not in error["error"]


def test_http_responses_are_not_cached(state):
    handler = object.__new__(face_handler(state))
    handler.path = "/api/surse-proiecte?plx=plx-000"
    headers = {}
    handler.send_header = lambda k, v: headers.update({k: v})
    handler.send_response = lambda *args: None
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()
    handler._json({})
    assert headers["Cache-Control"] == "no-store"
