"""Legislative project lifecycle states shared by source acquisition and watchlists.

The public portals do not use one stable vocabulary. This module keeps the app honest by mapping
known status labels to a bounded lifecycle and by marking missing/new labels as unavailable or
unknown instead of guessing.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
DEFAULT_STALE_DAYS = 30
MAX_PROJECTS = 100
REGISTRY_ATTENTION_STATES = frozenset({"changed", "failed", "needs_review", "rate_limited"})
PROJECT_REGISTRY_FAMILIES = frozenset({"parlament", "camera", "senat"})

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


def _readonly(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    budget = 0

    def stop():
        nonlocal budget
        budget += 1
        return budget > 20_000

    con.set_progress_handler(stop, 10_000)
    return con


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    with_timezone = datetime.fromisoformat(text)
    if with_timezone.tzinfo is None:
        return with_timezone.replace(tzinfo=UTC)
    return with_timezone.astimezone(UTC)


def _is_stale(last_seen: str | None, *, now: datetime, stale_days: int) -> bool:
    try:
        parsed = _parse_time(last_seen)
    except ValueError:
        return True
    return parsed is None or parsed < now - timedelta(days=stale_days)


def _project_url(row: dict) -> str:
    url = row.get("sursa_url") or ""
    if url:
        return url
    cam, idp = row.get("cam"), row.get("idp")
    if cam in (1, 2) and idp and str(idp).isdigit():
        return f"https://www.cdep.ro/pls/proiecte/upl_pck2015.proiect?cam={cam}&idp={idp}"
    return ""


def project_lifecycle_item(
    row: dict,
    *,
    registry: dict | None = None,
    now: datetime | None = None,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> dict:
    """Public lifecycle/status shape for one project row from a source registry."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    lifecycle = normalize_stage_label(row.get("stadiu"))
    last_seen = row.get("citit_la") or ""
    stale = _is_stale(last_seen, now=now, stale_days=stale_days)
    url = _project_url(row)
    source_state = "ok"
    if not url or lifecycle["key"] == "unavailable":
        source_state = "unavailable"
    elif lifecycle["key"] == "unknown":
        source_state = "unknown"
    elif stale:
        source_state = "stale"
    registry = registry or {}
    registry_state = registry.get("state") or ""
    return {
        "source_name": row.get("source_name") or "Camera Deputaților",
        "project_id": row.get("plx_id") or "",
        "title": row.get("titlu") or "",
        "status": row.get("stadiu") or "",
        "stage": lifecycle,
        "last_seen": last_seen,
        "last_updated": row.get("data_inreg") or last_seen,
        "consultation_deadline": row.get("consultation_deadline"),
        "url": url,
        "source_state": source_state,
        "registry_source": registry,
        "registry_source_id": registry.get("id") or "",
        "registry_source_state": registry_state,
        "registry_needs_attention": registry_state in REGISTRY_ATTENTION_STATES,
        "registry_can_sync": bool(registry.get("id"))
        and registry.get("family") in PROJECT_REGISTRY_FAMILIES,
        "stale": stale,
        "unavailable": source_state == "unavailable",
        "needs_attention": source_state in {"stale", "unknown", "unavailable"}
        or registry_state in REGISTRY_ATTENTION_STATES,
    }


def _project_registry_sources(stare, identifiers: list[str]) -> dict[str, dict]:
    from scripts import source_registry

    path = source_registry.cale(stare)
    if not identifiers or not path.exists():
        return {}
    try:
        with closing(_readonly(path)) as con:
            tables = {
                r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "source_registry" not in tables:
                return {}
            placeholders = ",".join("?" for _ in identifiers)
            rows = [
                dict(r)
                for r in con.execute(
                    "SELECT id,family,identifier,url,label,state,last_hash,parser_version,"
                    "last_attempt_at,last_error FROM source_registry WHERE identifier IN ("
                    + placeholders
                    + ") AND family IN ('parlament','camera','senat') "
                    "ORDER BY updated_at DESC, id",
                    identifiers,
                )
            ]
    except (OSError, sqlite3.Error):
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        current = out.get(row["identifier"])
        if current is None or (
            row["state"] in REGISTRY_ATTENTION_STATES
            and current.get("state") not in REGISTRY_ATTENTION_STATES
        ):
            out[row["identifier"]] = row
    return out


def project_lifecycle_summary(
    stare,
    *,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    stale_days: int = DEFAULT_STALE_DAYS,
    now: datetime | None = None,
) -> dict:
    """Return a bounded lifecycle status feed from the local parliamentary initiative store."""
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Căutare prea lungă.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PROJECTS:
        raise ValueError("Limită invalidă.")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 100_000:
        raise ValueError("Pagină invalidă.")
    if (
        not isinstance(stale_days, int)
        or isinstance(stale_days, bool)
        or not 1 <= stale_days <= 3660
    ):
        raise ValueError("Interval de actualitate invalid.")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    base = {
        "mod": "local",
        "source_name": "Camera Deputaților",
        "source_status": "unavailable",
        "generated_at": now.isoformat(),
        "stale_after_days": stale_days,
        "total": 0,
        "returned": 0,
        "projects": [],
        "stale": 0,
        "unknown_stage": 0,
        "unavailable": 0,
        "limitari": [],
    }
    try:
        needle = (
            "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        with closing(_readonly(stare.initiative)) as con:
            tables = {
                r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "initiative" not in tables:
                base["limitari"].append("Registrul inițiativelor nu este instalat.")
                return base
            where = "WHERE plx_id LIKE ? ESCAPE '\\' OR titlu LIKE ? ESCAPE '\\'"
            base["total"] = con.execute(
                "SELECT count(*) FROM initiative " + where,
                (needle, needle),
            ).fetchone()[0]
            rows = [
                dict(r)
                for r in con.execute(
                    "SELECT plx_id, titlu, stadiu, citit_la, data_inreg, sursa_url, cam, idp "
                    "FROM initiative " + where + " ORDER BY citit_la DESC, plx_id LIMIT ? OFFSET ?",
                    (needle, needle, limit + 1, offset),
                )
            ]
    except (OSError, sqlite3.Error):
        base["limitari"].append("Registrul inițiativelor nu este disponibil.")
        return base
    visible_rows = rows[:limit]
    registry = _project_registry_sources(stare, [row.get("plx_id", "") for row in visible_rows])
    projects = [
        project_lifecycle_item(
            row, registry=registry.get(row.get("plx_id", "")), now=now, stale_days=stale_days
        )
        for row in visible_rows
    ]
    base["projects"] = projects
    base["returned"] = len(projects)
    base["mai_multe"] = len(rows) > limit
    base["stale"] = sum(1 for project in projects if project["stale"])
    base["unknown_stage"] = sum(1 for project in projects if project["stage"]["key"] == "unknown")
    base["unavailable"] = sum(1 for project in projects if project["unavailable"])
    if projects:
        if base["unavailable"]:
            base["source_status"] = "partial"
        elif base["unknown_stage"]:
            base["source_status"] = "needs_review"
        elif base["stale"]:
            base["source_status"] = "stale"
        else:
            base["source_status"] = "ok"
    else:
        base["source_status"] = "empty"
    return base
