"""Validate the bounded real-pilot ingredients before heavy acceptance runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "real_pilot_pack.json"
CONTRACT = "real-pilot-pack-v1"
REQUIRED_KEYS = {
    "romanian_law_text",
    "parliament_project",
    "public_consultation",
    "celex_text",
    "reviewable_finding",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path = PACK) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = PACK, *, root: Path = ROOT) -> dict:
    pack = _load(path)
    requirements = pack.get("requirements") or []
    seen = {item.get("key") for item in requirements}
    problems: list[dict[str, str]] = []

    if pack.get("contract") != CONTRACT:
        problems.append({"key": "contract", "message": "Unexpected real-pilot contract."})
    for key in sorted(REQUIRED_KEYS - seen):
        problems.append({"key": key, "message": "Required pilot ingredient is not declared."})

    ready = 0
    blocked: list[str] = []
    for item in requirements:
        key = str(item.get("key") or "")
        status = item.get("status")
        if item.get("required") and status == "blocked":
            blocked.append(key)
        if status == "ready":
            ready += 1
        if status == "ready" and not item.get("evidence"):
            problems.append({"key": key, "message": "Ready ingredient has no evidence."})
        for evidence in item.get("evidence") or []:
            rel_path = evidence.get("path")
            expected = evidence.get("sha256")
            if rel_path is None:
                continue
            source_path = root / rel_path
            if not source_path.exists():
                problems.append({"key": key, "message": f"Evidence file missing: {rel_path}"})
                continue
            if expected and _sha256(source_path) != expected:
                problems.append({"key": key, "message": f"Evidence hash mismatch: {rel_path}"})

    computed_status = "blocked" if blocked or problems else "ready"
    return {
        "contract": CONTRACT,
        "status": computed_status,
        "declared_status": pack.get("status"),
        "domain": pack.get("domain"),
        "acceptance_command": pack.get("acceptance_command"),
        "ready_requirements": ready,
        "total_requirements": len(requirements),
        "blocked": blocked,
        "problems": problems,
        "next_actions": [
            item["next_action"]
            for item in requirements
            if item.get("required") and item.get("status") == "blocked" and item.get("next_action")
        ],
        "excluded": pack.get("excluded") or [],
        "notes": pack.get("notes") or [],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=PACK)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.pack), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
