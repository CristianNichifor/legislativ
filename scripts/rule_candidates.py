"""Reviewed rule-candidate contract for law-as-code work.

This validates a human or AI-assisted extraction before it can become an
executable legal rule. It does not decide that the rule is legally correct.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Final

from scripts import dosare

CONTRACT: Final[str] = "rule-candidate-v1"
MODALITIES: Final[frozenset[str]] = frozenset(
    {
        "obligation",
        "prohibition",
        "permission",
        "procedure",
        "deadline",
        "competence",
        "sanction",
        "definition",
        "exception",
        "vague_standard",
        "not_codeable",
    }
)
REVIEW_STATES: Final[frozenset[str]] = frozenset(
    {"machine_detected", "human_reviewed", "legally_validated", "disputed", "obsolete"}
)
REQUIRED: Final[frozenset[str]] = frozenset(
    {"provision_id", "act_id", "locator", "source_hash", "text", "modality", "review_state"}
)


@dataclass(frozen=True)
class RuleCandidate:
    contract: str
    status: str
    candidate_id: str
    provision_id: str
    act_id: str
    locator: str
    modality: str
    review_state: str
    text_sha256: str
    source_hash: str
    actor: str = ""
    condition: str = ""
    action: str = ""
    deadline: str = ""
    exceptions: tuple[str, ...] = field(default_factory=tuple)
    effect: str = ""
    reviewer: str = ""
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["exceptions"] = list(self.exceptions)
        out["limitations"] = list(self.limitations)
        return out


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _text(value, limit: int, required: bool = False) -> str:
    return dosare._text(value, limit, required)


def _hash(value) -> str:
    value = _text(value, 64, True)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Hash sursă invalid.")
    return value


def _enum(value, allowed: frozenset[str], label: str) -> str:
    value = _text(value, 80, True)
    if value not in allowed:
        raise ValueError(f"{label} neacceptat.")
    return value


def _exceptions(value) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Excepții invalide.")
    return tuple(_text(item, 600, True) for item in value)


def _candidate_id(payload: dict) -> str:
    material = {
        key: payload[key]
        for key in (
            "provision_id",
            "source_hash",
            "modality",
            "actor",
            "condition",
            "action",
            "deadline",
            "effect",
            "exceptions",
        )
    }
    return _sha(dosare._json(material))[:32]


def validate(request: dict) -> dict:
    if not isinstance(request, dict) or not REQUIRED.issubset(request):
        raise ValueError("Candidat de regulă incomplet.")
    extra = set(request) - (
        REQUIRED
        | {
            "actor",
            "condition",
            "action",
            "deadline",
            "exceptions",
            "effect",
            "reviewer",
        }
    )
    if extra:
        raise ValueError("Câmpuri nepermise în candidatul de regulă.")

    text = _text(request["text"], 12000, True)
    modality = _enum(request["modality"], MODALITIES, "Tip regulă")
    review_state = _enum(request["review_state"], REVIEW_STATES, "Stare revizie")
    normalized = {
        "provision_id": _text(request["provision_id"], 240, True),
        "act_id": _text(request["act_id"], 200, True),
        "locator": _text(request["locator"], 120, True),
        "source_hash": _hash(request["source_hash"]),
        "text": text,
        "modality": modality,
        "review_state": review_state,
        "actor": _text(request.get("actor"), 300),
        "condition": _text(request.get("condition"), 1200),
        "action": _text(request.get("action"), 1200),
        "deadline": _text(request.get("deadline"), 300),
        "exceptions": list(_exceptions(request.get("exceptions"))),
        "effect": _text(request.get("effect"), 1200),
        "reviewer": _text(request.get("reviewer"), 160),
    }
    limitations: list[str] = [
        "Candidatul nu este o concluzie juridică și nu se execută automat.",
        "Textul sursă rămâne autoritatea; câmpurile structurate sunt revizuibile.",
    ]
    status = "reviewable"
    if modality == "not_codeable":
        status = "not_codeable"
        limitations.append("Prevederea este marcată ca nepotrivită pentru codificare.")
    elif modality == "vague_standard":
        status = "needs_legal_review"
        limitations.append("Standardul juridic este vag și cere interpretare umană.")
    elif not (normalized["actor"] and normalized["action"]):
        status = "needs_more_structure"
        limitations.append("Actorul și acțiunea trebuie completate înainte de executare.")

    return RuleCandidate(
        contract=CONTRACT,
        status=status,
        candidate_id=_candidate_id(normalized),
        provision_id=normalized["provision_id"],
        act_id=normalized["act_id"],
        locator=normalized["locator"],
        modality=modality,
        review_state=review_state,
        text_sha256=_sha(text),
        source_hash=normalized["source_hash"],
        actor=normalized["actor"],
        condition=normalized["condition"],
        action=normalized["action"],
        deadline=normalized["deadline"],
        exceptions=tuple(normalized["exceptions"]),
        effect=normalized["effect"],
        reviewer=normalized["reviewer"],
        limitations=tuple(limitations),
    ).to_dict()
