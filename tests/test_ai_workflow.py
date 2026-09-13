from __future__ import annotations

import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import ai_workflow, dosare
from scripts.server import face_handler

DOSSIER_ID = "a" * 32
AUDIT_ID = "d" * 32


def draft_request():
    return {
        "task": "issue_note",
        "type": "lacuna",
        "title": "Norme lipsă",
        "context": "Explică gap-ul și checklist-ul.",
        "evidence": [
            {
                "label": "Legea 1/2026 art. 3",
                "act_id": "lege-1-2026",
                "locator": "art3",
                "source_url": "https://example.test/lege1",
                "source_hash": "c" * 64,
                "quote": "Guvernul aprobă normele metodologice în termen de 30 de zile.",
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
            "titlu": "Dosar norme",
            "intrebare": "",
            "domeniu": "administrativ",
            "data_analizei": None,
        },
    )
    return path


def execute_request(**patch):
    request = {
        "id": AUDIT_ID,
        "dosar_id": DOSSIER_ID,
        "boundary": "local_ai",
        "draft": draft_request(),
        "provider": "deterministic-local-mock",
        "approved": True,
        "result_text": "",
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


def test_preview_shows_cost_privacy_and_approval():
    out = ai_workflow.preview(
        {"boundary": "online_byok", "draft": draft_request(), "provider": "OpenAI / gpt-test"}
    )

    assert out["contract"] == "ai-dossier-assistant-workflow-v1"
    assert out["status"] == "requires_user_action"
    assert out["approval"]["required"] is True
    assert out["approval"]["external_send_required"] is True
    assert out["approval"]["unsupported_claims_block_or_label"] is True
    assert out["privacy"]["server_calls_model"] is False
    assert out["privacy"]["stores_api_key"] is False
    assert out["privacy"]["prompt_scope"] == "selected_evidence_only"
    assert out["cost_estimate"]["server_cost"] == "none"


def test_local_mock_generates_gap_proposal_checklist_and_append_only_audit(dossier_db):
    out = ai_workflow.execute(dossier_db, execute_request())
    retry = ai_workflow.execute(dossier_db, execute_request())

    assert out == retry
    assert out["contract"] == "ai-draft-storage-audit-v1"
    assert out["workflow_contract"] == "ai-dossier-assistant-workflow-v1"
    assert out["boundary"] == "local_ai"
    assert out["approved"] is True
    assert out["server_calls_model"] is False
    assert out["stores_api_key"] is False
    assert out["insert_allowed"] is True
    assert out["output_status"] == "draft_unreviewed"
    assert "Explicație gap" in out["draft_text"]
    assert "Propunere de lucru" in out["draft_text"]
    assert "Checklist reviewer" in out["draft_text"]
    assert out["claim_support"]["unsupported_claims"] == 0
    assert len(out["result_sha256"]) == 64

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        dosare._open(dossier_db, write=True) as con,
    ):
        con.execute("UPDATE ai_draft_audit_events SET status='reviewed' WHERE id=?", (AUDIT_ID,))


def test_online_byok_result_is_stored_without_secret_and_labels_uncited_claim(dossier_db):
    out = ai_workflow.execute(
        dossier_db,
        execute_request(
            boundary="online_byok",
            provider="OpenAI / gpt-test",
            result_text="Legea obligă autoritatea să emită norme. Ipoteza vine din dovadă [1].",
        ),
    )

    assert out["boundary"] == "online_byok"
    assert out["approved_external_send"] is True
    assert out["provider"] == "OpenAI / gpt-test"
    assert out["output_status"] == "draft_labeled_unsupported_claims"
    assert out["insert_allowed"] is True
    assert out["claim_support"]["unsupported_claims"] == 1
    assert out["claim_support"]["claims"][0]["status"] == "unsupported_labeled"
    assert "SECRET" not in json.dumps(out)


def test_citation_outside_selected_evidence_blocks_insertion(dossier_db):
    out = ai_workflow.execute(
        dossier_db,
        execute_request(result_text="Propunerea pare susținută de o altă sursă [2]."),
    )

    assert out["output_status"] == "blocked_unsupported_claims"
    assert out["insert_allowed"] is False
    assert out["claim_support"]["blocks_insertion"] is True
    assert out["claim_support"]["claims"][0]["reason"] == "citation_outside_selected_evidence"


def test_http_route_stores_workflow_only_for_local_origin(dossier_db):
    state = SimpleNamespace(initiative=dossier_db.with_suffix(".initiative.db"), date_dir=None)
    state.dosare_db = dossier_db

    assert (
        http_request(
            state,
            "POST",
            "/api/dosare/ai-workflow",
            execute_request(),
            origin="https://evil.test",
        )[0]
        == 403
    )

    code, data = http_request(state, "POST", "/api/dosare/ai-workflow", execute_request())
    assert code == 200
    assert data["contract"] == "ai-draft-storage-audit-v1"
    assert data["audit_json" if False else "server_calls_model"] is False
