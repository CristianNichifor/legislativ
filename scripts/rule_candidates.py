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
ENTRY_CONTRACT: Final[str] = "rule-candidate-entry-v1"
ENTRY_PREVIEW_CONTRACT: Final[str] = "rule-candidate-entry-preview-v1"
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
CONFIDENCE_LEVELS: Final[frozenset[str]] = frozenset({"unknown", "low", "medium", "high"})
EXTRACTION_METHODS: Final[frozenset[str]] = frozenset(
    {"manual", "provision", "manual_note", "matrix", "ai_draft", "mcp_draft", "imported"}
)
REQUIRED: Final[frozenset[str]] = frozenset(
    {"provision_id", "act_id", "locator", "source_hash", "text", "modality", "review_state"}
)
ENTRY_ORIGINS: Final[frozenset[str]] = frozenset({"manual_note", "provision", "matrix_evidence"})
OPTIONAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "actor",
        "condition",
        "action",
        "deadline",
        "exceptions",
        "effect",
        "source_url",
        "applicability_scope",
        "confidence",
        "extraction_method",
        "origin_kind",
        "origin_id",
        "reviewer",
        "supersedes_candidate_id",
        "supersedes_queue_id",
    }
)


@dataclass(frozen=True)
class RuleCandidate:
    contract: str
    status: str
    candidate_id: str
    provision_id: str
    act_id: str
    locator: str
    text: str
    modality: str
    review_state: str
    text_sha256: str
    source_hash: str
    source_url: str = ""
    actor: str = ""
    condition: str = ""
    action: str = ""
    deadline: str = ""
    exceptions: tuple[str, ...] = field(default_factory=tuple)
    effect: str = ""
    applicability_scope: str = ""
    confidence: str = "unknown"
    extraction_method: str = "manual"
    origin_kind: str = ""
    origin_id: str = ""
    reviewer: str = ""
    supersedes_candidate_id: str = ""
    supersedes_queue_id: str = ""
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
            "source_url",
            "modality",
            "review_state",
            "actor",
            "condition",
            "action",
            "deadline",
            "effect",
            "exceptions",
            "applicability_scope",
            "confidence",
            "extraction_method",
            "reviewer",
        )
    }
    return _sha(dosare._json(material))[:32]


