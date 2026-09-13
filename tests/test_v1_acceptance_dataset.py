import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts import v1_acceptance_dataset as acceptance

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def manifest():
    return json.loads(acceptance.MANIFEST.read_text(encoding="utf-8"))


def test_manifest_matches_schema_and_runtime_contract(manifest):
    schema = json.loads((ROOT / "schema/v1_acceptance_dataset.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    assert acceptance.validate_manifest(manifest) == manifest


def test_v1_scope_is_small_and_covers_acceptance_families(manifest):
    assert manifest["scope"]["large_release_required"] is False
    assert "multi-GB public dataset releases" in manifest["scope"]["excludes"]
    assert 5 <= len(manifest["items"]) <= 10

    by_type = {item["record_type"] for item in manifest["items"]}
    by_family = {item["source_family"] for item in manifest["items"]}
    assert {"law", "project", "consultation", "celex"} <= by_type
    assert {"portal_legislativ", "camera", "senat", "econsultare", "eu_cellar"} <= by_family


def test_local_fixture_payloads_are_existing_bounded_files(manifest):
    cap = manifest["scope"]["max_checked_in_payload_bytes"]
    fixture_items = [item for item in manifest["items"] if item["mode"] == "local_fixture"]
    assert fixture_items
    assert sum((ROOT / item["local_path"]).stat().st_size for item in fixture_items) <= cap
    for item in fixture_items:
        path = ROOT / item["local_path"]
        assert path.is_file()
        assert item["sha256"] == acceptance._sha256(path)


def test_placeholders_do_not_claim_local_payloads(manifest):
    placeholders = [item for item in manifest["items"] if item["mode"] == "placeholder"]
    assert placeholders
    assert any(item["record_type"] == "celex" for item in placeholders)
    for item in placeholders:
        assert item["local_path"] is None
        assert item["sha256"] is None
        assert item["acceptance_status"] in {"placeholder", "text_missing"}


def test_duplicate_identifiers_are_rejected(manifest):
    duplicate = copy.deepcopy(manifest["items"][0])
    duplicate["id"] = "v1-law-duplicate"
    manifest["items"].append(duplicate)
    with pytest.raises(acceptance.AcceptanceDatasetError, match="duplicate source identifier"):
        acceptance.validate_manifest(manifest)


def test_large_release_requirement_is_rejected(manifest):
    manifest["scope"]["large_release_required"] = True
    with pytest.raises(acceptance.AcceptanceDatasetError, match="must not require release"):
        acceptance.validate_manifest(manifest)
