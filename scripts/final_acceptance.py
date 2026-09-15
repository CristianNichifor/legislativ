"""Generate the final acceptance report from existing release gates."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts import app_completeness, source_registry

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "FINAL_ACCEPTANCE.md"
PILOT_PACK = ROOT / "data" / "real_pilot_pack.json"
REHEARSAL = ROOT / "docs" / "v1_rehearsal_current.json"
PILOT_ACCEPTANCE = ROOT / "docs" / "v1_acceptance_pilot_2026-09-11.json"
AI_EVAL_SCHEMA = ROOT / "docs" / "ai_eval_schema1.json"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unavailable", "path": str(path.relative_to(ROOT))}
    return data if isinstance(data, dict) else {"status": "invalid", "path": str(path)}


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _runtime_completeness(data_home: str | None, data_channel: str | None, sync_anchors: bool):
    if not data_home:
        return app_completeness.report(), None
    from scripts.local_runtime import DEFAULT_CHANNEL, open_runtime

    with open_runtime(data_home, data_channel or DEFAULT_CHANNEL) as runtime:
        anchor_sync = None
        if sync_anchors:
            anchor_sync = source_registry.executa(
                runtime.manager.current_state, {"action": "sync_bootstrap"}
            )
        return app_completeness.report(runtime.manager.current_state), anchor_sync


EVIDENCE_BASIS = {
    "runtime_verified": (
        "Raport generat împotriva unui runtime real, cu ancorele oficiale verificate în "
        "această rulare."
    ),
    "runtime_no_anchors": (
        "Raport generat împotriva unui runtime real, dar fără verificarea ancorelor "
        "oficiale în această rulare."
    ),
    "static_only": (
        "Raport generat fără runtime: starea surselor este cea a unui director gol, nu a "
        "unei instalări reale."
    ),
}


def _evidence_basis(data_home: str | None, sync_anchors: bool) -> str:
    if not data_home:
        return "static_only"
    return "runtime_verified" if sync_anchors else "runtime_no_anchors"


def _table(rows: list[tuple[str, str, str]]) -> str:
    body = ["| Gate | Status | Evidence |", "| --- | --- | --- |"]
    body.extend(f"| {gate} | {status} | {evidence} |" for gate, status, evidence in rows)
    return "\n".join(body)


def _capability_table(counts: dict) -> str:
    if not counts:
        return "- Not available in this report."
    body = ["| Capability | Covered | Required | Families |", "| --- | --- | --- | --- |"]
    for key in sorted(counts):
        item = counts[key] or {}
        families = ", ".join(item.get("families") or []) or "-"
        body.append(f"| `{key}` | {item.get('ok', 0)} | {item.get('total', 0)} | {families} |")
    return "\n".join(body)


def build(
    *,
    data_home: str | None = None,
    data_channel: str | None = None,
    sync_source_anchors: bool = False,
    generated_at: datetime | None = None,
) -> tuple[str, dict]:
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    completeness, anchor_sync = _runtime_completeness(data_home, data_channel, sync_source_anchors)
    pilot_pack = _read_json(PILOT_PACK)
    rehearsal = _read_json(REHEARSAL)
    pilot_acceptance = _read_json(PILOT_ACCEPTANCE)
    ai_eval_schema = _read_json(AI_EVAL_SCHEMA)
    source_status = completeness.get("source_status") or {}
    vertical = completeness.get("vertical_acceptance") or {}
    evidence_basis = _evidence_basis(data_home, sync_source_anchors)
    claim_allowed = bool(completeness.get("completion_claim_allowed"))
    status = "passed" if claim_allowed and evidence_basis == "runtime_verified" else "blocked"
    capabilities = completeness.get("capabilities") or []
    capability_rows = [
        (
            item.get("label", item.get("key", "")),
            item.get("state", "unknown"),
            item.get("evidence", ""),
        )
        for item in capabilities
    ]
    blockers = completeness.get("blocking_capabilities") or []
    blocker_lines = []
    for item in blockers:
        joined = "; ".join(item.get("blockers") or ["no evidence"])
        blocker_lines.append(f"- `{item.get('key')}`: {item.get('state')} - {joined}")
    if not blocker_lines:
        blocker_lines.append("- None.")
    source_sync_lines = ["- Not run in this report."]
    if anchor_sync:
        counts = json.dumps(anchor_sync.get("counts", {}), ensure_ascii=False, sort_keys=True)
        source_sync_lines = [
            f"- Contract: `{anchor_sync.get('contract')}`.",
            f"- Total anchors: {anchor_sync.get('total', 0)}.",
            f"- Counts: `{counts}`.",
        ]
    completeness_command = (
        "uv run python -m scripts.app_completeness "
        "--data-home ~/.local/share/legislativ "
        "--sync-source-anchors --require-complete"
    )
    real_data_command = (
        "uv run python -m scripts.acceptare_date_reale "
        "/tmp/legislativ-v1-pilot-release --min-acts 2 "
        "--pilot-act lege-98-2016 --require-reviewable-finding --require-eu-text"
    )
    report = f"""# Final Acceptance

