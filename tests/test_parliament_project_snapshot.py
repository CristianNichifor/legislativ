from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import documente_proiecte, parliament_project_snapshot, source_registry, tracker_events


def test_parliament_project_snapshot_validates_recorded_cdep_fisa():
    out = parliament_project_snapshot.validate()

    assert out["contract"] == "parliament-project-snapshots-v1"
    assert out["status"] == "ready"
    assert out["problems"] == []
    snapshot = out["snapshots"][0]
    assert snapshot["project_id"] == "plx-33-2025"
    assert snapshot["idp"] == "21949"
    assert snapshot["senate_id"] == "L576/2024"
    assert snapshot["procedure_date"] == "2025-02-03"
    assert "raport" in snapshot["stage"].lower()
    assert snapshot["source_url"].startswith("https://www.cdep.ro/")
    assert snapshot["route_counts"]["stages"] >= 1
    assert snapshot["route_counts"]["opinions"] >= 1


def test_parliament_project_snapshot_detects_bad_expected_metadata(tmp_path):
    pack = json.loads(parliament_project_snapshot.SNAPSHOTS.read_text(encoding="utf-8"))
    pack["snapshots"][0]["project_id"] = "plx-wrong"
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(pack), encoding="utf-8")

    out = parliament_project_snapshot.validate(path)

    assert out["status"] == "blocked"
    assert out["problems"] == [{"key": "plx-33-2025", "message": "Unexpected project_id."}]


def test_recorded_project_seeds_registry_and_tracker_without_live_crawl(monkeypatch, tmp_path):
    stare = SimpleNamespace(initiative=tmp_path / "initiative.db")
    row = parliament_project_snapshot.register_source(stare)

    assert row["family"] == "camera"
    assert row["identifier"] == "plx-33-2025"
    assert row["state"] == "discovered"

    fisa = (parliament_project_snapshot.ROOT / "tests/fixtures/cdep_fisa.html.gz").read_bytes()
    monkeypatch.setattr(documente_proiecte, "descarca", lambda *_args, **_kwargs: fisa)

    synced = source_registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert synced["state"] in {"changed", "needs_review"}
    assert synced["last_hash"]
    assert synced["parser_version"] == "achizitii_proiecte.v1"
    assert synced["tracker_sync"]["stored"] >= 1
    listed = tracker_events.lista(stare, {"project_id": ["plx-33-2025"]})
    event_types = {event["event_type"] for event in listed["events"]}
    assert "committee_assignment" in event_types
    assert "report_filed" in event_types
    selected = source_registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["snapshots"][0]["summary"]["plx"] == "plx-33-2025"
    assert selected["snapshots"][0]["summary"]["fisa_url"].endswith("idp=21949")
