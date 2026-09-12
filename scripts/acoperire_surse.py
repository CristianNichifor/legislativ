"""Operational coverage summary for local legal-source tracking."""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime

from scripts import source_registry
from scripts.lifecycle import DEFAULT_STALE_DAYS, project_lifecycle_item

REQUIRED_FAMILIES = (
    "legislatie_ro",
    "parlament",
    "camera",
    "senat",
    "consultare_guvern",
    "consultare_minister",
    "monitorul_oficial",
    "ccr",
    "ue_cellar",
)
ATTENTION = source_registry.ATTENTION_STATES


def _source_family_summary(stare) -> tuple[list[dict], list[str]]:
    labels = source_registry.families()
    counts: Counter[tuple[str, str]] = Counter()
    total_by_family: Counter[str] = Counter()
    limitations = []
    path = source_registry.cale(stare)
    if path.exists():
        try:
            with closing(source_registry._open(path)) as con:
                source_registry.init(con)
                rows = con.execute(
                    "SELECT family,state,count(*) c FROM source_registry GROUP BY family,state"
                )
                for row in rows:
                    counts[(row["family"], row["state"])] = row["c"]
                    total_by_family[row["family"]] += row["c"]
        except (OSError, sqlite3.Error):
            limitations.append("Registrul surselor nu este disponibil.")
    else:
        limitations.append("Registrul surselor nu este inițializat.")
    families = []
    for family in REQUIRED_FAMILIES:
        states = {
            state: counts[(family, state)]
            for state in sorted(source_registry.SYNC_STATES)
            if counts[(family, state)]
        }
        total = total_by_family[family]
        attention = sum(counts[(family, state)] for state in ATTENTION)
        status = "missing" if not total else "attention" if attention else "ok"
        families.append(
            {
                "family": family,
                "label": labels.get(family, family),
                "required": True,
                "total": total,
                "attention": attention,
                "states": states,
                "status": status,
            }
        )
    for family in sorted(set(total_by_family) - set(REQUIRED_FAMILIES)):
        families.append(
            {
                "family": family,
                "label": labels.get(family, family),
                "required": False,
                "total": total_by_family[family],
                "attention": sum(counts[(family, state)] for state in ATTENTION),
                "states": {
                    state: counts[(family, state)]
                    for state in sorted(source_registry.SYNC_STATES)
                    if counts[(family, state)]
                },
                "status": "ok",
            }
        )
    return families, limitations


def _project_stage_summary(stare, *, now: datetime, stale_days: int) -> tuple[dict, list[str]]:
    path = stare.initiative
    if not path.exists():
        return {
            "total": 0,
            "stale": 0,
            "unknown": 0,
            "unavailable": 0,
            "stages": {},
        }, ["Registrul proiectelor parlamentare nu este disponibil."]
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            tables = {
                row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "initiative" not in tables:
                return {
                    "total": 0,
                    "stale": 0,
                    "unknown": 0,
                    "unavailable": 0,
                    "stages": {},
                }, ["Registrul proiectelor parlamentare nu este instalat."]
            rows = [
                dict(row)
                for row in con.execute(
                    "SELECT plx_id,titlu,stadiu,citit_la,data_inreg,sursa_url,cam,idp "
                    "FROM initiative"
                )
            ]
    except (OSError, sqlite3.Error):
        return {
            "total": 0,
            "stale": 0,
            "unknown": 0,
            "unavailable": 0,
            "stages": {},
        }, ["Registrul proiectelor parlamentare nu poate fi citit."]
    stages: Counter[str] = Counter()
    stale = unknown = unavailable = 0
    for row in rows:
        item = project_lifecycle_item(row, now=now, stale_days=stale_days)
        key = item["stage"]["key"]
        label = item["stage"]["label"]
        stages[f"{key}\0{label}"] += 1
        stale += int(item["stale"])
        unknown += int(key == "unknown")
        unavailable += int(item["unavailable"])
    return {
        "total": len(rows),
        "stale": stale,
        "unknown": unknown,
        "unavailable": unavailable,
        "stages": {
            key.split("\0", 1)[0]: {"label": key.split("\0", 1)[1], "total": value}
            for key, value in sorted(stages.items())
        },
    }, []


def raport(stare, *, stale_days: int = DEFAULT_STALE_DAYS, now: datetime | None = None) -> dict:
    if (
        not isinstance(stale_days, int)
        or isinstance(stale_days, bool)
        or not 1 <= stale_days <= 3660
    ):
        raise ValueError("Interval de actualitate invalid.")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    families, limitations = _source_family_summary(stare)
    projects, project_limitations = _project_stage_summary(stare, now=now, stale_days=stale_days)
    missing = [row for row in families if row["required"] and row["status"] == "missing"]
    attention = [row for row in families if row["attention"]]
    blockers = []
    blockers.extend(
        {
            "kind": "missing_family",
            "family": row["family"],
            "label": row["label"],
            "message": f"Lipsește familia de surse: {row['label']}.",
        }
        for row in missing
    )
    blockers.extend(
        {
            "kind": "source_attention",
            "family": row["family"],
            "label": row["label"],
            "message": f"{row['attention']} surse necesită atenție în {row['label']}.",
        }
        for row in attention
    )
    if projects["unknown"]:
        blockers.append(
            {
                "kind": "unknown_stage",
                "message": f"{projects['unknown']} proiecte au etape necunoscute.",
            }
        )
    if projects["stale"]:
        blockers.append(
            {"kind": "stale_project", "message": f"{projects['stale']} proiecte au date vechi."}
        )
    return {
        "generated_at": now.isoformat(),
        "stale_after_days": stale_days,
        "families": families,
        "projects": projects,
        "missing_required": len(missing),
        "attention_sources": sum(row["attention"] for row in families),
        "blockers": blockers,
        "status": "blocked" if missing or blockers else "ok",
        "limitari": limitations + project_limitations,
    }
