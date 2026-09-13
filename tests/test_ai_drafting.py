import pytest

from scripts import ai_drafting


def payload(**extra):
    data = {
        "task": "issue_note",
        "type": "lacuna",
        "title": "Lacună privind normele",
        "context": "Verifică dacă obligația are act subsecvent.",
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
    data.update(extra)
    return data


def test_ai_drafting_preview_is_source_grounded_and_client_side():
    out = ai_drafting.preview(payload())

    assert out["contract"] == "ai-evidence-draft-v1"
    assert out["mode"] == "client_local_or_byok"
    assert out["status"] == "draft_unreviewed"
    assert out["evidence_count"] == 1
    assert len(out["input_sha256"]) == 64
    assert len(out["evidence_sha256"]) == 64
    assert out["evidence_manifest"][0]["quote_sha256"]
    assert "quote" not in out["evidence_manifest"][0]
    assert out["export_manifest"]["contract"] == "bounded-evidence-export-manifest-v1"
    assert out["export_manifest"]["max_evidence_items"] == ai_drafting.MAX_EVIDENCE
    assert out["export_manifest"]["max_quote_chars"] == ai_drafting.MAX_QUOTE
    assert out["export_manifest"]["max_context_chars"] == ai_drafting.MAX_CONTEXT
    assert out["export_manifest"]["max_prompt_bytes"] == ai_drafting.MAX_PROMPT
    assert out["export_manifest"]["source_hashes_and_urls_preserved"] is True
    assert out["export_manifest"]["server_calls_model"] is False
    assert out["export_manifest"]["credentials_stored"] is False
    assert out["export_manifest"]["non_verdict_notice"] == "Ciornă de lucru; nu verdict juridic."
    assert (
        out["export_manifest"]["source_references"][0]["source_url"] == "https://example.test/lege"
    )
    assert out["export_manifest"]["source_references"][0]["quote_sha256"]
    assert any("chei API" in item for item in out["export_manifest"]["private_data_excluded"])
    assert out["approval"]["required_for_external_ai"] is True
    assert out["approval"]["server_calls_model"] is False
    assert any("BYOK" in item for item in out["approval"]["private_data_excluded"])
    assert out["cost_estimate"]["server_cost"] == "none"
    assert out["cost_estimate"]["cost_owner"] == "user_if_byok_or_mcp"
    assert out["external_approval_payload"]["contract"] == "ai-external-send-approval-v1"
    assert out["external_approval_payload"]["input_sha256"] == out["input_sha256"]
    assert out["external_approval_payload"]["evidence_sha256"] == out["evidence_sha256"]
    assert out["external_approval_payload"]["server_calls_model"] is False
    assert out["external_approval_payload"]["stores_api_key"] is False
    assert out["external_approval_payload"]["output_status"] == "draft_unreviewed"
    assert out["external_approval_payload"]["may_invent_sources"] is False
    assert out["execution_boundary"]["contract"] == "ai-byok-execution-boundary-v1"
    assert out["execution_boundary"]["runtime"] == "browser_direct_provider_or_local_webgpu"
    assert out["execution_boundary"]["server_calls_model"] is False
    assert out["execution_boundary"]["app_paid_provider"] is False
    assert out["execution_boundary"]["stores_api_key"] is False
    assert out["execution_boundary"]["allowed_modes"] == ["local_ai", "online_byok"]
    assert out["execution_boundary"]["prompt_scope"] == "selected_evidence_only"
    assert out["execution_boundary"]["output_status"] == "draft_unreviewed"
    assert out["execution_boundary"]["failure_contract"] == "ai-byok-provider-failure-v1"
    assert [item["code"] for item in out["execution_boundary"]["failure_states"]] == [
        "timeout",
        "bad_key",
        "quota",
        "refusal",
        "malformed_response",
        "provider_unavailable",
    ]
    assert out["provider_failure_states"][0]["output_status"] == "no_draft_created"
    assert out["audit"]["approved_external_send"] is False
    assert out["audit"]["model_invoked_by_server"] is False
    assert "Nu inventa surse" in out["system"]
    assert "Guvernul aprobă normele" in out["prompt"]
    assert "evidence_manifest" in out["prompt"]
    assert "bounded-evidence-export-manifest-v1" in out["prompt"]
    assert "verdict juridic final" in out["prompt"]
    assert any("Serverul nu a apelat niciun model" in item for item in out["limitari"])


@pytest.mark.parametrize(
    ("task", "label"),
    [
        ("explain_issue", "explică problema"),
        ("issue_note", "notă de constatare"),
        ("draft_amendment", "ciornă amendament"),
        ("review_checklist", "listă de verificare"),
        ("amendment_rationale", "ciornă amendament"),
    ],
)
def test_ai_drafting_supports_byok_ui_tasks(task, label):
    out = ai_drafting.preview(payload(task=task))

    assert out["task"] == ("draft_amendment" if task == "amendment_rationale" else task)
    assert label in out["prompt"]


def test_ai_drafting_requires_bounded_source_evidence():
    with pytest.raises(ValueError, match="URL sau SHA"):
        ai_drafting.preview(
            payload(evidence=[{"label": "fără sursă", "quote": "Text fără proveniență."}])
        )

    with pytest.raises(ValueError, match="între 1 și 8"):
        ai_drafting.preview(payload(evidence=[]))

    with pytest.raises(ValueError, match="Tip de ciornă"):
        ai_drafting.preview(payload(task="legal_verdict"))


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("timeout", True),
        ("bad_key", False),
        ("quota", True),
        ("refusal", False),
        ("malformed_response", False),
        ("provider_unavailable", True),
        ("unknown-provider-error", True),
    ],
)
def test_ai_byok_provider_failure_states_are_secret_free(code, retryable):
    out = ai_drafting.provider_failure_state(code)

    assert out["contract"] == "ai-byok-provider-failure-v1"
    assert out["retryable"] is retryable
    assert out["server_calls_model"] is False
    assert out["stores_api_key"] is False
    assert out["output_status"] == "no_draft_created"
    assert "SECRET" not in str(out)
