from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import real_reviewable_finding

ROOT = Path(__file__).resolve().parents[1]


def test_real_reviewable_finding_schema_validates_artifact():
    schema = json.loads((ROOT / "schema/real_reviewable_finding.schema.json").read_text())
    finding = json.loads((ROOT / "data/real_reviewable_finding.json").read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(finding)


def test_real_reviewable_finding_is_quote_and_hash_bound():
    out = real_reviewable_finding.validate()

    assert out["contract"] == "real-reviewable-finding-v1"
    assert out["status"] == "ready"
    assert out["issue_type"] == "lacuna"
    assert out["review_status"] == "reviewed"
    assert out["proposal_ready"] is True
    assert out["verified_sources"] == 2
    assert out["problems"] == []


def test_real_reviewable_finding_seeds_reviewed_dossier_proposal_and_export(tmp_path):
    out = real_reviewable_finding.seed_dossier(tmp_path)

    assert out["contract"] == "real-reviewable-finding-dossier-flow-v1"
    assert out["review"]["stare"] == "confirmed_by_reviewer"
    assert out["note"]["status"] == "reviewed"
    assert out["note"]["source_hash"] == (
        "9e96ff1c5b0d427376e352d5149174b6e7b51072edc4708343d6fc5713703762"
    )
    assert out["proposal"]["revizie"] == 1
    assert "art. 58 din Legea nr. 98/2016" in out["proposal"]["text"]
    assert out["export_contains_proposal"] is True


def test_real_reviewable_finding_detects_source_hash_mismatch(tmp_path):
    data = json.loads((ROOT / "data/real_reviewable_finding.json").read_text())
    data["finding"]["source_sha256"] = "0" * 64
    path = tmp_path / "finding.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    out = real_reviewable_finding.validate(path)

    assert out["status"] == "blocked"
    assert out["problems"] == [
        {"key": "sources/lege-98-2016.html.gz", "message": "Source hash mismatch."}
    ]