Generated: `{generated}`

Commit: `{_git_commit()}`

Status: **{status}**

This file is generated from the current product gates. It is not a legal
accuracy claim and it does not replace human domain review.

## Report Provenance

The status above describes the runtime this report was generated against, not the
repository alone. A run without a real `--data-home` and without verified official
anchors can never report `passed`.

- Evidence basis: `{evidence_basis}`.
- Meaning: {EVIDENCE_BASIS[evidence_basis]}
- Data home: `{data_home or "not used"}`.
- Data channel: `{data_channel or "default"}`.
- Official anchors verified in this run: `{str(bool(sync_source_anchors)).lower()}`.
- Completion claim allowed by the gate: `{str(claim_allowed).lower()}`.

## Completeness Gate

- Contract: `{completeness.get("contract")}`.
- Completion claim allowed: `{str(bool(completeness.get("completion_claim_allowed"))).lower()}`.
- Summary: `{json.dumps(completeness.get("summary", {}), ensure_ascii=False, sort_keys=True)}`.
- Source status: `{source_status.get("status")}`.
- Missing required source families: `{source_status.get("missing_required", 0)}`.
- Unsynced required source families: `{source_status.get("unsynced_required", 0)}`.
- Anchor-only required source families: `{source_status.get("anchor_only_required", 0)}`.
- Source attention rows: `{source_status.get("attention_sources", 0)}`.

### Coverage By Sync Capability

Required families, grouped by what the local registry can prove about them. Only
`automated` families can reach coverage by syncing; `manual_metadata` depends on an
operator entering rows, and `anchor_only` families are carried by a separate pipeline.

{_capability_table(source_status.get("sync_capability_counts") or {})}

{_table(capability_rows)}

## Current Blockers

{chr(10).join(blocker_lines)}

## Source Anchor Sync

{chr(10).join(source_sync_lines)}

## Vertical Acceptance

- Status: `{vertical.get("status", "unknown")}`.
- Contract: `{vertical.get("contract", "unknown")}`.
- Checks: `{json.dumps(vertical.get("checks", {}), ensure_ascii=False, sort_keys=True)}`.
- Summary: `{json.dumps(vertical.get("summary", {}), ensure_ascii=False, sort_keys=True)}`.

## Real Data Evidence

- Real pilot pack: `{pilot_pack.get("status", "unknown")}`.
- Domain: `{pilot_pack.get("domain", "unknown")}`.
- Acceptance command: `{pilot_pack.get("acceptance_command", "unknown")}`.
- Historical pilot acceptance: `{pilot_acceptance.get("status", "unknown")}`.
- Fixture rehearsal: `{rehearsal.get("status", "unknown")}`.
- AI eval schema: `{ai_eval_schema.get("contract", ai_eval_schema.get("status", "unknown"))}`.

## Release Commands

```bash
{completeness_command}
uv run python -m scripts.real_pilot_pack
uv run python -m scripts.v1_rehearsal
{real_data_command}
```

## Limitations

{chr(10).join(f"- {item}" for item in completeness.get("limitari", []))}
- Legal correctness, precision and recall require independent adjudication.
- AI/MCP output remains draft evidence for human review, never a verdict.
- Private dossiers must remain local and outside public dataset manifests.
"""
    summary = {
        "status": status,
        "completion_claim_allowed": claim_allowed,
        "evidence_basis": evidence_basis,
        "data_home_used": bool(data_home),
        "anchors_verified": bool(sync_source_anchors),
        "blocking_capabilities": [item.get("key") for item in blockers],
        "source_status": source_status,
        "anchor_sync": anchor_sync,
    }
    return report, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-home")
    parser.add_argument("--data-channel")
    parser.add_argument("--sync-source-anchors", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    if args.data_channel and not args.data_home:
        parser.error("--data-channel necesita --data-home")
    if args.sync_source_anchors and not args.data_home:
        parser.error("--sync-source-anchors necesita --data-home")
    report, summary = build(
        data_home=args.data_home,
        data_channel=args.data_channel,
        sync_source_anchors=args.sync_source_anchors,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if args.require_complete and summary["status"] != "passed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
