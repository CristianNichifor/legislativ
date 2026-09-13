from __future__ import annotations

import io
from types import SimpleNamespace

from scripts import acceptance_dashboard
from scripts.server import face_handler


def request(state, url):
    handler = object.__new__(face_handler(state))
    handler.path = url
    handler.rfile = io.BytesIO(b"")
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    handler.do_GET()
    return result[0]


def test_acceptance_dashboard_reports_known_finish_gaps(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)

    out = acceptance_dashboard.raport(state)

    assert out["contract"] == "acceptance-dashboard-v1"
    assert out["status"] == "attention"
    assert out["capability_summary"] == {"ready": 3, "partial": 5, "missing": 0, "total": 8}
    assert {item["key"] for item in out["capabilities"]} >= {"law_as_code", "mcp", "eu_checks"}
    assert {section["key"] for section in out["sections"]} == {
        "local_v1",
        "sources",
        "eu",
        "real_pilot_pack",
        "ai_mcp",
    }
    eu = next(section for section in out["sections"] if section["key"] == "eu")
    assert eu["status"] == "ok"
    assert eu["metrics"]["referenced"] == 8
    assert eu["metrics"]["official_texts_ready"] == 1
    assert "official CELEX text fixture ready" in eu["summary"]
    pack = next(section for section in out["sections"] if section["key"] == "real_pilot_pack")
    assert pack["status"] == "ok"
    assert pack["metrics"] == {
        "required_ready": 5,
        "required_total": 5,
        "reviewable_findings_ready": 1,
    }
    assert any("nu reconstruiește" in item for item in out["limitari"])


def test_acceptance_dashboard_http_endpoint(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)

    code, out = request(state, "/api/acceptance-dashboard")

    assert code == 200
    assert out["contract"] == "acceptance-dashboard-v1"
    assert out["sections"][0]["key"] == "local_v1"
