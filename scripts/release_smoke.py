"""Lightweight release/deployment smoke checks.

This intentionally avoids rebuilding the corpus or downloading public datasets. It checks that the
repo contains the public app, local launch entrypoints and CI wiring needed to make merged work
reachable from GitHub Pages and from the downloadable local bundle.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    key: str
    ok: bool
    summary: str


REQUIRED_FILES = (
    "app/index.html",
    "app/browser-workspace.js",
    "app/dataset-updates.js",
    "scripts/build_runtime.py",
    "scripts/launcher.py",
    "scripts/server.py",
    "ruleaza.sh",
    "ruleaza.cmd",
)


def _contains(path: Path, *needles: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


def run(root: Path) -> dict:
    root = root.resolve()
    files = [
        Check(
            key=f"file:{name}",
            ok=(root / name).is_file(),
            summary=name,
        )
        for name in REQUIRED_FILES
    ]
    checks = [
        *files,
        Check(
            key="local_launch:private_data_home",
            ok=_contains(root / "scripts/launcher.py", "--data-home", "private"),
            summary="launcher accepts an explicit data home and creates private storage",
        ),
        Check(
            key="public_app:workspace_and_updates",
            ok=_contains(
                root / "app/index.html",
                "dataset-updates.js",
                "acceptance-dashboard-refresh",
            ),
            summary="public app loads update UI and exposes the acceptance dashboard action",
        ),
        Check(
            key="browser_checks:npm_scripts",
            ok=_contains(root / "package.json", "test:browser", "test:browser:static"),
            summary="browser/static smoke scripts are exposed through npm",
        ),
        Check(
            key="pages:workflow",
            ok=_contains(
                root / ".github/workflows/pages.yml",
                "actions/deploy-pages",
                "scripts.construieste_web",
                "app/**",
            ),
            summary="GitHub Pages workflow builds and deploys the browser app",
        ),
    ]
    return {
        "contract": "release-smoke-v1",
        "status": "ok" if all(check.ok for check in checks) else "attention",
        "checks": [check.__dict__ for check in checks],
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
        for check in report["checks"]:
            marker = "ok" if check["ok"] else "fail"
            print(f"{marker}\t{check['key']}\t{check['summary']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
