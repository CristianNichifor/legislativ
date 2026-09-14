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


def add_manual_source(stare, family, identifier, metadata):
    row = source_registry.executa(
        stare,
        {
            "family": family,
            "identifier": identifier,
            "url": f"https://example.test/{identifier}",
            "label": identifier,
        },
    )
    source_registry.executa(stare, {"action": "sync", "id": row["id"], "metadata": metadata})
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

    assert out["contract"] == "consultation-feed-v1"
    assert out["source_status"] == "ok"
    assert out["total"] == 2
    assert out["families"]["consultare_econsultare"] == 2
    assert out["attention"] == 2
    assert [item["deadline"] for item in out["items"]] == ["2026-10-01", "2026-10-20"]
    assert out["items"][0]["family"] == "consultare_econsultare"
    assert out["items"][0]["family_label"] == "Consultări publice · e-consultare"
    assert out["items"][0]["authority"] == "Ministerul Dezvoltării"
    assert out["items"][0]["documents"] == 2
    assert out["items"][0]["state"] == "changed"
    assert out["items"][0]["can_review"] is True


def test_consultation_feed_includes_government_and_ministry_metadata(monkeypatch, tmp_path):
    stare = state(tmp_path)
    add_source(stare, monkeypatch, "https://e-consultare.gov.ro/consultare/123")
    add_manual_source(
        stare,
        "consultare_guvern",
        "guvern-1",
        {
            "title": "Hotărâre Guvern",
            "authority": "SGG",
            "status": "open",
            "deadline": "10.10.2026",
            "documents": [{"label": "Nota", "url": "https://example.test/nota.pdf"}],
        },
    )
    add_manual_source(
        stare,
        "consultare_minister",
        "minister-1",
        {"title": "Ordin minister", "status": "open"},
    )

    out = econsultare_feed.lista(stare)

    assert out["total"] == 3
    assert out["families"] == {
        "consultare_econsultare": 1,
        "consultare_guvern": 1,
        "consultare_minister": 1,
    }
    by_family = {item["family"]: item for item in out["items"]}
    assert by_family["consultare_guvern"]["family_label"] == "Consultări Guvern"
    assert by_family["consultare_guvern"]["deadline"] == "2026-10-10"
    assert by_family["consultare_guvern"]["documents"] == 1
    assert by_family["consultare_minister"]["family_label"] == "Consultări ministere"
    assert by_family["consultare_minister"]["missing_fields"] == ["authority", "deadline"]
    assert by_family["consultare_minister"]["needs_attention"] is True
    assert "metadata lipsă" in by_family["consultare_minister"]["next_action"]


def test_econsultare_feed_filters_and_reports_missing_registry(monkeypatch, tmp_path):
    stare = state(tmp_path)
    missing = econsultare_feed.lista(stare)
    assert missing["source_status"] == "missing"
    assert missing["families"] == {}
    add_source(stare, monkeypatch, "https://e-consultare.gov.ro/consultare/123")
    add_manual_source(
        stare,
        "consultare_minister",
        "minister-1",
        {"title": "Ordin minister", "authority": "Minister", "status": "closed"},
    )

    assert econsultare_feed.lista(stare, {"status": ["open"]})["total"] == 1
    assert econsultare_feed.lista(stare, {"status": ["closed"]})["total"] == 1
    assert econsultare_feed.lista(stare, {"family": ["consultare_minister"]})["total"] == 1
    with pytest.raises(ValueError, match="Filtru"):
        econsultare_feed.lista(stare, {"status": ["bad"]})
    with pytest.raises(ValueError, match="familie"):
        econsultare_feed.lista(stare, {"family": ["bad"]})
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
    assert result[0][1]["attention"] == 1


def test_econsultare_feed_review_action_clears_attention(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = add_source(stare, monkeypatch, "https://e-consultare.gov.ro/consultare/123")
    before = econsultare_feed.lista(stare)

    source_registry.executa(
        stare,
        {"action": "review", "id": row["id"], "note": "Revizuită din feed-ul e-consultare."},
    )
    after = econsultare_feed.lista(stare)

    assert before["attention"] == 1
    assert before["items"][0]["can_review"] is True
    assert after["attention"] == 0
    assert after["items"][0]["state"] == "unchanged"
    assert after["items"][0]["can_review"] is False
