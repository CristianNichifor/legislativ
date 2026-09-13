import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from scripts import attention_feed, public_tracking, source_registry, tracker_events

ROOT = public_tracking.ROOT


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def fixture():
    return json.loads(public_tracking.FIXTURE.read_text(encoding="utf-8"))


def test_public_tracking_fixture_matches_schema():
    schema = json.loads((ROOT / "schema/public_tracking_snapshot.schema.json").read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture())


def test_public_tracking_validation_names_coverage_without_fetching():
    out = public_tracking.validate()

    assert out["contract"] == "public-tracking-snapshot-v1"
    assert out["status"] == "ready"
    assert out["project_id"] == "PL-x 33/2025"
    assert out["problems"] == []
    assert out["coverage"] == {
        "public_consultations": True,
        "consultation_deadlines": True,
        "committees": True,
        "opinions": True,
        "reports": True,
        "votes": True,
        "monitor_publication": True,
        "changed_source_alerts": True,
    }
    assert {"camera", "senat", "consultare_econsultare", "avize", "monitorul_oficial_pi"}.issubset(
        set(out["source_families"])
    )


def test_public_tracking_replays_sources_events_and_attention_feed(tmp_path):
    stare = state(tmp_path)

    replayed = public_tracking.replay(stare)

    assert replayed["contract"] == "public-tracking-replay-v1"
    assert replayed["sources"] == 5
    assert replayed["events"] == 8
    assert replayed["attention_sources"] == 2
    assert replayed["event_types"] == {
        "committee_assignment": 2,
        "opinion_received": 1,
        "published_in_monitor": 1,
        "public_consultation_closed": 1,
        "public_consultation_opened": 1,
        "report_filed": 1,
        "vote_recorded": 1,
    }

    timeline = tracker_events.lista(stare, {"project_id": ["PL-x 33/2025"], "limit": ["20"]})
    assert timeline["total"] == 8
    assert timeline["summary"]["by_stage"]["committee"]["count"] == 2
    assert timeline["summary"]["by_stage"]["report"]["count"] == 1
    assert timeline["summary"]["by_stage"]["adopted"]["count"] == 1
    assert timeline["summary"]["by_stage"]["published"]["count"] == 1

    registry = source_registry.lista(stare)
    cdep = next(row for row in registry["sources"] if row["family"] == "camera")
    assert cdep["state"] == "changed"
    assert cdep["latest_change"]["changed"] is True
    assert any(
        change["type"] == "new_committee_report" for change in cdep["latest_change"]["changes"]
    )

    feed = attention_feed.lista(stare, {"limit": ["20"]})
    kinds = {item["kind"] for item in feed["items"]}
    assert {"source", "tracker_event"}.issubset(kinds)
    assert any(
        item["kind"] == "source" and item["state"] in {"overdue", "stage_or_deadline_changed"}
        for item in feed["items"]
    )
    assert any(item["source_family"] == "consultare_econsultare" for item in feed["items"])

    monitor = next(row for row in registry["sources"] if row["family"] == "monitorul_oficial_pi")
    assert monitor["state"] == "fetched"
    assert monitor["snapshots"][0]["summary"] == {
        "act_id": "lege-plx-33-2025",
        "date": "2025-03-24",
        "number": 227,
        "part": "I",
    }


def test_public_tracking_validation_blocks_missing_required_event(tmp_path):
    data = fixture()
    data["sources"][0]["snapshots"][1]["events"] = [
        event
        for event in data["sources"][0]["snapshots"][1]["events"]
        if event["event_type"] != "vote_recorded"
    ]
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    out = public_tracking.validate(path)

    assert out["status"] == "blocked"
    assert {"key": "vote_recorded", "message": "Required tracker event missing."} in out["problems"]
