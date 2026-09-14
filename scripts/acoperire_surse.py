"""Operational coverage summary for local legal-source tracking."""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from scripts import source_portfolio, source_registry
from scripts.lifecycle import DEFAULT_STALE_DAYS, project_lifecycle_item

REQUIRED_FAMILIES = (
    "legislatie_ro",
    "parlament",
    "camera",
    "senat",
    "consultare_guvern",
    "consultare_econsultare",
    "consultare_minister",
    "monitorul_oficial",
    "monitorul_oficial_pi",
    "ccr",
    "avize",
    "ue_cellar",
)
OPTIONAL_CONTROL_FAMILIES = (
    "monitorul_oficial_local",
    "monitorul_oficial_other_parts",
)
CONTROL_FAMILIES = REQUIRED_FAMILIES + OPTIONAL_CONTROL_FAMILIES
ATTENTION = source_registry.ATTENTION_STATES
READY_STATES = frozenset({"unchanged"})
INCOMPLETE_STATES = frozenset({"discovered", "queued", "fetched"})
BLOCKING_STATES = ATTENTION | frozenset({"unavailable"})
FETCHED_STATES = frozenset({"fetched", "unchanged", "changed", "needs_review"})
FAILED_STATES = frozenset({"failed", "unavailable", "rate_limited"})


def _is_available_bootstrap_anchor(state: str, identifier: str) -> bool:
    return identifier.startswith(source_registry.BOOTSTRAP_ANCHOR_PREFIX) and state in {
        "changed",
        "unchanged",
    }


def _portfolio_summary(families: list[dict]) -> dict:
    by_family = {row["family"]: row for row in families}
    contract = source_portfolio.portfolio()
    items = []
    for row in contract["families"]:
        coverage = by_family.get(row["key"])
        if row["key"] in REQUIRED_FAMILIES:
            tier = "required"
        elif row["key"] in {"monitorul_oficial_other_parts", "monitorul_oficial_local"}:
            tier = "deferred"
        else:
            tier = "planned"
        items.append(
            {
                "key": row["key"],
                "label": row["label"],
                "priority": row["priority"],
                "tier": tier,
                "ingest_policy": row["ingest_policy"],
                "purpose": row["purpose"],
                "first_slice": row["first_slice"],
                "rough_gb_min": row["rough_gb_min"],
                "rough_gb_max": row["rough_gb_max"],
                "coverage_status": coverage["status"] if coverage else "missing",
                "tracked_sources": coverage["total"] if coverage else 0,
                "attention_sources": coverage["attention"] if coverage else 0,
            }
        )
    return {
        "contract": "source-portfolio-v1",
        "families": items,
        "monitorul_oficial_policy": contract["monitorul_oficial_policy"],
        "storage_estimates": {
            profile: source_portfolio.estimate_storage(profile)
            for profile in ("v1", "serious", "everything")
        },
    }


