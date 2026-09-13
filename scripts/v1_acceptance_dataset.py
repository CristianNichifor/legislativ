"""Small v1 acceptance dataset contract.

This validates the curated smoke manifest only. It does not build or fetch a
public dataset release.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "v1_acceptance_dataset.json"
CONTRACT = "v1-acceptance-dataset-manifest-v1"
MAX_ITEMS = 10
MIN_ITEMS = 5
SOURCE_FAMILIES = frozenset(
    {
        "portal_legislativ",
        "camera",
        "senat",
        "econsultare",
        "ministry_consultation",
        "eu_cellar",
    }
)
RECORD_TYPES = frozenset({"law", "project", "consultation", "celex"})
MODES = frozenset({"local_fixture", "placeholder"})
REQUIRED_RECORD_TYPES = frozenset({"law", "project", "consultation", "celex"})


class AcceptanceDatasetError(ValueError):
    """Invalid v1 acceptance dataset manifest."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceDatasetError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict, *, root: Path = ROOT) -> dict:
    """Validate manifest invariants that JSON Schema cannot express alone."""
    _require(manifest.get("contract") == CONTRACT, "unknown v1 acceptance dataset contract")
    scope = manifest.get("scope")
    _require(isinstance(scope, dict), "scope must be an object")
    _require(scope.get("large_release_required") is False, "v1 acceptance must not require release")
    max_bytes = scope.get("max_checked_in_payload_bytes")
    _require(isinstance(max_bytes, int) and 0 < max_bytes <= 1024 * 1024, "invalid byte cap")

    items = manifest.get("items")
    _require(isinstance(items, list) and MIN_ITEMS <= len(items) <= MAX_ITEMS, "invalid item count")
    ids: set[str] = set()
    identifiers: set[tuple[str, str]] = set()
    record_types: set[str] = set()
    total_fixture_bytes = 0

    for item in items:
        _require(isinstance(item, dict), "item must be an object")
        item_id = item.get("id")
        _require(isinstance(item_id, str) and item_id not in ids, "duplicate item id")
        ids.add(item_id)

        family = item.get("source_family")
        record_type = item.get("record_type")
        mode = item.get("mode")
        identifier = item.get("identifier")
        _require(family in SOURCE_FAMILIES, "unknown source family")
        _require(record_type in RECORD_TYPES, "unknown record type")
        _require(mode in MODES, "unknown item mode")
        _require(isinstance(identifier, str) and identifier, "missing identifier")
        key = (family, identifier)
        _require(key not in identifiers, "duplicate source identifier")
        identifiers.add(key)
        record_types.add(record_type)

        local_path = item.get("local_path")
        sha256 = item.get("sha256")
        if mode == "local_fixture":
            _require(isinstance(local_path, str), "local fixture must name a path")
            _require(isinstance(sha256, str) and len(sha256) == 64, "local fixture must name hash")
            path = root / local_path
            _require(path.is_file(), f"local fixture missing: {local_path}")
            total_fixture_bytes += path.stat().st_size
            _require(_sha256(path) == sha256, f"local fixture hash mismatch: {local_path}")
        else:
            _require(local_path is None, "placeholder must not point to local payload")
            _require(sha256 is None, "placeholder must not pretend to have payload hash")

    _require(
        record_types >= REQUIRED_RECORD_TYPES,
        "manifest must cover law/project/consultation/CELEX",
    )
    _require(total_fixture_bytes <= max_bytes, "checked-in fixture payloads exceed v1 cap")
    return manifest


def validate(path: Path = MANIFEST) -> dict:
    return validate_manifest(load_manifest(path), root=path.resolve().parents[1])
