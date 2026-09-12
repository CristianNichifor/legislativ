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
    assert out["approval"]["required_for_external_ai"] is True
    assert out["approval"]["server_calls_model"] is False
    assert out["cost_estimate"]["server_cost"] == "none"
    assert out["cost_estimate"]["cost_owner"] == "user_if_byok_or_mcp"
    assert out["audit"]["approved_external_send"] is False
    assert out["audit"]["model_invoked_by_server"] is False
    assert "Nu inventa surse" in out["system"]
    assert "Guvernul aprobă normele" in out["prompt"]
    assert "evidence_manifest" in out["prompt"]
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
