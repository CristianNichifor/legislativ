"""Final product acceptance/status gate for user-visible app completeness.

This report is deliberately stricter than the v1 vertical acceptance runner:
bounded workflows may be usable while the whole product is still incomplete.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from scripts import acceptance_dashboard, final_v1_acceptance

CONTRACT = "app-completeness-gate-v1"
REQUIRED_CAPABILITIES = (
    "local_data_separation",
    "public_source_data_availability",
    "dossier_workflow",
    "matrix_to_dossier",
    "lifecycle_tracking",
    "eu_issue_note",
    "ai_mcp_bounded_draft",
    "export_backup_restore",
    "no_hidden_legal_verdicts",
)


class AppCompletenessError(RuntimeError):
    """The app must not be described as complete yet."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (_repo_root() / rel).read_text(encoding="utf-8")


def _has_all(text: str, needles: tuple[str, ...]) -> bool:
    return all(needle in text for needle in needles)


def _capability(
    key: str,
    label: str,
    state: str,
    evidence: str,
    *,
    checks: dict[str, bool],
    blockers: list[str] | None = None,
    next_action: str = "",
) -> dict:
    if key not in REQUIRED_CAPABILITIES:
        raise ValueError(f"Unknown app completeness capability: {key}")
    if state not in {"ready", "partial", "missing"}:
        raise ValueError(f"Invalid app completeness state: {state}")
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "key": key,
        "label": label,
        "required": True,
        "state": "missing" if failed and state == "ready" else state,
        "evidence": evidence,
        "checks": checks,
        "failed_checks": failed,
        "blockers": blockers or failed,
        "next_action": next_action,
    }


def _vertical_flow() -> tuple[dict, str | None]:
    try:
        with tempfile.TemporaryDirectory(prefix="legislativ-completeness-") as tmp:
            return final_v1_acceptance.run(Path(tmp)), None
    except Exception as exc:  # pragma: no cover - exercised through failed reports
        return {}, str(exc)


def _source_summary(stare) -> dict:
    if stare is None:
        root = Path(tempfile.gettempdir()) / "legislativ-app-completeness-empty-state"
        stare = SimpleNamespace(
            corpus=root / "corpus.db",
            initiative=root / "initiative.db",
            graf=root / "graf.db",
            eu=root / "eu.db",
            date_dir=None,
        )
    try:
        return acceptance_dashboard.raport(stare)
    except Exception as exc:  # pragma: no cover - defensive status reporting
        return {
            "status": "blocked",
            "capability_summary": {"ready": 0, "partial": 0, "missing": 1, "total": 1},
            "sections": [],
            "capabilities": [],
            "source_coverage": {"blockers": [{"message": str(exc)}]},
        }


