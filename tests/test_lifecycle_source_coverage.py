from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from scripts import lifecycle_source_coverage, source_registry, tracker_events
from scripts.server import face_handler


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def test_project_source_coverage_groups_required_public_sources(tmp_path):
    stare = state(tmp_path)
    project_id = "PL-x 10/2026"
    source = source_registry.executa(
        stare,
        {
            "family": "camera",
            "identifier": project_id,
            "url": "https://www.cdep.ro/proiect10",
            "label": "Proiect urmărit",
        },
    )
    source_registry.executa(stare, {"action": "queue", "id": source["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": source["id"],
            "state": "fetched",
            "content_hash": "a" * 64,
            "parser_version": "test",
        },
    )
    tracker_events.adauga(
        stare,
        {
            "event_type": "public_consultation_opened",
            "project_id": project_id,
            "source_family": "consultare_guvern",
            "source_url": "https://sgg.gov.ro/1/transparenta-decizionala/proiect10/",
            "occurred_at": "2026-09-10T10:00:00+00:00",
            "title": "Consultare Guvern",
            "payload": {"authority": "Guvernul României"},
            "content_hash": "b" * 64,
        },
    )

    out = lifecycle_source_coverage.build(stare, {"project_id": [project_id]})

    assert out["contract"] == "project-source-coverage-v1"
    assert out["project_id"] == project_id
    by_group = {group["key"]: group for group in out["groups"]}
    assert by_group["parliament"]["state"] == "present"
    assert by_group["consultations"]["state"] == "present"
    assert by_group["consultations"]["freshness_state"] == "partial"
    assert by_group["eu"]["state"] == "missing"
    assert by_group["eu"]["freshness"]["missing"] == ["ue_cellar"]
    assert by_group["monitor"]["state"] == "missing"
    assert out["summary"]["events"] == 1
    assert out["summary"]["sources"] == 1
    assert out["summary"]["freshness_states"]["partial"] >= 1
    assert out["status"] == "missing"


def test_project_source_coverage_marks_attention_sources_for_review(tmp_path):
    stare = state(tmp_path)
    project_id = "PL-x 11/2026"
    source = source_registry.executa(stare, {"family": "camera", "identifier": project_id})
    source_registry.executa(stare, {"action": "queue", "id": source["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": source["id"],
            "state": "fetched",
            "content_hash": "a" * 64,
            "parser_version": "test",
        },
    )
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": source["id"],
            "state": "changed",
            "content_hash": "b" * 64,
            "parser_version": "test",
        },
    )

    out = lifecycle_source_coverage.build(stare, {"project_id": [project_id]})

    parliament = next(group for group in out["groups"] if group["key"] == "parliament")
    assert parliament["state"] == "needs_review"
    assert parliament["freshness_state"] == "needs_review"
    assert out["status"] == "needs_review"
    assert "Revizuiește sursele schimbate" in " ".join(out["next_actions"])


def test_project_source_coverage_validates_project_id(tmp_path):
    with pytest.raises(ValueError, match="Identificator"):
        lifecycle_source_coverage.build(state(tmp_path), {"project_id": ["<bad>"]})


def test_http_project_source_coverage_endpoint(tmp_path):
    stare = state(tmp_path)
    tracker_events.adauga(
        stare,
        {
            "event_type": "published_in_monitor",
            "project_id": "PL-x 12/2026",
            "source_family": "monitorul_oficial_pi",
            "source_url": "https://monitoruloficial.ro/",
            "occurred_at": "2026-09-10T10:00:00+00:00",
            "title": "Publicat în Monitorul Oficial",
            "payload": {},
            "content_hash": "c" * 64,
        },
    )
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/project-source-coverage?project_id=PL-x%2012/2026"
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_GET()

    code, data = result[0]
    assert code == 200
    assert data["contract"] == "project-source-coverage-v1"
    assert data["summary"]["events"] == 1
