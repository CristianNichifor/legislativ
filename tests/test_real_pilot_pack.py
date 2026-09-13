from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import real_pilot_pack

ROOT = Path(__file__).resolve().parents[1]


def test_real_pilot_pack_schema_validates_current_pack():
    schema = json.loads((ROOT / "schema/real_pilot_pack.schema.json").read_text())
    pack = json.loads((ROOT / "data/real_pilot_pack.json").read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(pack)


def test_real_pilot_pack_reports_current_blockers_without_crawling():
    out = real_pilot_pack.validate()

    assert out["contract"] == "real-pilot-pack-v1"
    assert out["status"] == "blocked"
    assert out["declared_status"] == "blocked"
    assert out["ready_requirements"] == 3
    assert out["blocked"] == [
        "celex_text",
        "reviewable_finding",
    ]
    assert out["problems"] == []
    assert "--require-reviewable-finding --require-eu-text" in out["acceptance_command"]
    assert "bulk crawling" in out["excluded"]


def test_real_pilot_pack_detects_bad_hash(tmp_path):
    pack = json.loads((ROOT / "data/real_pilot_pack.json").read_text())
    pack["requirements"][0]["evidence"][0]["sha256"] = "0" * 64
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")

    out = real_pilot_pack.validate(path)

    assert out["status"] == "blocked"
    assert out["problems"] == [
        {
            "key": "romanian_law_text",
            "message": "Evidence hash mismatch: sources/lege-98-2016.html.gz",
        }
    ]
