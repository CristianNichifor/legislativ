"""Legislative project lifecycle states shared by source acquisition and watchlists.

The public portals do not use one stable vocabulary. This module keeps the app honest by mapping
known status labels to a bounded lifecycle and by marking missing/new labels as unavailable or
unknown instead of guessing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from scripts.text import cheie


@dataclass(frozen=True)
class LifecycleStage:
    key: str
    label: str
    order: int
    terminal: bool = False
    available: bool = True
    known: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


STAGES: tuple[LifecycleStage, ...] = (
    LifecycleStage("consultation_announced", "public consultation announced", 10),
    LifecycleStage("consultation_open", "consultation open", 20),
    LifecycleStage("consultation_closed", "consultation closed", 30),
    LifecycleStage("drafting", "drafting", 40),
    LifecycleStage("government_adopted", "government adopted", 50),
    LifecycleStage("sent_to_parliament", "sent to Parliament", 60),
    LifecycleStage("registered", "registered", 70),
    LifecycleStage("committee", "committee", 80),
    LifecycleStage("report", "report", 90),
    LifecycleStage("plenary_scheduled", "plenary scheduled", 100),
    LifecycleStage("adopted", "adopted", 110, terminal=True),
    LifecycleStage("rejected", "rejected", 120, terminal=True),
    LifecycleStage("promulgated", "promulgated", 130, terminal=True),
    LifecycleStage("published", "published", 140, terminal=True),
    LifecycleStage("withdrawn_archived", "withdrawn/archived", 150, terminal=True),
    LifecycleStage("unknown", "unknown", 900, known=False),
    LifecycleStage("unavailable", "unavailable", 910, available=False, known=False),
)

_BY_KEY = {stage.key: stage for stage in STAGES}

ACTIVE_STAGE_KEYS = frozenset(
    stage.key for stage in STAGES if stage.available and stage.known and not stage.terminal
)
TERMINAL_STAGE_KEYS = frozenset(stage.key for stage in STAGES if stage.terminal)

_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "consultation_announced",
        (
            "anunt consultare publica",
            "anunt dezbatere publica",
            "transparenta decizionala anunt",
            "consultare publica anuntata",
        ),
    ),
    (
        "consultation_open",
        (
            "consultare publica deschisa",
            "dezbatere publica deschisa",
            "in consultare publica",
            "afisat pentru consultare",
            "supus consultarii publice",
        ),
    ),
    (
        "consultation_closed",
        (
            "consultare publica inchisa",
            "dezbatere publica inchisa",
            "termen consultare expirat",
            "consultare publica finalizata",
        ),
    ),
    (
        "drafting",
        (
            "in lucru la minister",
            "in elaborare",
            "elaborare proiect",
            "avizare interministeriala",
            "minister",
        ),
    ),
    (
        "government_adopted",
        (
            "adoptat de guvern",
            "aprobat de guvern",
            "hotarare guvern adoptata",
            "ordonanta adoptata de guvern",
        ),
    ),
    (
        "sent_to_parliament",
        (
            "transmis la parlament",
            "trimis parlamentului",
            "depus la parlament",
            "inaintat parlamentului",
        ),
    ),
    (
        "registered",
        (
            "inregistrat",
            "inregistrata",
            "prezentat biroului permanent",
            "pl x",
            "plx",
            "bpi",
        ),
    ),
    (
        "report",
        (
            "raport depus",
            "raport favorabil",
            "raport de respingere",
            "raport comun",
            "raport inlocuitor",
        ),
    ),
    (
        "plenary_scheduled",
        (
            "pe ordinea de zi",
            "plen",
            "sedinta plenului",
            "programat pentru dezbatere",
            "dezbatere in plen",
        ),
    ),
    (
        "committee",
        (
            "la comisii",
            "trimis pentru raport",
            "trimisa pentru raport",
            "trimis pentru aviz",
            "trimisa pentru aviz",
            "sesizare comisie",
            "comisia",
        ),
    ),
    (
        "adopted",
        (
            "vot final adoptat",
            "adoptat definitiv",
            "adoptata definitiv",
            "adoptat de camera decizionala",
            "adoptata de camera decizionala",
            "camera decizionala adoptat",
        ),
    ),
    (
        "rejected",
        (
            "respins",
            "respinsa",
            "respins definitiv",
            "vot final respins",
        ),
    ),
    (
        "promulgated",
        (
            "promulgat",
            "promulgata",
            "decret de promulgare",
        ),
    ),
    (
        "published",
        (
            "publicat in monitorul oficial",
            "publicata in monitorul oficial",
            "monitorul oficial",
            "lege nr",
        ),
    ),
    (
        "withdrawn_archived",
        (
            "retras",
            "retrasa",
            "clasat",
            "clasata",
            "arhivat",
            "arhivata",
            "procedura incetata",
        ),
    ),
)


def stage(key: str) -> LifecycleStage:
    return _BY_KEY.get(key, _BY_KEY["unknown"])


def normalize_stage_label(label: str | None) -> dict:
    """Return the lifecycle stage for a public-source label.

    Empty values mean the source did not expose a stage. Non-empty values that do not match known
    portal wording are kept as `unknown`, so callers can surface them for parser coverage work.
    """
    if label is None or not str(label).strip():
        return stage("unavailable").to_dict()
    normalized = cheie(str(label))
    for key, phrases in _PHRASES:
        if any(phrase in normalized for phrase in phrases):
            out = stage(key).to_dict()
            out["raw"] = label
            return out
    out = stage("unknown").to_dict()
    out["raw"] = label
    return out


def is_active_stage(label: str | None) -> bool:
    return normalize_stage_label(label)["key"] in ACTIVE_STAGE_KEYS


def watchlist_lifecycle(row: dict) -> dict:
    """Small watchlist payload for one project row without binding to a storage schema."""
    lifecycle = normalize_stage_label(row.get("stadiu"))
    return {
        "plx_id": row.get("plx_id", ""),
        "titlu": row.get("titlu", ""),
        "sursa_url": row.get("sursa_url", ""),
        "citit_la": row.get("citit_la", ""),
        "lifecycle": lifecycle,
        "needs_attention": lifecycle["key"] in {"unknown", "unavailable"},
    }
