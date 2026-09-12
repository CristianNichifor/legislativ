"""End-to-end user-flow contract for the app surface."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Flow:
    key: str
    label: str
    state: str
    evidence: tuple[str, ...]
    blocker: str = ""


def _has(path: Path, *needles: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


def run(root: Path) -> dict:
    root = root.resolve()
    flows = [
        Flow(
            key="public_to_local_workspace",
            label="Public app -> local private workspace",
            state=(
                "ready"
                if _has(root / "scripts/construieste_web.py", "browser-workspace.js")
                and _has(root / "app/browser-workspace.js", "/api/browser-workspace")
                else "missing"
            ),
            evidence=("scripts/construieste_web.py", "app/browser-workspace.js"),
        ),
        Flow(
            key="source_update_rollback",
            label="Public dataset update -> activate -> rollback",
            state="ready" if _has(root / "scripts/local_runtime.py", "rollback") else "missing",
            evidence=("scripts/local_runtime.py", "tests/test_local_runtime.py"),
        ),
        Flow(
            key="dossier_note_proposal",
            label="Dossier -> manual note -> structured proposal",
            state=(
                "ready"
                if _has(root / "scripts/server.py", "/api/dosare/note", "/api/dosare/propuneri")
                else "missing"
            ),
            evidence=("scripts/server.py", "docs/DOSARE.md"),
        ),
        Flow(
            key="eu_risk_context",
            label="CELEX import/search -> EU risk context",
            state=(
                "partial"
                if _has(root / "scripts/server.py", "/api/ue/import", "/api/dosare/note-ue")
                else "missing"
            ),
            evidence=("scripts/server.py", "docs/V1_ACCEPTANCE.md"),
            blocker="needs official CELEX text import for the pilot references",
        ),
        Flow(
            key="law_as_code_review",
            label="Rule candidate -> reviewed draft -> deterministic check",
            state=(
                "partial"
                if _has(
                    root / "scripts/server.py",
                    "/api/dosare/rule-candidates/preview",
                    "/api/dosare/rule-drafts/checks",
                )
                else "missing"
            ),
            evidence=("scripts/server.py", "docs/LAW_CODE_CHECKS.md"),
            blocker="only delegated-norm checks are implemented",
        ),
        Flow(
            key="acceptance_dashboard",
            label="Acceptance dashboard -> remaining gaps",
            state=(
                "ready"
                if _has(root / "scripts/server.py", "/api/acceptance-dashboard")
                and _has(root / "scripts/acceptance_dashboard.py", "acceptance-dashboard-v1")
                else "missing"
            ),
            evidence=("scripts/server.py", "scripts/acceptance_dashboard.py"),
        ),
    ]
    return {
        "contract": "e2e-user-flows-v1",
        "status": "attention" if any(flow.state != "ready" for flow in flows) else "ok",
        "summary": {
            "ready": sum(1 for flow in flows if flow.state == "ready"),
            "partial": sum(1 for flow in flows if flow.state == "partial"),
            "missing": sum(1 for flow in flows if flow.state == "missing"),
            "total": len(flows),
        },
        "flows": [
            {
                "key": flow.key,
                "label": flow.label,
                "state": flow.state,
                "evidence": list(flow.evidence),
                "blocker": flow.blocker,
            }
            for flow in flows
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for flow in report["flows"]:
            print(f"{flow['state']}\t{flow['key']}\t{flow['label']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
