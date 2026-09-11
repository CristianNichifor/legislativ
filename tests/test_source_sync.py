import pytest

from scripts.source_sync import (
    STATE_LABELS,
    SYNC_STATES,
    can_transition,
    classify_one_source_sync,
    normalize_state,
    one_source_acceptance_boundaries,
)


def test_state_vocabulary_is_complete_and_documented():
    assert SYNC_STATES == (
        "discovered",
        "queued",
        "fetched",
        "unchanged",
        "changed",
        "failed",
        "unavailable",
        "rate_limited",
        "needs_review",
    )
    assert set(STATE_LABELS) == set(SYNC_STATES)
    assert all(STATE_LABELS[state] for state in SYNC_STATES)


def test_state_validation_and_transitions_are_bounded():
    assert normalize_state("queued") == "queued"
    with pytest.raises(ValueError, match="Unknown source sync state"):
        normalize_state("parsed")
    assert can_transition("discovered", "queued")
    assert can_transition("queued", "rate_limited")
    assert can_transition("fetched", "changed")
    assert can_transition("failed", "queued")
    assert not can_transition("discovered", "changed")
    assert not can_transition("rate_limited", "changed")


@pytest.mark.parametrize(
    ("kwargs", "state", "retryable", "changed", "reason"),
    [
        ({"retry_after_seconds": 60}, "rate_limited", True, False, "rate limited"),
        ({"http_status": 429}, "rate_limited", True, False, "rate limited"),
        ({"http_status": 404}, "unavailable", False, False, "unavailable"),
        ({"http_status": 410}, "unavailable", False, False, "unavailable"),
        ({"http_status": 451}, "unavailable", False, False, "unavailable"),
        ({"error": "timeout"}, "failed", True, False, "failed"),
        ({"fetched_hash": None}, "unavailable", False, False, "no content"),
        (
            {"fetched_hash": "abc", "needs_review": True},
            "needs_review",
            False,
            False,
            "manual review",
        ),
        ({"fetched_hash": "abc"}, "fetched", False, True, "first fetch"),
        (
            {"previous_hash": "abc", "fetched_hash": "abc"},
            "unchanged",
            False,
            False,
            "hash match",
        ),
        (
            {"previous_hash": "abc", "fetched_hash": "def"},
            "changed",
            False,
            True,
            "hash changed",
        ),
    ],
)
def test_one_source_sync_classification(kwargs, state, retryable, changed, reason):
    decision = classify_one_source_sync(**kwargs)
    assert decision.state == state
    assert decision.retryable is retryable
    assert decision.changed is changed
    assert decision.reason == reason


def test_one_source_acceptance_boundaries_exclude_large_release_work():
    contract = one_source_acceptance_boundaries()
    assert contract["states"] == list(SYNC_STATES)
    assert "source_family" in contract["must_record"]
    assert "content_hash_when_available" in contract["must_record"]
    assert "full_dataset_rebuild" in contract["must_not_do"]
    assert "bulk_download" in contract["must_not_do"]
    assert "ai_legal_verdict" in contract["must_not_do"]