def _source_family_summary(stare) -> tuple[list[dict], list[str]]:
    labels = source_registry.families()
    counts: Counter[tuple[str, str]] = Counter()
    evidence_counts = _parliamentary_evidence_by_family(stare)
    total_by_family: Counter[str] = Counter()
    checked_by_family: dict[str, str] = {}
    limitations = []
    path = source_registry.cale(stare)
    if path.exists():
        try:
            with closing(source_registry._open(path)) as con:
                source_registry.init(con)
                rows = con.execute("SELECT family,state,identifier FROM source_registry")
                for row in rows:
                    state = row["state"]
                    identifier = row["identifier"] or ""
                    coverage_state = (
                        "unchanged" if _is_available_bootstrap_anchor(state, identifier) else state
                    )
                    counts[(row["family"], coverage_state)] += 1
                    total_by_family[row["family"]] += 1
                for row in con.execute(
                    "SELECT family,max(last_attempt_at) checked FROM source_registry "
                    "WHERE last_attempt_at IS NOT NULL AND last_attempt_at != '' "
                    "GROUP BY family"
                ):
                    checked_by_family[row["family"]] = row["checked"] or ""
        except (OSError, sqlite3.Error):
            limitations.append("Registrul surselor nu este disponibil.")
    else:
        limitations.append("Registrul surselor nu este inițializat.")
    families = []
    for family in CONTROL_FAMILIES:
        states = {
            state: counts[(family, state)]
            for state in sorted(source_registry.SYNC_STATES)
            if counts[(family, state)]
        }
        total = total_by_family[family]
        attention = sum(counts[(family, state)] for state in BLOCKING_STATES)
        ready = sum(counts[(family, state)] for state in READY_STATES)
        incomplete = sum(counts[(family, state)] for state in INCOMPLETE_STATES)
        fetched = sum(counts[(family, state)] for state in FETCHED_STATES)
        failed = sum(counts[(family, state)] for state in FAILED_STATES)
        status = (
            "missing"
            if not total
            else "attention"
            if attention
            else "unsynced"
            if incomplete and not ready
            else "ok"
        )
        row = {
            "family": family,
            "label": labels.get(family, family),
            "required": family in REQUIRED_FAMILIES,
            "support": _family_support(family),
            "total": total,
            "attention": attention,
            "ready": ready,
            "incomplete": incomplete,
            "fetched": fetched,
            "changed": counts[(family, "changed")],
            "failed": failed,
            "parliamentary_evidence_counts": evidence_counts.get(family, _empty_evidence_counts()),
            "last_checked": checked_by_family.get(family, ""),
            "next_action": _family_next_action(
                status=status,
                family=family,
                attention=attention,
                failed=failed,
                incomplete=incomplete,
                total=total,
            ),
            "states": states,
            "status": status,
        }
        row["actions"] = _family_actions(row)
        families.append(row)
    for family in sorted(set(total_by_family) - set(CONTROL_FAMILIES)):
        status = "attention" if sum(counts[(family, state)] for state in BLOCKING_STATES) else "ok"
        failed = sum(counts[(family, state)] for state in FAILED_STATES)
        incomplete = sum(counts[(family, state)] for state in INCOMPLETE_STATES)
        row = {
            "family": family,
            "label": labels.get(family, family),
            "required": False,
            "support": _family_support(family),
            "total": total_by_family[family],
            "attention": sum(counts[(family, state)] for state in BLOCKING_STATES),
            "ready": sum(counts[(family, state)] for state in READY_STATES),
            "incomplete": incomplete,
            "fetched": sum(counts[(family, state)] for state in FETCHED_STATES),
            "changed": counts[(family, "changed")],
            "failed": failed,
            "parliamentary_evidence_counts": evidence_counts.get(family, _empty_evidence_counts()),
            "last_checked": checked_by_family.get(family, ""),
            "next_action": _family_next_action(
                status=status,
                family=family,
                attention=sum(counts[(family, state)] for state in BLOCKING_STATES),
                failed=failed,
                incomplete=incomplete,
                total=total_by_family[family],
            ),
            "states": {
                state: counts[(family, state)]
                for state in sorted(source_registry.SYNC_STATES)
                if counts[(family, state)]
            },
            "status": status,
        }
        row["actions"] = _family_actions(row)
        families.append(row)
    return families, limitations


def _empty_evidence_counts() -> dict:
    return {
        "documents": 0,
        "reports": 0,
        "votes": 0,
        "avize": 0,
        "unavailable_documents": 0,
    }


def _evidence_kind(label: str) -> str:
    folded = label.casefold()
    if "raport" in folded:
        return "reports"
    if "aviz" in folded or "punct de vedere" in folded:
        return "avize"
    if "vot" in folded or "voturi" in folded:
        return "votes"
    return "documents"


def _parliament_family_from_project(row: dict) -> str:
    if row.get("cam") == 1:
        return "senat"
    if row.get("cam") == 2:
        return "camera"
    return "parlament"


