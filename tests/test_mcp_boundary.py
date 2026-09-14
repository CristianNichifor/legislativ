import io
import json
from types import SimpleNamespace

import pytest

from scripts import mcp_boundary, mcp_runtime
from scripts.server import face_handler


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


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def valid_request(**patch):
    request = {
        "server": "desktop-claude",
        "tool": "claude.chat",
        "capability": "ai_draft",
        "purpose": "Redacteaza o nota juridica din dovezile selectate.",
        "data": "Art. 1: dovada citata.",
    }
    request.update(patch)
    return request


def test_capabilities_describe_local_mock_executor_contract():
    result = mcp_boundary.capabilities()

    assert result["contract"] == "mcp-boundary-v1"
    assert {item["key"] for item in result["capabilities"]} >= {"ai_draft", "github_issue"}
    assert result["execution"]["implemented"] is True
    assert result["execution"]["runtime_contract"] == "mcp-runtime-surface-v1"
    assert result["execution"]["executor_contract"] == "mcp-executor-boundary-v1"
    assert result["execution"]["supported_executor"] == "local-mock/ai.draft"
    assert result["execution"]["external_calls"] is False
    assert result["execution"]["cost_owner"] == "user_account_or_user_key"
    assert result["execution"]["credentials_stored"] is False
    assert result["execution"]["hidden_external_calls"] is False
    assert result["runtime"]["servers_endpoint"] == "/api/mcp/runtime"
    assert result["runtime"]["test_endpoint"] == "/api/mcp/test"
    assert result["limits"]["max_data_chars"] == mcp_boundary.MAX_TEXT
    assert result["limits"]["max_preview_chars"] == mcp_boundary.MAX_PREVIEW
    assert any("chei API" in item for item in result["private_data_excluded"])
    assert any("local-mock" in item for item in result["limitari"])


def test_preview_requires_explicit_payload_and_never_marks_approved():
    result = mcp_boundary.preview(valid_request())

    assert result["status"] == "requires_user_approval"
    assert result["approval"]["server"] == "desktop-claude"
    assert result["approval"]["external_text"] is True
    assert result["approval"]["requires_user_approval"] is True
    assert result["approval"]["approved"] is False
    assert result["approval"]["cost_owner"] == "user_account_or_user_key"
    assert result["approval"]["max_data_chars"] == mcp_boundary.MAX_TEXT
    assert result["approval"]["credentials_stored"] is False
    assert result["approval"]["hidden_external_calls"] is False
    assert any("BYOK" in item for item in result["approval"]["private_data_excluded"])
    assert result["audit_event"]["approved"] is False
    assert result["audit_event"]["contract"] == "mcp-audit-event-v1"
    assert result["cost_estimate"]["server_cost"] == "none"
    assert result["cost_estimate"]["cost_owner"] == "user_account_or_user_key"
    assert result["approval"]["data_preview"] == "Art. 1: dovada citata."
    assert len(result["approval"]["data_sha256"]) == 64


def test_preview_truncates_visible_text_but_hashes_full_payload():
    text = "x" * (mcp_boundary.MAX_PREVIEW + 10)

    result = mcp_boundary.preview(valid_request(data=text))

    assert result["approval"]["data_truncated"] is True
    assert result["approval"]["data_preview"] == "x" * mcp_boundary.MAX_PREVIEW
    assert result["approval"]["data_sha256"] == result["audit_event"]["data_sha256"]


@pytest.mark.parametrize(
    "patch",
    [
        {"server": "bad server"},
        {"tool": "bad/tool"},
        {"capability": "unknown"},
        {"purpose": " "},
        {"data": ""},
        {"extra": "field"},
    ],
)
def test_preview_rejects_ambiguous_or_incomplete_requests(patch):
    with pytest.raises(ValueError):
        mcp_boundary.preview(valid_request(**patch))


def test_non_text_capabilities_can_preview_empty_payload():
    result = mcp_boundary.preview(valid_request(capability="consultation-reminder", data=""))

    assert result["approval"]["capability"] == "consultation_reminder"
    assert result["approval"]["external_text"] is False


def test_runtime_registry_exposes_servers_approval_schema_and_failures():
    result = mcp_runtime.registry()

    assert result["contract"] == "mcp-runtime-surface-v1"
    assert result["servers"][0]["id"] == "local-mock"
    assert result["servers"][0]["tools"][0]["id"] == "ai.draft"
    assert result["servers"][0]["tools"][0]["requires_user_approval"] is True
    assert {tool["id"] for tool in result["servers"][0]["tools"]} >= {
        "ai.draft",
        "document.export",
    }
    assert result["approval"]["payload_preview_required"] is True
    assert result["approval"]["audit_schema"]["selected_evidence_ids"] == "array"
    assert result["approval"]["audit_schema"]["result_hash"] == "sha256_or_null"
    assert {item["code"] for item in result["failure_states"]} >= {
        "mcp_unavailable",
        "approval_required",
        "payload_mismatch",
        "executor_failed",
    }
    assert all(item["external_calls"] is False for item in result["failure_states"])


def test_runtime_test_connection_is_local_mock_only():
    ok = mcp_runtime.test_connection({"server": "local-mock", "tool": "ai.draft"})
    blocked = mcp_runtime.test_connection({"server": "desktop-claude", "tool": "claude.chat"})

    assert ok["contract"] == "mcp-runtime-test-v1"
    assert ok["available"] is True
    assert ok["requires_user_approval"] is True
    assert ok["preview_required_before_execute"] is True
    assert ok["hidden_external_calls"] is False
    assert blocked["available"] is False
    assert blocked["failure"]["contract"] == "mcp-runtime-failure-v1"
    assert blocked["failure"]["code"] == "unknown_server"


def test_mcp_http_boundary_is_local_only(state):
    assert request(state, "GET", "/api/mcp/capabilities", host="evil.test:8123")[0] == 403
    assert request(state, "GET", "/api/mcp/runtime")[1]["contract"] == "mcp-runtime-surface-v1"
    code, tested = request(
        state, "POST", "/api/mcp/test", {"server": "local-mock", "tool": "ai.draft"}
    )
    assert code == 200
    assert tested["available"] is True
    assert (
        request(state, "POST", "/api/mcp/preview", valid_request(), origin="https://evil.test")[0]
        == 403
    )
    code, data = request(state, "POST", "/api/mcp/preview", valid_request())
    assert code == 200
    assert data["status"] == "requires_user_approval"
    assert request(state, "POST", "/api/mcp/preview", valid_request(), length=16001)[0] == 413
