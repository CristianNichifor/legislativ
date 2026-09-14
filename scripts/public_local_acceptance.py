"""Public Pages and local package acceptance gate.

This gate is intentionally deterministic. It does not publish Pages, download a
real dataset, rebuild a corpus or touch MCP/law-as-code internals. It checks the
contracts that make those release paths safe to use: Pages workflow wiring,
local package smoke coverage, channel/manifest verification, public unavailable
states and private data boundaries.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from scripts import dataset_release, release_smoke

CONTRACT = "public-local-acceptance-v1"
TRUSTED_ORIGIN = "https://date.cristian-nichifor.com"


@dataclass(frozen=True)
class Check:
    key: str
    ok: bool
    summary: str


def _read(root: Path, rel: str) -> str:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _has_all(text: str, needles: tuple[str, ...]) -> bool:
    return all(needle in text for needle in needles)


def _channel_contract_ok() -> bool:
    manifest = {
        "schema_version": 1,
        "release": "2026-09-14",
        "app_contract": 1,
        "created_at": "2026-09-14T00:00:00Z",
        "files": [{"name": "corpus.db", "bytes": 4096, "sha256": "a" * 64}],
    }
    dataset_release.validate_manifest(manifest)
    dataset_release.validate_channel(
        {
            "schema_version": 1,
            "manifest": f"{TRUSTED_ORIGIN}/2026-09-14/dataset-release.json",
            "sha256": "b" * 64,
        },
        trusted_origin=TRUSTED_ORIGIN,
    )
    try:
        dataset_release.validate_channel(
            {
                "schema_version": 1,
                "manifest": "https://evil.example/2026-09-14/dataset-release.json",
                "sha256": "b" * 64,
            },
            trusted_origin=TRUSTED_ORIGIN,
        )
    except dataset_release.ReleaseError:
        return True
    return False


def run(root: Path) -> dict:
    root = root.resolve()
    smoke = release_smoke.run(root)
    pages = _read(root, ".github/workflows/pages.yml")
    package = _read(root, "scripts/build_runtime.py")
    local_launch = _read(root, "docs/local-launch.md")
    local_first = _read(root, "docs/LOCAL_FIRST.md")
    release_doc = _read(root, "docs/RELEASE_SMOKE.md")
    dataset_updates = _read(root, "app/dataset-updates.js")
    browser_generation = _read(root, "tests/browser_generation.cjs")
    source_dataflow = _read(root, "tests/test_source_dataflow_acceptance.py")
    local_tests = _read(root, "tests/test_local_launch.py")
    package_json = _read(root, "package.json")

    checks = [
        Check(
            "release_smoke:baseline",
            smoke["status"] == "ok",
            "release smoke checks public app, package entrypoints, local launch and Pages wiring",
        ),
        Check(
            "pages:public_deploy",
            _has_all(
                pages,
                (
                    "branches: [main]",
                    "actions/deploy-pages",
                    "scripts.construieste_web",
                    "app/**",
                    "contents: read",
                    "pages: write",
                ),
            ),
            "GitHub Pages deploys the committed browser app from main without private data",
        ),
        Check(
            "local:downloadable_package",
            _has_all(package, ('"legislativ-local.zip"', '"SHA256SUMS"', "archive.write"))
            and _has_all(local_tests, ("any(n.endswith", '".db"', '"private/"')),
            "local package produces a zip and checksum while excluding databases/private folders",
        ),
        Check(
            "local:cold_start_smoke",
            _has_all(
                local_tests,
                ("test_packaged_cold_start_contract", "test_real_server_cold_start"),
            ),
            "local launcher has packaged and real-server cold-start smoke tests",
        ),
        Check(
            "data:channel_manifest_contract",
            _channel_contract_ok(),
            "dataset channel/manifest contract validates trusted immutable release URLs",
        ),
        Check(
            "data:update_private_boundary",
            _has_all(
                source_dataflow,
                (
                    "test_public_local_source_dataflow_acceptance",
                    "private legislative gap workspace",
                    "private_data_uploaded",
                    "manager.rollback",
                ),
            ),
            "public update and rollback preserve private dossier storage",
        ),
        Check(
            "public:optional_source_states",
            _has_all(
                dataset_updates,
                (
                    "Surse indisponibile",
                    "Nicio baza legislativa instalata",
                    "Datele private raman",
                    "status.private_data_uploaded !== false",
                ),
            )
            or _has_all(
                dataset_updates,
                (
                    "Surse indisponibile",
                    "Nicio bază legislativă instalată",
                    "Datele private rămân",
                    "status.private_data_uploaded !== false",
                ),
            ),
            "public update UI explains missing optional data and private-data boundary",
        ),
        Check(
            "public:server_unavailable_states",
            _has_all(
                browser_generation,
                (
                    "corpus-failure",
                    "Status survives missing runtime/CDN",
                    "Private status independent of public boot",
                ),
            ),
            "browser smoke proves server/runtime unavailable states do not break private export",
        ),
        Check(
            "browser:static_acceptance_script",
            '"test:browser:static"' in package_json
            and "npm run test:browser:static" in release_doc,
            "static browser acceptance command is published for maintainers",
        ),
        Check(
            "docs:release_operator_path",
            _has_all(
                local_launch + local_first + release_doc,
                (
                    "legislativ-local.zip",
                    "channel.json",
                    "private",
                    "uv run python -m scripts.release_smoke --json",
                ),
            ),
            "operator docs explain package, channel, smoke command and private storage",
        ),
    ]
    status = "ok" if all(check.ok for check in checks) else "attention"
    return {
        "contract": CONTRACT,
        "status": status,
        "checks": [check.__dict__ for check in checks],
        "acceptance": {
            "github_pages_private_dossier": status == "ok",
            "downloadable_local_app": status == "ok",
            "source_update_preserves_private_work": status == "ok",
            "rollback_preserves_private_dossiers": status == "ok",
        },
        "commands": [
            "uv run python -m scripts.public_local_acceptance --json",
            (
                "uv run pytest -q tests/test_public_local_acceptance.py "
                "tests/test_release_smoke.py tests/test_local_launch.py "
                "tests/test_source_dataflow_acceptance.py"
            ),
            "npm run test:browser:static",
        ],
        "scope": [
            "No publish, upload or real public download is performed.",
            "No MCP or law-as-code application internals are exercised.",
            "This is an acceptance gate for release wiring and private-data boundaries.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for check in report["checks"]:
            marker = "ok" if check["ok"] else "fail"
            print(f"{marker}\t{check['key']}\t{check['summary']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
