"""Shared source-sync state vocabulary for small, one-source refreshes.

This module does not fetch public sources and does not schedule jobs. It only
keeps the future registry/queue work on one explicit contract.
"""

from __future__ import annotations

from dataclasses import dataclass

SYNC_STATES = (
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

STATE_LABELS = {
    "discovered": "Source known by URL or public identifier; no fetch attempted in this queue.",
    "queued": "Source selected for one bounded sync attempt.",
    "fetched": "Source bytes or metadata were fetched for the first time.",
    "unchanged": "Fetched source hash matches the previous retained observation.",
    "changed": "Fetched source hash differs from the previous retained observation.",
    "failed": "Fetch or parsing failed for a retryable reason.",
    "unavailable": "Official source is absent, unsupported, removed or outside allowed access.",
    "rate_limited": "Official source asked the app to slow down or returned an equivalent limit.",
    "needs_review": "Source is fetched but cannot safely update derived legal data automatically.",
}

_STATE_SET = frozenset(SYNC_STATES)

_TRANSITIONS = {
    "discovered": frozenset({"queued", "unavailable", "needs_review"}),
    "queued": frozenset({"fetched", "failed", "unavailable", "rate_limited", "needs_review"}),
    "fetched": frozenset({"unchanged", "changed", "needs_review"}),
    "unchanged": frozenset({"queued", "needs_review"}),
    "changed": frozenset({"queued", "needs_review"}),
    "failed": frozenset({"queued", "unavailable", "rate_limited", "needs_review"}),
    "unavailable": frozenset({"queued", "needs_review"}),
    "rate_limited": frozenset({"queued", "failed"}),
    "needs_review": frozenset({"queued", "unchanged", "changed", "unavailable"}),
}


@dataclass(frozen=True)
class SyncDecision:
    """One-source sync classification, with no raw source text or local paths."""

    state: str
    retryable: bool
    changed: bool
    reason: str


def normalize_state(value: str) -> str:
    """Return a known state or raise a bounded validation error."""
    if value not in _STATE_SET:
        raise ValueError("Unknown source sync state.")
    return value


def can_transition(current: str, target: str) -> bool:
    """Whether a registry row may move between two explicit source states."""
    current = normalize_state(current)
    target = normalize_state(target)
    return current == target or target in _TRANSITIONS[current]


def classify_one_source_sync(
    *,
    previous_hash: str | None = None,
    fetched_hash: str | None = None,
    http_status: int | None = None,
    error: str | None = None,
    retry_after_seconds: int | None = None,
    needs_review: bool = False,
) -> SyncDecision:
    """Classify one bounded source-sync attempt.

    The caller owns URL validation, fetching, hashing and parsing. This function
    only maps those facts to the public queue vocabulary.
    """
    if retry_after_seconds is not None or http_status == 429:
        return SyncDecision("rate_limited", retryable=True, changed=False, reason="rate limited")
    if http_status in {404, 410, 451}:
        return SyncDecision("unavailable", retryable=False, changed=False, reason="unavailable")
    if error:
        return SyncDecision("failed", retryable=True, changed=False, reason="failed")
    if fetched_hash is None:
        return SyncDecision("unavailable", retryable=False, changed=False, reason="no content")
    if needs_review:
        return SyncDecision("needs_review", retryable=False, changed=False, reason="manual review")
    if previous_hash is None:
        return SyncDecision("fetched", retryable=False, changed=True, reason="first fetch")
    if fetched_hash == previous_hash:
        return SyncDecision("unchanged", retryable=False, changed=False, reason="hash match")
    return SyncDecision("changed", retryable=False, changed=True, reason="hash changed")


def one_source_acceptance_boundaries() -> dict[str, object]:
    """Machine-readable minimum for the first one-source sync slice."""
    return {
        "states": list(SYNC_STATES),
        "must_record": [
            "source_family",
            "source_identifier_or_url",
            "attempted_at",
            "state",
            "status_code_or_error_category",
            "content_hash_when_available",
            "parser_version_when_parsed",
        ],
        "must_not_do": [
            "full_dataset_rebuild",
            "bulk_download",
            "ai_legal_verdict",
            "overwrite_private_dossiers",
            "hide_missing_or_unavailable_source",
        ],
    }
