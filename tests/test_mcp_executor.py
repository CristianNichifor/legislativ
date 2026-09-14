from __future__ import annotations

import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import dosare, mcp_ai_draft, mcp_executor
from scripts.server import face_handler

DOSSIER_ID = "a" * 32
AUDIT_ID = "b" * 32


def draft_request():
    return {
        "task": "issue_note",
        "type": "lacuna",
        "title": "Achiziții publice",
        "context": "Folosește numai dovezile selectate.",
        "evidence": [
            {
                "label": "Legea 10/2026 art. 1",
                "act_id": "lege-10-2026",
                "locator": "art1",
                "source_url": "https://example.test/lege10",
                "source_hash": "c" * 64,
                "quote": "achiziții publice și praguri valorice",
            }
        ],
    }


@pytest.fixture
def dossier_db(tmp_path):
    path = tmp_path / "dosare.db"
    dosare.creeaza(
        path,
        {
            "id": DOSSIER_ID,
            "titlu": "Dosar achiziții",
            "intrebare": "",
            "domeniu": "achiziții",
            "data_analizei": None,
        },
    )
    return path


def approved_request(**patch):
    draft = draft_request()
    plan = mcp_ai_draft.preview({"server": "local-mock", "tool": "ai.draft", "draft": draft})
    request = {
        "id": AUDIT_ID,
        "dosar_id": DOSSIER_ID,
        "server": "local-mock",
        "tool": "ai.draft",
        "draft": draft,
        "approved": True,
        "approved_data_sha256": plan["mcp"]["approval"]["data_sha256"],
    }
    request.update(patch)
    return request


def http_request(state, method, url, body=None, host="localhost:8123", origin=None):
    handler = object.__new__(face_handler(state))
    handler.path = url
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {"Host": host, "Content-Length": str(len(raw))}
    if origin:
        handler.headers["Origin"] = origin
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_config_probe_is_local_mock_only():
    out = mcp_executor.test_config({"server": "local-mock", "tool": "ai.draft"})

    assert out["contract"] == "mcp-executor-config-test-v1"
    assert out["available"] is True
    assert out["external_calls"] is False
    assert out["credentials_stored"] is False
    assert out["app_paid_ai"] is False

    blocked = mcp_executor.test_config({"server": "desktop-claude", "tool": "claude.chat"})
    assert blocked["available"] is False
    assert blocked["mode"] == "unsupported"


def test_execute_requires_exact_user_approved_payload_hash(dossier_db):
    with pytest.raises(ValueError, match="aprobare explicită"):
        mcp_executor.execute(dossier_db, approved_request(approved=False))

    with pytest.raises(ValueError, match="nu mai corespunde"):
        mcp_executor.execute(dossier_db, approved_request(approved_data_sha256="0" * 64))


def test_execute_runs_local_mock_and_stores_append_only_audit(dossier_db):
    request = approved_request()
    out = mcp_executor.execute(dossier_db, request)
    retry = mcp_executor.execute(dossier_db, request)

    assert out == retry
    assert out["contract"] == "mcp-executor-boundary-v1"
    assert out["id"] == AUDIT_ID
    assert out["dosar_id"] == DOSSIER_ID
    assert out["server"] == "local-mock"
    assert out["tool"] == "ai.draft"
    assert out["output_status"] == "draft_unreviewed"
    assert out["external_calls"] is False
    assert out["hidden_external_calls"] is False
    assert out["credentials_stored"] is False
    assert out["app_paid_ai"] is False
    assert out["selected_evidence_ids"] == ["lege-10-2026:art1"]
    assert out["user_action"] == "approved_and_executed"
    assert "Ciornă MCP locală" in out["draft_text"]
    assert "Nu verdict juridic" in out["draft_text"]
    assert out["audit_event"]["approved"] is True
    assert out["audit_event"]["payload_hash"] == out["approved_data_sha256"]
    assert out["audit_event"]["selected_evidence_ids"] == ["lege-10-2026:art1"]
    assert out["audit_event"]["result_hash"] == out["result_sha256"]
    assert out["audit_event"]["user_action"] == "approved_and_executed"
    assert len(out["audit_event"]["result_sha256"]) == 64

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        dosare._open(dossier_db, write=True) as con,
    ):
        con.execute("UPDATE mcp_audit_events SET status='reviewed' WHERE id=?", (AUDIT_ID,))


def test_execute_rejects_credentials_and_unknown_servers(dossier_db):
    with pytest.raises(ValueError, match="invalidă"):
        mcp_executor.execute(dossier_db, {**approved_request(), "api_key": "secret"})

    with pytest.raises(ValueError, match="local-mock"):
        mcp_executor.execute(
            dossier_db,
            approved_request(server="desktop-claude", tool="claude.chat"),
        )


def test_http_route_executes_only_for_local_origin(dossier_db):
    state = SimpleNamespace(initiative=dossier_db.with_suffix(".initiative.db"), date_dir=None)
    state.dosare_db = dossier_db

    assert (
        http_request(
            state,
            "POST",
            "/api/dosare/ai-draft/mcp-execute",
            approved_request(),
            origin="https://evil.test",
        )[0]
        == 403
    )

    code, data = http_request(state, "POST", "/api/dosare/ai-draft/mcp-execute", approved_request())
    assert code == 200
    assert data["contract"] == "mcp-executor-boundary-v1"
    assert data["audit_event"]["external_calls"] is False
