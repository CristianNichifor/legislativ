"""Deterministic source snapshot diff contract.

This module classifies already-captured snapshots. It does not fetch, parse or
rewrite legal data; callers use it to decide what needs human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

CONTRACT = "source-change-detection-v1"


@dataclass(frozen=True)
class SourceChange:
    type: str
    severity: str
    label: str
    before: object = None
    after: object = None
    key: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _items(snapshot: dict, key: str) -> list[dict]:
    items = snapshot.get(key) or snapshot.get("summary", {}).get(key) or []
    return [item for item in items if isinstance(item, dict)]


def _identity(item: dict) -> str:
    for key in ("id", "url", "href", "number", "identifier", "locator", "title", "label"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return repr(sorted(item.items()))


def _index(items: list[dict]) -> dict[str, dict]:
    return {_identity(item): item for item in items}


def _text(value) -> str:
    return str(value or "").strip()


def _change_type(item: dict) -> tuple[str, str, str]:
    haystack = " ".join(
        _text(item.get(key)) for key in ("type", "kind", "label", "title", "name", "category")
    ).lower()
    if "raport" in haystack or "report" in haystack:
        return ("new_committee_report", "attention", "Raport/comisie nouă în sursă.")
    if "vot" in haystack or "vote" in haystack:
        return ("new_vote", "attention", "Vot nou în sursă.")
    return ("new_document", "info", "Document nou în sursă.")


def _add_document_changes(previous: dict, current: dict, changes: list[SourceChange]) -> None:
    before = _index(_items(previous, "documents"))
    after = _index(_items(current, "documents"))
    for key, item in sorted(after.items()):
        if key not in before:
            change_type, severity, label = _change_type(item)
            changes.append(SourceChange(change_type, severity, label, after=item, key=key))


def _event_type(item: dict) -> tuple[str, str] | None:
    haystack = " ".join(
        _text(item.get(key)) for key in ("event_type", "type", "key", "action", "title")
    ).lower()
    if "report" in haystack or "raport" in haystack:
        return ("new_committee_report", "Eveniment nou de raport/comisie.")
    if "vote" in haystack or "vot" in haystack:
        return ("new_vote", "Eveniment nou de vot.")
    if "closed" in haystack or "inchis" in haystack or "închis" in haystack:
        return ("consultation_closed", "Consultare publică închisă.")
    return None


def _add_event_changes(previous: dict, current: dict, changes: list[SourceChange]) -> None:
    before = _index(_items(previous, "events"))
    after = _index(_items(current, "events"))
    for key, item in sorted(after.items()):
        if key in before:
            continue
        classified = _event_type(item)
        if classified:
            change_type, label = classified
            changes.append(SourceChange(change_type, "attention", label, after=item, key=key))


def _deadline(snapshot: dict) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    for key in ("deadline", "consultation_deadline", "data_limita"):
        value = _text(snapshot.get(key) or summary.get(key))
        if value:
            return value
    return ""


def _add_field_changes(previous: dict, current: dict, changes: list[SourceChange]) -> None:
    before_deadline, after_deadline = _deadline(previous), _deadline(current)
    if before_deadline and after_deadline and before_deadline != after_deadline:
        changes.append(
            SourceChange(
                "deadline_changed",
                "attention",
                "Termenul oficial s-a schimbat.",
                before=before_deadline,
                after=after_deadline,
            )
        )
    before_status = _text(previous.get("status") or previous.get("summary", {}).get("status"))
    after_status = _text(current.get("status") or current.get("summary", {}).get("status"))
    if before_status != "closed" and after_status == "closed":
        changes.append(
            SourceChange(
                "consultation_closed",
                "attention",
                "Consultarea publică este marcată ca închisă.",
                before=before_status,
                after=after_status,
            )
        )
    before_mo = _text(previous.get("monitorul_oficial") or previous.get("summary", {}).get("mo"))
    after_mo = _text(current.get("monitorul_oficial") or current.get("summary", {}).get("mo"))
    if not before_mo and after_mo:
        changes.append(
            SourceChange(
                "published_in_monitor",
                "attention",
                "Sursa indică publicare în Monitorul Oficial.",
                after=after_mo,
            )
        )


def detect_changes(previous: dict | None, current: dict) -> dict:
    """Return a bounded diff for two already-normalized snapshots."""
    previous = previous or {}
    changes: list[SourceChange] = []
    _add_document_changes(previous, current, changes)
    _add_event_changes(previous, current, changes)
    _add_field_changes(previous, current, changes)
    before_hash = _text(previous.get("content_hash"))
    after_hash = _text(current.get("content_hash"))
    if before_hash and after_hash and before_hash != after_hash and not changes:
        changes.append(
            SourceChange(
                "content_hash_changed",
                "attention",
                "Conținutul sursei s-a schimbat, dar parserul nu a clasificat diferența.",
                before=before_hash,
                after=after_hash,
            )
        )
    severity = "none"
    if any(change.severity == "attention" for change in changes):
        severity = "attention"
    elif changes:
        severity = "info"
    return {
        "contract": CONTRACT,
        "changed": bool(changes),
        "severity": severity,
        "changes": [change.to_dict() for change in changes],
        "limitations": [
            "Compară instantanee deja capturate; nu descarcă surse oficiale.",
            "Clasificarea este conservatoare și nu actualizează automat date juridice.",
        ],
    }
