from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from scripts import dosare, mcp_export
from scripts.server import face_handler

DOSSIER_ID = "c" * 32


def export_payload(**patch):
    payload = {
        "title": "Notă achiziții",
        "type": "contradictie",
        "act_id": "lege-10-2026",
        "locator": "art1",
        "source_url": "https://example.test/lege10",
        "source_hash": "d" * 64,
        "evidence_quote": "Pragurile se aplică diferit.",
        "reasoning": "Există risc de contradicție între praguri.",
    }
    payload.update(patch)
    return payload


def packet(**patch):
    data = {"server": "local-mock", "tool": "document.export", "export": export_payload()}
    data.update(patch)
    return data


def request(state, method, url, body=None, host="localhost:8123", origin=None):
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


@pytest.fixture
def state(tmp_path):
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
    return SimpleNamespace(
        initiative=tmp_path / "initiative.db",
        date_dir=None,
        dosare_db=path,
    )


def approved_request():
    plan = mcp_export.preview(packet())
    return {
        "id": "e" * 32,
        "dosar_id": DOSSIER_ID,
        "server": "local-mock",
        "tool": "document.export",
        "export": export_payload(),
        "approved": True,
        "approved_data_sha256": plan["mcp"]["approval"]["data_sha256"],
    }


def test_export_preview_requires_approval_and_hashes_exact_markdown():
    out = mcp_export.preview(packet())

    assert out["contract"] == "mcp-dossier-export-v1"
    assert out["status"] == "requires_user_approval"
    assert out["approval_state"] == "preview_created"
    assert out["approval"]["required"] is True
    assert out["approval"]["mcp_executes_now"] is False
    assert out["mcp"]["approval"]["capability"] == "document_export"
    assert out["mcp"]["approval"]["requires_user_approval"] is True
    assert out["mcp"]["approval"]["hidden_external_calls"] is False
    assert out["mcp"]["audit_event"]["payload_hash"] == out["mcp"]["approval"]["data_sha256"]
    assert out["mcp"]["audit_event"]["result_hash"] is None
    assert out["mcp"]["audit_event"]["user_action"] == "previewed"
    assert out["mcp"]["audit_event"]["selected_evidence_ids"] == ["lege-10-2026:art1"]
    assert out["selected_evidence_ids"] == ["lege-10-2026:art1"]
    assert "Pragurile se aplică diferit" in out["markdown"]
    assert out["markdown_sha256"]


@pytest.mark.parametrize(
    "patch",
    [
        {"server": ""},
        {"tool": ""},
        {"export": export_payload(title="")},
        {"extra": "x"},
    ],
)
def test_export_preview_rejects_ambiguous_packets(patch):
    with pytest.raises(ValueError):
        mcp_export.preview(packet(**patch))


def test_export_execute_requires_local_origin_approval_and_stores_audit(state):
    assert (
        request(
            state,
            "POST",
            "/api/dosare/mcp-export-execute",
            approved_request(),
            origin="https://evil.test",
        )[0]
        == 403
    )

    code, preview = request(state, "POST", "/api/dosare/mcp-export-preview", packet())
    assert code == 200
    assert preview["status"] == "requires_user_approval"

    code, executed = request(state, "POST", "/api/dosare/mcp-export-execute", approved_request())
    assert code == 200
    assert executed["contract"] == "mcp-executor-boundary-v1"
    assert executed["workflow"] == "document_export"
    assert executed["output_status"] == "export_unreviewed"
    assert executed["audit_event"]["event"] == "mcp_document_export_executed"
    assert executed["audit_event"]["server"] == "local-mock"
    assert executed["audit_event"]["tool"] == "document.export"
    assert executed["audit_event"]["payload_hash"] == executed["approved_data_sha256"]
    assert executed["audit_event"]["selected_evidence_ids"] == ["lege-10-2026:art1"]
    assert executed["audit_event"]["approval_state"] == "approved_and_executed"
    assert executed["approval_state"] == "approved_and_executed"
    assert executed["external_calls"] is False
    assert executed["credentials_stored"] is False
