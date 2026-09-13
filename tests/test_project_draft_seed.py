import io
import json
from types import SimpleNamespace

from scripts import project_draft_seed, tracker_events
from scripts.server import face_handler


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def add_event(stare):
    return tracker_events.adauga(
        stare,
        {
            "event_type": "report_filed",
            "project_id": "PL-x 10/2026",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/proiect/10",
            "occurred_at": "2026-09-12T10:00:00+00:00",
            "title": "Raport depus",
            "payload": {"committee": "Comisia juridică"},
            "content_hash": "a" * 64,
        },
    )["event"]


def test_project_draft_seed_uses_tracker_events(tmp_path):
    stare = state(tmp_path)
    add_event(stare)

    out = project_draft_seed.build(stare, {"project_id": ["PL-x 10/2026"]})

    assert out["contract"] == "project-draft-seed-v1"
    assert out["summary"]["events"] == 1
    assert "Proiect urmărit: PL-x 10/2026" in out["text"]
    assert "Raport depus" in out["text"]
    assert "https://www.cdep.ro/proiect/10" in out["text"]
    assert "nu verdict juridic" in out["text"]


def test_project_draft_seed_reports_empty_local_tracker(tmp_path):
    stare = state(tmp_path)

    out = project_draft_seed.build(stare, {"project_id": ["PL-x 10/2026"]})

    assert out["summary"]["events"] == 0
    assert "Nu există evenimente locale" in out["text"]
    assert not tracker_events.cale(stare).exists()


def test_http_project_draft_seed_endpoint(tmp_path):
    stare = state(tmp_path)
    add_event(stare)
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/project-draft-seed?project_id=PL-x%2010/2026"
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_GET()

    code, data = result[0]
    assert code == 200
    assert data["contract"] == "project-draft-seed-v1"
    assert json.dumps(data, ensure_ascii=False)
