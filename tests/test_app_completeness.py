from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import app_completeness, source_registry
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


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(
        corpus=tmp_path / "corpus.db",
        initiative=tmp_path / "initiative.db",
        graf=tmp_path / "graf.db",
        eu=tmp_path / "eu.db",
        date_dir=None,
    )


def test_app_completeness_reports_all_major_user_visible_capabilities(state):
    out = app_completeness.report(state)

    assert out["contract"] == "app-completeness-gate-v1"
    assert out["status"] == "blocked"
    assert out["completion_claim_allowed"] is False
    assert {item["key"] for item in out["capabilities"]} == set(
        app_completeness.REQUIRED_CAPABILITIES
    )
    assert out["summary"]["total"] == len(app_completeness.REQUIRED_CAPABILITIES)
    assert out["summary"]["partial"] >= 1
    assert out["summary"]["ready"] >= 1
    assert out["blocking_capabilities"]
    assert "public_source_data_availability" in {
        item["key"] for item in out["blocking_capabilities"]
    }
    assert out["visible_in"] == {
        "docs": "docs/APP_COMPLETENESS.md",
        "ui": "/api/app-completeness via Stadiu finalizare",
        "cli": "python -m scripts.app_completeness --require-complete",
    }


def test_app_completeness_fails_loudly_when_any_capability_is_partial(state):
    out = app_completeness.report(state)

    with pytest.raises(app_completeness.AppCompletenessError, match="public_source"):
        app_completeness.assert_complete(out)


def test_app_completeness_require_complete_cli_exits_nonzero():
    result = subprocess.run(
        ["python", "-m", "scripts.app_completeness", "--require-complete"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = json.loads(result.stdout)

    assert result.returncode == 2
    assert out["status"] == "blocked"
    assert out["blocking_capabilities"]
    assert out["completion_claim_allowed"] is False
    assert out["source_status"]["missing_required"] == 0
    assert out["source_status"]["unsynced_required"] == 12


def test_app_completeness_data_home_without_sync_reports_missing_sources(tmp_path, capsys):
    result = app_completeness.main(["--data-home", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)

    assert result == 0
    assert out["status"] == "blocked"
    assert out["source_status"]["missing_required"] == 12
    assert out["source_status"]["unsynced_required"] == 0
    assert not (tmp_path / "private" / "empty" / "initiative.sources.db").exists()


def test_app_completeness_data_home_sync_anchors_can_close_gate(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        source_registry,
        "_fetch_official_anchor",
        lambda url: {
            "http_status": 200,
            "content_hash": source_registry._stable_hash({"url": url}),
            "title": "Official source",
            "content_type": "text/html",
            "bytes": 64,
            "truncated": False,
            "error": "",
        },
    )

    result = app_completeness.main(
        ["--data-home", str(tmp_path), "--sync-source-anchors", "--require-complete"]
    )
    out = json.loads(capsys.readouterr().out)

    assert result == 0
    assert out["status"] == "ready"
    assert out["completion_claim_allowed"] is True
    assert out["source_status"]["missing_required"] == 0
    assert out["source_status"]["unsynced_required"] == 0
    assert out["source_anchor_sync"]["counts"] == {"unchanged": 14}
    lifecycle = next(item for item in out["capabilities"] if item["key"] == "lifecycle_tracking")
    assert lifecycle["state"] == "ready"
    assert lifecycle["blockers"] == []
    assert lifecycle["next_action"] == ""


def test_app_completeness_default_report_bootstraps_official_source_anchors():
    out = app_completeness.report()

    assert out["source_status"]["missing_required"] == 0
    assert out["source_status"]["unsynced_required"] == 12
    assert any(blocker["kind"] == "source_unsynced" for blocker in out["source_status"]["blockers"])


def test_app_completeness_http_endpoint(state):
    code, out = request(state, "/api/app-completeness")

    assert code == 200
    assert out["contract"] == "app-completeness-gate-v1"
    assert out["status"] == "blocked"
    assert out["completion_claim_allowed"] is False


def test_app_completeness_reports_unsynced_bootstrapped_sources(state):
    source_registry.executa(state, {"action": "bootstrap"})

    out = app_completeness.report(state)

    source_status = out["source_status"]
    assert source_status["missing_required"] == 0
    assert source_status["unsynced_required"] == 12
    assert source_status["attention_sources"] == 0
    source_capability = next(
        item for item in out["capabilities"] if item["key"] == "public_source_data_availability"
    )
    assert source_capability["state"] == "partial"
    assert "no_required_family_unsynced" in source_capability["failed_checks"]
    assert out["completion_claim_allowed"] is False


def test_app_completeness_is_visible_in_ui():
    html = (Path(__file__).parents[1] / "app/index.html").read_text(encoding="utf-8")

    assert "Gate produs" in html
    assert "app-completeness-gate-v1" in html
    assert "fetch('/api/app-completeness')" in html
    assert "completion_claim_allowed" in html
    assert "source-registry-bootstrap" in html
    assert "acceptance-source-sync" in html
    assert "Verifică sursele oficiale de bază" in html
    assert "sync_bootstrap" in html
    assert "bindAcceptanceDashboardActions" in html
