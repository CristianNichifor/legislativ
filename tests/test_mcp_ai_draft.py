import io
import json
from types import SimpleNamespace

import pytest

from scripts import mcp_ai_draft
from scripts.server import face_handler


def draft_payload(**patch):
    payload = {
        "task": "issue_note",
        "type": "lacuna",
        "title": "Lacună privind normele",
        "context": "Verifică dacă există act subsecvent.",
        "evidence": [
            {
                "label": "Legea 1/2026 art. 3",
                "act_id": "lege-1-2026",
                "locator": "art3",
                "source_url": "https://example.test/lege",
                "quote": "Guvernul aprobă normele metodologice.",
            }
        ],
    }
    payload.update(patch)
    return payload


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


def packet(**patch):
    data = {"server": "desktop-claude", "tool": "claude.chat", "draft": draft_payload()}
    data.update(patch)
    return data


def test_mcp_ai_draft_requires_approval_and_reuses_source_grounded_prompt():
    out = mcp_ai_draft.preview(packet())

    assert out["contract"] == "mcp-ai-evidence-draft-v1"
    assert out["status"] == "requires_user_approval"
    assert out["ai_contract"] == "ai-evidence-draft-v1"
    assert out["mcp"]["status"] == "requires_user_approval"
    assert out["mcp"]["audit_event"]["approved"] is False
    assert out["mcp"]["approval"]["server"] == "desktop-claude"
    assert out["mcp"]["approval"]["data_sha256"] == out["mcp"]["audit_event"]["data_sha256"]
    assert "Guvernul aprobă normele" in out["prompt"]
    assert "nerevizuită" in out["insert_header"]
    assert any("nu a apelat niciun MCP" in item for item in out["limitari"])


@pytest.mark.parametrize(
    "patch",
    [
        {"server": ""},
        {"tool": ""},
        {"draft": draft_payload(evidence=[])},
        {"extra": "x"},
    ],
)
def test_mcp_ai_draft_rejects_ambiguous_or_unsupported_packets(patch):
    with pytest.raises(ValueError):
        mcp_ai_draft.preview(packet(**patch))


def test_mcp_ai_draft_http_is_local_only(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)
    body = packet()

    assert (
        request(
            state, "POST", "/api/dosare/ai-draft/mcp-preview", body, origin="https://evil.test"
        )[0]
        == 403
    )
    code, data = request(state, "POST", "/api/dosare/ai-draft/mcp-preview", body)
    assert code == 200
    assert data["status"] == "requires_user_approval"
