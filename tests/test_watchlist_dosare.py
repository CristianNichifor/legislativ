import io
import json
from types import SimpleNamespace

import pytest

from scripts import dosare, source_registry, watchlist_dosare
from scripts.server import face_handler

ID = "a" * 32


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def create(state):
    return dosare.creeaza(dosare.cale(state), {"id": ID, "titlu": "Achiziții"})


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


def test_watchlist_tracks_private_dossier_items_and_registry_attention(state):
    create(state)
    row = watchlist_dosare.adauga(
        dosare.cale(state),
        {
            "dosar_id": ID,
            "tip": "project",
            "valoare": "PL-x 1/2026",
            "eticheta": "Proiect achiziții",
        },
    )
    assert row["tip_label"] == "Proiect legislativ"

    source = source_registry.descopera(
        state,
        {
            "family": "parlament",
            "identifier": "PL-x 1/2026",
            "url": "https://example.test/plx",
            "label": "Proiect achiziții",
        },
    )
    source_registry.pune_in_coada(state, source["id"])
    source_registry.inregistreaza(
        state,
        {
            "id": source["id"],
            "state": "fetched",
            "content_hash": "b" * 64,
            "parser_version": "test.v1",
        },
    )
    source_registry.inregistreaza(
        state,
        {
            "id": source["id"],
            "state": "changed",
            "content_hash": "c" * 64,
            "parser_version": "test.v1",
            "note": "text schimbat",
        },
    )

    feed = watchlist_dosare.feed(state, dosare.cale(state), ID)
    assert feed["attention"] == 1
    assert feed["items"][0]["source_state"] == "changed"
    assert feed["items"][0]["source"]["last_hash"] == "c" * 64
    assert feed["items"][0]["actiuni"]["rerun_analysis"] is True
    assert feed["items"][0]["needs_attention"] is True


def test_watchlist_review_delete_and_unregistered_items(state):
    create(state)
    item = watchlist_dosare.adauga(
        dosare.cale(state), {"dosar_id": ID, "tip": "keyword", "valoare": "concesiuni"}
    )
    feed = watchlist_dosare.feed(state, dosare.cale(state), ID)
    assert feed["items"][0]["source_state"] == "not_registered"
    assert feed["items"][0]["needs_attention"] is True

    reviewed = watchlist_dosare.marcheaza_revizuit(
        dosare.cale(state), {"id": item["id"], "dosar_id": ID, "nota": "verificat manual"}
    )
    assert reviewed["revizuit"] is True
    assert reviewed["nota_revizie"] == "verificat manual"

    deleted = watchlist_dosare.sterge(dosare.cale(state), {"id": item["id"], "dosar_id": ID})
    assert deleted == {"id": item["id"], "sters": True}
    assert watchlist_dosare.lista(dosare.cale(state), ID)["total"] == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"tip": "bad"},
        {"valoare": ""},
        {"dosar_id": "bad"},
        {"extra": "x"},
    ],
)
def test_watchlist_rejects_invalid_records(state, patch):
    create(state)
    body = {"dosar_id": ID, "tip": "act", "valoare": "lege-98-2016", **patch}
    with pytest.raises(ValueError):
        watchlist_dosare.adauga(dosare.cale(state), body)


def test_watchlist_http_boundaries(state):
    create(state)
    body = {
        "action": "add",
        "dosar_id": ID,
        "tip": "celex",
        "valoare": "32014L0024",
        "eticheta": "Directiva achiziții",
    }
    assert (
        request(state, "POST", "/api/dosare/watchlist", body, origin="https://evil.test")[0] == 403
    )
    assert request(state, "POST", "/api/dosare/watchlist", body, length=16001)[0] == 413
    assert request(state, "POST", "/api/dosare/watchlist", body)[0] == 200
    code, feed = request(state, "GET", "/api/dosare/watchlist?id=" + ID)
    assert code == 200
    assert feed["total"] == 1
    assert feed["items"][0]["valoare"] == "32014L0024"
