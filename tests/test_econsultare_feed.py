import io
from types import SimpleNamespace

import pytest

from scripts import achizitii_econsultare as ec
from scripts import econsultare_feed, source_registry
from scripts.server import face_handler
from tests.test_achizitii_econsultare import HTML


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def add_source(stare, monkeypatch, url, html=HTML):
    row = source_registry.executa(
        stare,
        {"family": "consultare_econsultare", "url": url, "label": "Consultare publică"},
    )
    monkeypatch.setattr(ec, "descarca", lambda source_url: (html, 200))
    source_registry.executa(stare, {"action": "sync", "id": row["id"]})
    return row


def test_econsultare_feed_lists_registered_sources_by_deadline(monkeypatch, tmp_path):
    stare = state(tmp_path)
    add_source(
        stare,
        monkeypatch,
        "https://e-consultare.gov.ro/consultare/late",
        HTML.replace(b"15.10.2026", b"20.10.2026"),
    )
    add_source(
        stare,
        monkeypatch,
        "https://e-consultare.gov.ro/consultare/early",
        HTML.replace(b"15.10.2026", b"01.10.2026"),
    )

    out = econsultare_feed.lista(stare)

    assert out["contract"] == "econsultare-feed-v1"
    assert out["source_status"] == "ok"
    assert out["total"] == 2
    assert [item["deadline"] for item in out["items"]] == ["2026-10-01", "2026-10-20"]
    assert out["items"][0]["authority"] == "Ministerul Dezvoltării"
    assert out["items"][0]["documents"] == 2
    assert out["items"][0]["state"] == "changed"


def test_econsultare_feed_filters_and_reports_missing_registry(monkeypatch, tmp_path):
    stare = state(tmp_path)
    assert econsultare_feed.lista(stare)["source_status"] == "missing"
    add_source(stare, monkeypatch, "https://e-consultare.gov.ro/consultare/123")

    assert econsultare_feed.lista(stare, {"status": ["open"]})["total"] == 1
    assert econsultare_feed.lista(stare, {"status": ["closed"]})["total"] == 0
    with pytest.raises(ValueError, match="Filtru"):
        econsultare_feed.lista(stare, {"status": ["bad"]})
    with pytest.raises(ValueError, match="Limită"):
        econsultare_feed.lista(stare, {"limit": ["0"]})


def test_econsultare_feed_http_endpoint(monkeypatch, tmp_path):
    stare = state(tmp_path)
    add_source(stare, monkeypatch, "https://e-consultare.gov.ro/consultare/123")
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/econsultare-feed?status=open"
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_GET()

    assert result[0][0] == 200
    assert result[0][1]["items"][0]["status"] == "open"