def _candidate_ref(value, label: str) -> str:
    value = _text(value, 64)
    if value and (len(value) > 64 or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(f"{label} invalid.")
    return value


def _origin_value(origin: dict, *names: str) -> str:
    for name in names:
        value = origin.get(name)
        if value not in (None, ""):
            return value
    return ""


def _entry_origin(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("Origine candidat regulă invalidă.")
    kind = _enum(request.get("kind"), ENTRY_ORIGINS, "Origine candidat")
    act_id = _text(_origin_value(request, "act_id", "act"), 200, kind == "provision")
    locator = _text(_origin_value(request, "locator", "loc"), 120, kind == "provision")
    provision_id = _text(
        _origin_value(request, "provision_id")
        or (f"{act_id}#{locator}" if act_id and locator else ""),
        240,
        kind == "provision",
    )
    source_hash = _hash(_origin_value(request, "source_hash", "source_sha256", "sursa_sha256"))
    text = _text(
        _origin_value(request, "text", "quote", "evidence_quote", "citat_dovada"),
        12000,
        True,
    )
    return {
        "kind": kind,
        "id": _text(_origin_value(request, "id", "origin_id", "note_id"), 240),
        "provision_id": provision_id,
        "act_id": act_id,
        "locator": locator,
        "source_hash": source_hash,
        "source_url": _text(_origin_value(request, "source_url", "sursa_url", "url"), 1000),
        "text": text,
    }


def from_entry(request: dict) -> dict:
    """Build one validated candidate from a selected provision or manual note.

    This is a preview/entry contract only. Persistence stays in the existing
    append-only review queue, so editing means saving a corrected candidate with
    explicit ancestry instead of mutating a previous row.
    """
    if not isinstance(request, dict) or request.get("contract") != ENTRY_CONTRACT:
        raise ValueError("Cerere intrare candidat regulă invalidă.")
    extra = set(request) - {"contract", "dosar_id", "id", "origin", "candidate", "edit"}
    if extra:
        raise ValueError("Câmpuri nepermise în intrarea candidatului.")
    origin = _entry_origin(request.get("origin"))
    patch = request.get("candidate") or {}
    edit = request.get("edit") or {}
    if not isinstance(patch, dict) or not isinstance(edit, dict):
        raise ValueError("Editare candidat regulă invalidă.")
    allowed_patch = OPTIONAL_FIELDS | {"modality", "review_state", "text", "provision_id"}
    if set(patch) - allowed_patch:
        raise ValueError("Câmpuri nepermise în candidatul editat.")
    if set(edit) - {"supersedes_candidate_id", "supersedes_queue_id"}:
        raise ValueError("Câmpuri nepermise în istoricul editării.")
    candidate = validate(
        {
            "provision_id": _text(patch.get("provision_id") or origin["provision_id"], 240, True),
            "act_id": origin["act_id"],
            "locator": origin["locator"],
            "source_hash": origin["source_hash"],
            "source_url": origin["source_url"],
            "text": _text(patch.get("text") or origin["text"], 12000, True),
            "modality": patch.get("modality", "obligation"),
            "review_state": patch.get("review_state", "machine_detected"),
            "actor": patch.get("actor", ""),
            "condition": patch.get("condition", ""),
            "action": patch.get("action", ""),
            "deadline": patch.get("deadline", ""),
            "exceptions": patch.get("exceptions", []),
            "effect": patch.get("effect", ""),
            "applicability_scope": patch.get("applicability_scope", ""),
            "confidence": patch.get("confidence", "unknown"),
            "extraction_method": patch.get("extraction_method", origin["kind"]),
            "origin_kind": patch.get("origin_kind", origin["kind"]),
            "origin_id": patch.get("origin_id", origin["id"] or origin["provision_id"]),
            "reviewer": patch.get("reviewer", ""),
            "supersedes_candidate_id": edit.get("supersedes_candidate_id", ""),
            "supersedes_queue_id": edit.get("supersedes_queue_id", ""),
        }
    )
    dossier_id = _text(request.get("dosar_id", ""), 32)
    queue_id = _text(request.get("id", ""), 32)
    queue_payload = None
    if dossier_id and queue_id:
        queue_payload = {
            "action": "save",
            "id": dosare._id(queue_id),
            "dosar_id": dosare._id(dossier_id),
            "candidate": candidate,
        }
    return {
        "contract": ENTRY_PREVIEW_CONTRACT,
        "entry_contract": ENTRY_CONTRACT,
        "origin": origin,
        "candidate": candidate,
        "queue_payload": queue_payload,
        "edit_mode": bool(candidate["supersedes_candidate_id"] or candidate["supersedes_queue_id"]),
        "limitari": [
            "Intrarea construiește un candidat revizuibil, nu verdict juridic.",
            "Editarea păstrează istoricul printr-un candidat nou; rândurile vechi nu sunt mutate.",
        ],
    }


def validate(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("Candidat de regulă incomplet.")
    if request.get("contract") == CONTRACT:
        persisted = (
            REQUIRED
            | OPTIONAL_FIELDS
            | {
                "contract",
                "status",
                "candidate_id",
                "text_sha256",
                "limitations",
            }
        )
        if set(request) - persisted:
            raise ValueError("Câmpuri nepermise în candidatul de regulă.")
        request = {key: request[key] for key in REQUIRED | OPTIONAL_FIELDS if key in request}
    if not REQUIRED.issubset(request):
        raise ValueError("Candidat de regulă incomplet.")
    extra = set(request) - (REQUIRED | OPTIONAL_FIELDS)
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
        "source_url": _text(request.get("source_url", ""), 1000),
        "text": text,
        "modality": modality,
        "review_state": review_state,
        "actor": _text(request.get("actor"), 300),
        "condition": _text(request.get("condition"), 1200),
        "action": _text(request.get("action"), 1200),
        "deadline": _text(request.get("deadline"), 300),
        "exceptions": list(_exceptions(request.get("exceptions"))),
        "effect": _text(request.get("effect"), 1200),
        "applicability_scope": _text(request.get("applicability_scope", ""), 1200),
        "confidence": _enum(request.get("confidence", "unknown"), CONFIDENCE_LEVELS, "Încredere"),
        "extraction_method": _enum(
            request.get("extraction_method", "manual"), EXTRACTION_METHODS, "Metodă extragere"
        ),
        "origin_kind": _text(request.get("origin_kind", ""), 80),
        "origin_id": _text(request.get("origin_id", ""), 240),
        "reviewer": _text(request.get("reviewer"), 160),
        "supersedes_candidate_id": _candidate_ref(
            request.get("supersedes_candidate_id", ""), "Candidat anterior"
        ),
        "supersedes_queue_id": _candidate_ref(
            request.get("supersedes_queue_id", ""), "Rând anterior"
        ),
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
    if normalized["supersedes_candidate_id"] or normalized["supersedes_queue_id"]:
        limitations.append("Acest candidat este o editare auditată a unui candidat anterior.")

    return RuleCandidate(
        contract=CONTRACT,
        status=status,
        candidate_id=_candidate_id(normalized),
        provision_id=normalized["provision_id"],
        act_id=normalized["act_id"],
        locator=normalized["locator"],
        text=text,
        modality=modality,
        review_state=review_state,
        text_sha256=_sha(text),
        source_hash=normalized["source_hash"],
        source_url=normalized["source_url"],
        actor=normalized["actor"],
        condition=normalized["condition"],
        action=normalized["action"],
        deadline=normalized["deadline"],
        exceptions=tuple(normalized["exceptions"]),
        effect=normalized["effect"],
        applicability_scope=normalized["applicability_scope"],
        confidence=normalized["confidence"],
        extraction_method=normalized["extraction_method"],
        origin_kind=normalized["origin_kind"],
        origin_id=normalized["origin_id"],
        reviewer=normalized["reviewer"],
        supersedes_candidate_id=normalized["supersedes_candidate_id"],
        supersedes_queue_id=normalized["supersedes_queue_id"],
        limitations=tuple(limitations),
    ).to_dict()
