"""User-facing source freshness/completeness states.

This module does not fetch, crawl or infer legal truth. It only turns already
stored registry/tracker facts into one bounded vocabulary the UI can show.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

FRESHNESS_STATES = (
    "missing",
    "stale",
    "partial",
    "current",
    "unavailable",
    "needs_review",
)

FRESHNESS_LABELS = {
    "missing": "Lipsește",
    "stale": "Învechită",
    "partial": "Parțială",
    "current": "Curentă",
    "unavailable": "Indisponibilă",
    "needs_review": "Necesită revizie",
}

FRESHNESS_SEVERITY = {
    "missing": "attention",
    "stale": "attention",
    "partial": "attention",
    "current": "ok",
    "unavailable": "blocked",
    "needs_review": "attention",
}

REVIEW_STATES = frozenset({"changed", "failed", "needs_review", "rate_limited"})
UNAVAILABLE_STATES = frozenset({"unavailable"})
CURRENT_STATES = frozenset({"unchanged", "fetched"})
PENDING_STATES = frozenset({"discovered", "queued"})


def parse_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw).astimezone(UTC)


def is_stale(value: object, *, now: datetime | None = None, stale_days: int = 30) -> bool:
    try:
        parsed = parse_time(value)
    except ValueError:
        return True
    if parsed is None:
        return True
    return parsed < (now or datetime.now(UTC)).astimezone(UTC) - timedelta(days=stale_days)


def state_payload(
    state: str,
    *,
    reason: str,
    missing: list[str] | None = None,
    stale_days: int | None = None,
) -> dict:
    if state not in FRESHNESS_STATES:
        raise ValueError("Stare actualitate sursă necunoscută.")
    return {
        "contract": "source-freshness-v1",
        "state": state,
        "label": FRESHNESS_LABELS[state],
        "severity": FRESHNESS_SEVERITY[state],
        "reason": reason,
        "missing": list(missing or []),
        "stale_after_days": stale_days,
    }


def for_registry_row(
    row: dict,
    *,
    now: datetime | None = None,
    stale_days: int = 30,
    completeness: str = "single_source",
) -> dict:
    state = str(row.get("state") or "")
    if state in UNAVAILABLE_STATES:
        return state_payload(
            "unavailable",
            reason="Sursa oficială este absentă, nesuportată sau inaccesibilă local.",
            stale_days=stale_days,
        )
    if state in REVIEW_STATES:
        return state_payload(
            "needs_review",
            reason="Ultima citire cere revizie înainte de folosirea în concluzii.",
            stale_days=stale_days,
        )
    if not row.get("last_attempt_at") or state in PENDING_STATES:
        return state_payload(
            "missing",
            reason="Sursa este în registru, dar nu are încă o citire locală utilizabilă.",
            missing=["last_attempt_at"],
            stale_days=stale_days,
        )
    if is_stale(row.get("last_attempt_at"), now=now, stale_days=stale_days):
        return state_payload(
            "stale",
            reason=f"Ultima citire depășește pragul de {stale_days} zile.",
            stale_days=stale_days,
        )
    if completeness == "partial":
        return state_payload(
            "partial",
            reason="Există date locale, dar nu toate familiile cerute sunt acoperite.",
            stale_days=stale_days,
        )
    if state in CURRENT_STATES or row.get("last_hash"):
        return state_payload(
            "current",
            reason="Sursa are o citire locală recentă și fără alertă deschisă.",
            stale_days=stale_days,
        )
    return state_payload(
        "partial",
        reason="Sursa are metadate locale, dar nu are hash/verificare completă.",
        missing=["content_hash"],
        stale_days=stale_days,
    )


def for_coverage_group(families: list[dict], *, stale_days: int = 30) -> dict:
    missing = [
        row["family"] for row in families if row.get("freshness", {}).get("state") == "missing"
    ]
    unavailable = [
        row["family"] for row in families if row.get("freshness", {}).get("state") == "unavailable"
    ]
    review = [
        row["family"] for row in families if row.get("freshness", {}).get("state") == "needs_review"
    ]
    stale = [row["family"] for row in families if row.get("freshness", {}).get("state") == "stale"]
    present = [
        row["family"] for row in families if row.get("freshness", {}).get("state") == "current"
    ]
    if unavailable:
        return state_payload(
            "unavailable",
            reason="Cel puțin o familie necesară este indisponibilă.",
            missing=unavailable,
            stale_days=stale_days,
        )
    if review:
        return state_payload(
            "needs_review",
            reason="Cel puțin o familie necesară are alertă deschisă.",
            missing=review,
            stale_days=stale_days,
        )
    if missing and present:
        return state_payload(
            "partial",
            reason="Acoperirea există, dar lipsesc familii cerute.",
            missing=missing,
            stale_days=stale_days,
        )
    if missing:
        return state_payload(
            "missing",
            reason="Nu există încă surse/evenimente locale pentru familie.",
            missing=missing,
            stale_days=stale_days,
        )
    if stale:
        return state_payload(
            "stale",
            reason="Cel puțin o familie are citire locală învechită.",
            missing=stale,
            stale_days=stale_days,
        )
    return state_payload(
        "current", reason="Familiile cerute au date locale fără alertă.", stale_days=stale_days
    )
