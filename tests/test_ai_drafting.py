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
    assert "Nu inventa surse" in out["system"]
    assert "Guvernul aprobă normele" in out["prompt"]
    assert "verdict juridic final" in out["prompt"]
    assert any("Serverul nu a apelat niciun model" in item for item in out["limitari"])


def test_ai_drafting_requires_bounded_source_evidence():
    with pytest.raises(ValueError, match="URL sau SHA"):
        ai_drafting.preview(
            payload(evidence=[{"label": "fără sursă", "quote": "Text fără proveniență."}])
        )

    with pytest.raises(ValueError, match="între 1 și 8"):
        ai_drafting.preview(payload(evidence=[]))

    with pytest.raises(ValueError, match="Tip de ciornă"):
        ai_drafting.preview(payload(task="legal_verdict"))
