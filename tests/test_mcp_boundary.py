import io
import json
from types import SimpleNamespace

import pytest

from scripts import mcp_boundary
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


def test_capabilities_describe_non_executing_contract():
    result = mcp_boundary.capabilities()

    assert result["contract"] == "mcp-boundary-v1"
    assert {item["key"] for item in result["capabilities"]} >= {"ai_draft", "github_issue"}
    assert any("nu execută" in item for item in result["limitari"])


def test_preview_requires_explicit_payload_and_never_marks_approved():
    result = mcp_boundary.preview(valid_request())

    assert result["status"] == "requires_user_approval"
    assert result["approval"]["server"] == "desktop-claude"
    assert result["approval"]["external_text"] is True
    assert result["audit_event"]["approved"] is False
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


def test_mcp_http_boundary_is_local_only(state):
    assert request(state, "GET", "/api/mcp/capabilities", host="evil.test:8123")[0] == 403
    assert (
        request(state, "POST", "/api/mcp/preview", valid_request(), origin="https://evil.test")[0]
        == 403
    )
    code, data = request(state, "POST", "/api/mcp/preview", valid_request())
    assert code == 200
    assert data["status"] == "requires_user_approval"
    assert request(state, "POST", "/api/mcp/preview", valid_request(), length=16001)[0] == 413
