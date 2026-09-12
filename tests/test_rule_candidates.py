from __future__ import annotations

import pytest

from scripts import rule_candidates


def payload(**patch):
    data = {
        "provision_id": "ro:lege-98-2016#art7.alin2",
        "act_id": "lege-98-2016",
        "locator": "art7.alin2",
        "source_hash": "a" * 64,
        "text": "Autoritatea contractantă publică anunțul în SEAP.",
        "modality": "obligation",
        "review_state": "human_reviewed",
        "actor": "autoritatea contractantă",
        "condition": "procedura este inițiată",
        "action": "publică anunțul în SEAP",
        "deadline": "",
        "exceptions": ["cazurile expres exceptate de lege"],
        "effect": "procedura poate fi contestată dacă publicarea lipsește",
        "reviewer": "test",
    }
    data.update(patch)
    return data


def test_rule_candidate_is_reviewable_and_source_bound():
    out = rule_candidates.validate(payload())

    assert out["contract"] == "rule-candidate-v1"
    assert out["status"] == "reviewable"
    assert len(out["candidate_id"]) == 32
    assert len(out["text_sha256"]) == 64
    assert out["source_hash"] == "a" * 64
    assert out["actor"] == "autoritatea contractantă"
    assert out["exceptions"] == ["cazurile expres exceptate de lege"]
    assert any("nu este o concluzie juridică" in item for item in out["limitations"])


def test_candidate_id_is_stable_for_same_normalized_payload():
    first = rule_candidates.validate(payload())
    second = rule_candidates.validate(payload())

    assert first["candidate_id"] == second["candidate_id"]


@pytest.mark.parametrize(
    ("modality", "status"),
    [
        ("not_codeable", "not_codeable"),
        ("vague_standard", "needs_legal_review"),
        ("obligation", "needs_more_structure"),
    ],
)
def test_non_executable_states_are_explicit(modality, status):
    out = rule_candidates.validate(payload(modality=modality, actor="", action=""))

    assert out["status"] == status
    assert out["limitations"]


@pytest.mark.parametrize(
    "patch",
    [
        {"source_hash": "x"},
        {"modality": "prediction"},
        {"review_state": "approved_by_ai"},
        {"exceptions": "none"},
        {"extra": "field"},
    ],
)
def test_invalid_candidate_payload_is_rejected(patch):
    with pytest.raises(ValueError):
        rule_candidates.validate(payload(**patch))
