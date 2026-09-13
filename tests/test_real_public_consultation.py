from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from scripts import achizitii_econsultare as ec
from scripts import real_public_consultation, tracker_events

ROOT = Path(__file__).resolve().parents[1]


def fixture() -> dict:
    return json.loads((ROOT / "data/real_public_consultation_snapshot.json").read_text())


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def test_real_public_consultation_fixture_matches_schema():
    schema = json.loads((ROOT / "schema/real_public_consultation_snapshot.schema.json").read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture())


def test_actiongrid_row_normalizes_to_econsultare_snapshot():
    data = fixture()

    snapshot = ec.snapshot_din_actiongrid(data["row"], listing_url=data["official_listing_url"])

    assert snapshot["contract"] == "econsultare-source-snapshot-v1"
    assert snapshot["url"] == data["expected"]["detail_url"]
    assert data["expected"]["title_contains"] in snapshot["summary"]["title"]
    assert snapshot["summary"]["authority"] == data["expected"]["authority"]
    assert snapshot["summary"]["status"] == "open"
    assert snapshot["summary"]["deadline"] == "28/09/2026"
    assert snapshot["source_metadata"]["source_hash"] == data["expected"]["row_hash"]


def test_real_public_consultation_fixture_builds_tracker_candidate():
    data = fixture()
    snapshot = ec.snapshot_din_actiongrid(data["row"], listing_url=data["official_listing_url"])

    candidate = ec.tracker_event_candidate(
        snapshot,
        source_id="econsultare-3758",
        content_hash=ec.snapshot_hash(snapshot),
        observed_at=data["recorded_at"],
    )

    assert candidate["event_type"] == "public_consultation_opened"
    assert candidate["project_id"] == data["expected"]["detail_url"]
    assert candidate["occurred_at"] == "2026-09-28T00:00:00+00:00"
    assert candidate["payload"]["authority"] == data["expected"]["authority"]
    assert candidate["payload"]["deadline"] == "2026-09-28T00:00:00+00:00"


def test_real_public_consultation_validation_is_ready():
    out = real_public_consultation.validate()

    assert out["status"] == "ready"
    assert out["source_family"] == "consultare_econsultare"
    assert out["source_id"] == "econsultare-3758"
    assert out["summary"]["documents"] == 0
    assert out["tracker_event"]["event_type"] == "public_consultation_opened"
    assert out["problems"] == []


def test_real_public_consultation_seeds_registry_and_tracker(tmp_path):
    stare = state(tmp_path)

    out = real_public_consultation.seed_registry(stare)

    assert out["source"]["family"] == "consultare_econsultare"
    assert out["source"]["state"] == "changed"
    assert out["source"]["last_hash"] == out["validation"]["source_hash"]
    assert out["tracker_event"]["event_type"] == "public_consultation_opened"
    assert out["tracker_event"]["stage_key"] == "consultation_open"
    listed = tracker_events.lista(stare, {"source_family": ["consultare_econsultare"]})
    assert listed["summary"]["by_stage"]["consultation_open"]["count"] == 1