def _parliamentary_evidence_by_family(stare) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def bucket(family: str) -> dict:
        return out.setdefault(family, _empty_evidence_counts())

    try:
        from scripts import documente_proiecte, tracker_events
        from scripts.text import cheie

        initiative_family: dict[str, str] = {}
        initiative_path = (
            Path(getattr(stare, "initiative", "")) if getattr(stare, "initiative", None) else None
        )
        if initiative_path and initiative_path.exists():
            with closing(
                sqlite3.connect(initiative_path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as con:
                con.row_factory = sqlite3.Row
                tables = {
                    r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "initiative" in tables:
                    initiative_family = {
                        row["plx_id"]: _parliament_family_from_project(dict(row))
                        for row in con.execute("SELECT plx_id, cam FROM initiative")
                    }

        documents_path = documente_proiecte.cale_store(stare)
        if documents_path.exists():
            with closing(
                sqlite3.connect(documents_path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as con:
                con.row_factory = sqlite3.Row
                tables = {
                    r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "document_links" in tables:
                    for row in con.execute("SELECT plx_id, label, url, status FROM document_links"):
                        family = initiative_family.get(row["plx_id"], "parlament")
                        counts = bucket(family)
                        counts["documents"] += 1
                        label = cheie((row["label"] or "") + " " + (row["url"] or ""))
                        kind = _evidence_kind(label)
                        if kind != "documents":
                            counts[kind] += 1
                        if row["status"] == "unavailable":
                            counts["unavailable_documents"] += 1

        tracker_path = tracker_events.cale(stare)
        if tracker_path.exists():
            with closing(
                sqlite3.connect(tracker_path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as con:
                con.row_factory = sqlite3.Row
                tables = {
                    r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "tracker_events" in tables:
                    for row in con.execute(
                        "SELECT source_family,event_type,count(*) total FROM tracker_events "
                        "GROUP BY source_family,event_type"
                    ):
                        family = row["source_family"] or "parlament"
                        if family not in {"camera", "senat", "parlament", "avize"}:
                            continue
                        counts = bucket(family)
                        if row["event_type"] == "report_filed":
                            counts["reports"] += row["total"]
                        elif row["event_type"] == "vote_recorded":
                            counts["votes"] += row["total"]
                        elif row["event_type"] in {"opinion_received", "opinion_requested"}:
                            counts["avize"] += row["total"]
    except (OSError, sqlite3.Error, ValueError, AttributeError):
        return out
    return out


def _family_support(family: str) -> dict:
    if family == "monitorul_oficial_other_parts":
        return {
            "state": "metadata_only",
            "label": "Metadate/selectiv",
            "policy": "Părțile II-VII nu sunt ingestate integral implicit.",
        }
    if family == "monitorul_oficial_local":
        return {
            "state": "metadata_only",
            "label": "Metadate + pachete opt-in",
            "policy": (
                "Monitorul Oficial Local pornește din registru și pachete alese de utilizator."
            ),
        }
    if family in source_registry.FAMILIES:
        return {
            "state": "supported",
            "label": "Suportată",
            "policy": "Poate fi urmărită incremental în registrul local.",
        }
    return {
        "state": "unsupported",
        "label": "Nesuportată",
        "policy": "Familia nu are încă flux local de urmărire.",
    }


def _family_actions(row: dict) -> list[dict]:
    family = row["family"]
    actions = [
        {
            "key": "add_source",
            "label": "Adaugă sursă",
            "target": family,
            "enabled": True,
        },
        {
            "key": "open_family",
            "label": "Deschide familia",
            "target": family,
            "enabled": True,
        },
    ]
    if row["total"]:
        actions.append(
            {
                "key": "sync_selected",
                "label": "Sincronizează sursa selectată",
                "target": family,
                "enabled": True,
            }
        )
    if row["failed"]:
        actions.append(
            {
                "key": "retry_failures",
                "label": "Reîncearcă eșuate",
                "target": family,
                "enabled": True,
            }
        )
    if row["attention"] or row["status"] in {"missing", "unsynced"}:
        actions.append(
            {
                "key": "create_note",
                "label": "Creează notă din lipsă/eșec",
                "target": family,
                "enabled": True,
            }
        )
    if row["attention"]:
        actions.append(
            {
                "key": "parser_details",
                "label": "Detalii parser/eșec",
                "target": family,
                "enabled": True,
            }
        )
    return actions


def _family_next_action(
    *,
    status: str,
    family: str,
    attention: int,
    failed: int,
    incomplete: int,
    total: int,
) -> str:
    if status == "missing":
        return "Adaugă o sursă oficială sau pornește ancorele oficiale de bază."
    if failed:
        return "Deschide rândurile eșuate, reîncearcă sursa selectată sau creează notă în dosar."
    if attention:
        return "Inspectează rândurile schimbate sau de revizuit înainte de redactare."
    if incomplete:
        return "Sincronizează rânduri selectate până au stare locală verificată."
    if not total:
        return "Adaugă o sursă când familia devine relevantă pentru dosar."
    if family in {"monitorul_oficial_local", "monitorul_oficial_other_parts"}:
        return "Păstrează metadate întâi; documentele se cer explicit de utilizator."
    return "Acoperirea este utilizabilă local cu limitările afișate."


def _project_stage_summary(stare, *, now: datetime, stale_days: int) -> tuple[dict, list[str]]:
    path = Path(stare.initiative)
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
    unsynced = [row for row in families if row["required"] and row["status"] == "unsynced"]
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
    blockers.extend(
        {
            "kind": "source_unsynced",
            "family": row["family"],
            "label": row["label"],
            "message": f"{row['incomplete']} surse nu au încă sync reușit în {row['label']}.",
        }
        for row in unsynced
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
        "unsynced_required": len(unsynced),
        "unsynced_sources": sum(row["incomplete"] for row in unsynced),
        "blockers": blockers,
        "portfolio": _portfolio_summary(families),
        "status": "blocked" if missing or blockers else "ok",
        "limitari": limitations + project_limitations,
    }
