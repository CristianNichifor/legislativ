from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts import source_freshness


def test_registry_freshness_uses_six_user_facing_states():
    now = datetime(2026, 9, 14, tzinfo=UTC)

    assert (
        source_freshness.for_registry_row({"state": "discovered", "last_attempt_at": ""}, now=now)[
            "state"
        ]
        == "missing"
    )
    assert (
        source_freshness.for_registry_row(
            {"state": "unchanged", "last_attempt_at": "2026-01-01T00:00:00+00:00"},
            now=now,
            stale_days=30,
        )["state"]
        == "stale"
    )
    assert (
        source_freshness.for_registry_row(
            {"state": "unchanged", "last_attempt_at": "2026-09-13T00:00:00+00:00"},
            now=now,
        )["state"]
        == "current"
    )
    assert (
        source_freshness.for_registry_row(
            {"state": "changed", "last_attempt_at": "2026-09-13T00:00:00+00:00"},
            now=now,
        )["state"]
        == "needs_review"
    )
    assert (
        source_freshness.for_registry_row(
            {"state": "unavailable", "last_attempt_at": "2026-09-13T00:00:00+00:00"},
            now=now,
        )["state"]
        == "unavailable"
    )
    assert (
        source_freshness.for_registry_row(
            {"state": "fetched", "last_attempt_at": "2026-09-13T00:00:00+00:00"},
            now=now,
            completeness="partial",
        )["state"]
        == "partial"
    )


def test_coverage_group_reports_partial_missing_and_review():
    rows = [
        {
            "family": "camera",
            "freshness": source_freshness.state_payload("current", reason="ok"),
        },
        {
            "family": "monitorul_oficial_pi",
            "freshness": source_freshness.state_payload(
                "missing", reason="missing", missing=["monitorul_oficial_pi"]
            ),
        },
    ]

    partial = source_freshness.for_coverage_group(rows)
    assert partial["state"] == "partial"
    assert partial["missing"] == ["monitorul_oficial_pi"]

    rows[1]["freshness"] = source_freshness.state_payload("needs_review", reason="review")
    review = source_freshness.for_coverage_group(rows)
    assert review["state"] == "needs_review"
    assert review["severity"] == "attention"


def test_state_payload_rejects_unknown_states():
    with pytest.raises(ValueError, match="actualitate"):
        source_freshness.state_payload("ok", reason="legacy")