def report(stare=None) -> dict:
    dashboard = _source_summary(stare)
    vertical, vertical_error = _vertical_flow()
    vertical_checks = vertical.get("checks") or {}
    source_coverage = dashboard.get("source_coverage") or {}
    missing_required = source_coverage.get("missing_required", 0)
    attention_sources = source_coverage.get("attention_sources", 0)

    date_locale = _read("scripts/date_locale.py")
    private_boundaries = _read("docs/private-data-boundaries.md")
    browser_workspaces = _read("docs/browser-workspaces.md")
    app_html = _read("app/index.html")
    browser_workspace = _read("app/browser-workspace.js")
    note_ue = _read("scripts/note_ue.py")
    ai_drafting = _read("scripts/ai_drafting.py")
    mcp_ai = _read("scripts/mcp_ai_draft.py")
    dosare = _read("scripts/dosare.py")
    law_rule_drafts = _read("scripts/law_rule_drafts.py")
    tests = "\n".join(
        _read(path)
        for path in (
            "tests/test_dossier_usability.py",
            "tests/test_note_ue.py",
            "tests/test_ai_drafting.py",
            "tests/test_mcp_ai_draft.py",
        )
    )

    source_ready = missing_required == 0 and attention_sources == 0
    vertical_ready = bool(vertical) and not vertical_error and all(vertical_checks.values())
    capabilities = [
        _capability(
            "local_data_separation",
            "Local data separation",
            "ready",
            (
                "Public datasets, private dossier storage and browser-local workspace "
                "boundaries are documented and implemented."
            ),
            checks={
                "public_private_dirs": _has_all(
                    date_locale, ("datasets", "staging", "private", "CORE_COLUMNS")
                ),
                "private_boundary_doc": _has_all(
                    private_boundaries, ("private/dosare.db", "public", "private")
                ),
                "browser_private_workspace": _has_all(
                    browser_workspaces, ("IndexedDB", "private SQLite", "export")
                ),
            },
        ),
        _capability(
            "public_source_data_availability",
            "Public source data availability",
            "ready" if source_ready else "partial",
            (
                "Source portfolio and availability dashboard exist, but the current runtime "
                "must have every required source family present and out of attention state."
            ),
            checks={
                "source_dashboard_available": dashboard.get("contract")
                == "acceptance-dashboard-v1",
                "no_required_family_missing": missing_required == 0,
                "no_required_source_attention": attention_sources == 0,
            },
            blockers=[
                blocker.get("message", blocker.get("kind", "source coverage blocker"))
                for blocker in source_coverage.get("blockers", [])
            ],
            next_action=(
                "Populate/sync every required public source family and clear attention states."
            ),
        ),
        _capability(
            "dossier_workflow",
            "Dossier workflow",
            "ready" if vertical_ready else "missing",
            (
                "The vertical runner creates a dossier, saves a source-backed note and "
                "assembles an evidence pack."
            ),
            checks={
                "vertical_runner_passed": vertical_ready,
                "note_and_events_present": vertical_checks.get(
                    "evidence_pack_has_note_and_events", False
                ),
                "dossier_ui_mounted": _has_all(
                    app_html, ('id="dossier-writing"', "bindWritingWorkspace(meta)")
                ),
            },
            blockers=[vertical_error] if vertical_error else [],
        ),
        _capability(
            "matrix_to_dossier",
            "Matrix-to-dossier",
            "ready" if vertical_checks.get("matrix_has_drilldown") else "missing",
            (
                "The final vertical flow proves matrix drilldown can feed the same dossier "
                "evidence path."
            ),
            checks={
                "matrix_drilldown_contract": vertical_checks.get("matrix_has_drilldown", False),
                "workflow_export_step_visible": "data-workflow-open-export" in app_html,
            },
            blockers=[vertical_error] if vertical_error else [],
        ),
        _capability(
            "lifecycle_tracking",
            "Lifecycle tracking",
            "partial",
            (
                "Local source registry, tracker events and parliamentary lifecycle stages "
                "exist; full lifecycle coverage depends on complete source availability."
            ),
            checks={
                "tracker_project_flow": vertical_checks.get("workbench_tracks_project", False),
                "lifecycle_ui_available": "source-coverage-open-lifecycle" in app_html,
                "source_coverage_complete": source_ready,
            },
            blockers=[
                "Lifecycle tracking is bounded until public-source coverage is complete "
                "and current."
            ],
            next_action="Run the public-source coverage gate against the deployed local data set.",
        ),
        _capability(
            "eu_issue_note",
            "EU issue note",
            "ready",
            (
                "EU issue notes are source-backed, local-only, hash-preserving and "
                "explicitly non-verdict."
            ),
            checks={
                "note_contract": "ro-eu-issue-note-v1" in note_ue,
                "legal_effect_unknown": '"legal_effect": "unknown"' in note_ue,
                "tested_source_backed": "test_preview_is_source_backed_read_only" in tests,
            },
        ),
        _capability(
            "ai_mcp_bounded_draft",
            "AI/MCP bounded draft",
            "ready",
            (
                "AI and MCP draft paths produce bounded prompts from selected evidence "
                "and require explicit user action."
            ),
            checks={
                "server_never_calls_model": "server_calls_model" in ai_drafting
                and "False" in ai_drafting,
                "mcp_no_execute": "mcp_executes_now" in mcp_ai and "False" in mcp_ai,
                "bounded_export_manifest": "bounded-evidence-export-manifest-v1" in tests,
            },
        ),
        _capability(
            "export_backup_restore",
            "Export, backup and restore",
            "ready",
            (
                "Dossier SQLite backup, browser export/import/restore and historical "
                "export preservation are implemented and tested."
            ),
            checks={
                "sqlite_backup_api": "def backup" in dosare,
                "browser_export_restore": _has_all(
                    browser_workspace, ("Exporta backup SQLite", "Restaureaza copia")
                ),
                "backup_tests": _has_all(tests, ("backup", "restore", "export")),
            },
        ),
        _capability(
            "no_hidden_legal_verdicts",
            "No hidden legal verdicts",
            "ready",
            (
                "Visible contracts preserve unknown legal effect, human review status and "
                "non-verdict notices."
            ),
            checks={
                "eu_note_non_verdict": "Nu este verdict juridic" in tests,
                "ai_non_verdict_notice": "Ciornă de lucru; nu verdict juridic" in ai_drafting,
                "rule_draft_non_verdict": "draft_rule_not_legal_verdict" in law_rule_drafts,
            },
        ),
    ]
    by_state = {
        state: sum(1 for item in capabilities if item["state"] == state)
        for state in ("ready", "partial", "missing")
    }
    blocking = [item for item in capabilities if item["state"] != "ready"]
    failed_checks = [
        {"capability": item["key"], "check": check}
        for item in capabilities
        for check in item["failed_checks"]
    ]
    return {
        "contract": CONTRACT,
        "status": "ready" if not blocking and not failed_checks else "blocked",
        "completion_claim_allowed": not blocking and not failed_checks,
        "required_capabilities": len(REQUIRED_CAPABILITIES),
        "summary": {**by_state, "total": len(capabilities)},
        "capabilities": capabilities,
        "blocking_capabilities": [
            {
                "key": item["key"],
                "state": item["state"],
                "blockers": item["blockers"],
                "next_action": item["next_action"],
            }
            for item in blocking
        ],
        "failed_checks": failed_checks,
        "vertical_acceptance": {
            "status": vertical.get("status", "failed" if vertical_error else "unknown"),
            "contract": vertical.get("contract"),
            "error": vertical_error,
            "checks": vertical_checks,
            "summary": vertical.get("summary", {}),
        },
        "source_status": {
            "status": source_coverage.get("status"),
            "missing_required": missing_required,
            "attention_sources": attention_sources,
            "blockers": source_coverage.get("blockers", []),
        },
        "visible_in": {
            "docs": "docs/APP_COMPLETENESS.md",
            "ui": "/api/app-completeness via Stadiu finalizare",
            "cli": "python -m scripts.app_completeness --require-complete",
        },
        "limitari": [
            "This gate reports current evidence; it does not fetch public sources or call AI/MCP.",
            "Partial capabilities block a completion claim even when bounded workflows pass.",
            "Legal correctness, recall and compliance remain human/domain acceptance questions.",
        ],
    }


def assert_complete(data: dict) -> None:
    if data.get("completion_claim_allowed"):
        return
    parts = []
    for item in data.get("blocking_capabilities", []):
        blockers = "; ".join(item.get("blockers") or ["no evidence"])
        parts.append(f"{item['key']}={item['state']} ({blockers})")
    if data.get("failed_checks"):
        failed = ", ".join(
            f"{item['capability']}.{item['check']}" for item in data["failed_checks"]
        )
        parts.append(f"failed_checks={failed}")
    raise AppCompletenessError("App completeness gate blocked: " + " | ".join(parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report final app completeness status")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero when any required capability is partial or missing.",
    )
    args = parser.parse_args(argv)
    data = report()
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_complete:
        try:
            assert_complete(data)
        except AppCompletenessError:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
