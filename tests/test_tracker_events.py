import io
import json
from types import SimpleNamespace

import pytest

from scripts import dosare, note_manuale, tracker_events
from scripts.server import face_handler
from tests.test_dosare import ID, create


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def event(**patch):
    data = {
        "event_type": "committee_assignment",
        "project_id": "PL-x 10/2026",
        "source_family": "camera",
        "source_url": "https://www.cdep.ro/pls/proiecte/upl_pck.proiect?idp=10",
        "occurred_at": "2026-09-12T10:00:00+00:00",
        "title": "Comisie sesizată",
        "payload": {"committee": "Comisia juridică", "role": "fond"},
    }
    data.update(patch)
    return data


def test_tracker_store_adds_lists_and_deduplicates_events(tmp_path):
    stare = state(tmp_path)

    saved = tracker_events.adauga(stare, event())["event"]
    again = tracker_events.adauga(stare, event(title="Comisie actualizată"))["event"]
    listed = tracker_events.lista(stare, {"project_id": ["PL-x 10/2026"]})

    assert saved["id"] == again["id"]
    assert again["title"] == "Comisie actualizată"
    assert listed["contract"] == "legislative-tracker-events-v1"
    assert listed["total"] == 1
    assert listed["events"][0]["event_label"] == "committee assignment"
    assert listed["events"][0]["payload"]["committee"] == "Comisia juridică"
    assert listed["source_status"] == "ok"


def test_tracker_store_filters_by_type_dossier_and_source_family(tmp_path):
    stare = state(tmp_path)
    tracker_events.adauga(stare, event(dossier_id="a" * 32))
    tracker_events.adauga(
        stare,
        event(
            event_type="vote_recorded",
            project_id="PL-x 11/2026",
            source_family="senat",
            source_url="https://www.senat.ro/vot",
            occurred_at="2026-09-13T10:00:00+00:00",
            payload={"result": "adopted"},
        ),
    )

    assert tracker_events.lista(stare, {"event_type": ["vote_recorded"]})["total"] == 1
    assert tracker_events.lista(stare, {"source_family": ["camera"]})["total"] == 1
    assert (
        tracker_events.lista(stare, {"dossier_id": ["a" * 32]})["events"][0]["project_id"]
        == "PL-x 10/2026"
    )


def test_tracker_events_carry_unified_lifecycle_metadata(tmp_path):
    stare = state(tmp_path)
    rows = [
        event(
            event_type="public_consultation_opened",
            source_family="consultare_econsultare",
            source_url="https://e-consultare.gov.ro/consultare/1",
            occurred_at="2026-09-01T10:00:00+00:00",
            payload={"authority": "MDLPA"},
        ),
        event(
            event_type="vote_recorded",
            source_family="camera",
            source_url="https://www.cdep.ro/vot",
            occurred_at="2026-09-10T10:00:00+00:00",
            payload={"result": "adoptat"},
        ),
        event(
            event_type="promulgated",
            source_family="presedinte",
            source_url="https://www.presidency.ro/decret",
            occurred_at="2026-09-11T10:00:00+00:00",
            payload={"decree_number": "100"},
        ),
        event(
            event_type="published_in_monitor",
            source_family="monitorul_oficial_pi",
            source_url="https://monitoruloficial.ro/",
            occurred_at="2026-09-12T10:00:00+00:00",
            payload={"part": "I", "number": 10, "date": "2026-09-12"},
        ),
    ]
    for row in rows:
        tracker_events.adauga(stare, row)

    out = tracker_events.lista(stare, {"project_id": ["PL-x 10/2026"]})
    by_type = {row["event_type"]: row for row in out["events"]}

    assert out["lifecycle_stages"][0] == {
        "key": "consultation_open",
        "label": "Consultare",
        "order": 0,
    }
    assert by_type["public_consultation_opened"]["display_label"] == ("Consultare publică deschisă")
    assert by_type["public_consultation_opened"]["stage_key"] == "consultation_open"
    assert by_type["vote_recorded"]["stage_key"] == "adopted"
    assert by_type["promulgated"]["stage_label"] == "Promulgat"
    assert by_type["published_in_monitor"]["stage_order"] > by_type["vote_recorded"]["stage_order"]


def test_tracker_store_marks_events_reviewed_and_filters_by_review_state(tmp_path):
    stare = state(tmp_path)
    saved = tracker_events.adauga(stare, event())["event"]

    assert tracker_events.lista(stare, {"reviewed": ["0"]})["total"] == 1
    reviewed = tracker_events.marcheaza_revizuit(
        stare, {"id": saved["id"], "reviewer": "ana", "note": "Verificat în fișa proiectului."}
    )["event"]

    assert reviewed["review"]["reviewed"] is True
    assert reviewed["review"]["reviewer"] == "ana"
    assert tracker_events.lista(stare, {"reviewed": ["0"]})["total"] == 0
    assert tracker_events.lista(stare, {"reviewed": ["1"]})["events"][0]["id"] == saved["id"]


def test_tracker_event_can_create_manual_dossier_note(tmp_path):
    stare = state(tmp_path)
    create(stare)
    saved = tracker_events.adauga(
        stare,
        event(id="e" * 32, content_hash="a" * 64),
    )["event"]

    out = tracker_events.creeaza_nota_dosar(
        stare,
        {
            "id": saved["id"],
            "dosar_id": ID,
            "note_id": "b" * 32,
            "reasoning": "Evenimentul schimbă termenul de analiză al dosarului.",
        },
    )

    assert out["note"]["id"] == "b" * 32
    assert out["note"]["act_id"] == "PL-x 10/2026"
    assert out["note"]["locator"] == "committee_assignment"
    assert out["note"]["type"] == "necorelare"
    assert out["note"]["status"] == "ready_for_review"
    assert out["note"]["source_hash"] == "a" * 64
    assert note_manuale.lista(dosare.cale(stare), ID)["total"] == 1


def test_tracker_store_reports_missing_database_without_creating_file(tmp_path):
    stare = state(tmp_path)

    out = tracker_events.lista(stare)

    assert out["source_status"] == "missing"
    assert out["events"] == []
    assert not tracker_events.cale(stare).exists()


def test_tracker_store_validates_event_shape(tmp_path):
    stare = state(tmp_path)

    with pytest.raises(ValueError, match="necunoscut"):
        tracker_events.adauga(stare, event(event_type="invented"))
    with pytest.raises(ValueError, match="Dată"):
        tracker_events.adauga(stare, event(occurred_at="not-a-date"))
    with pytest.raises(ValueError, match="Payload"):
        tracker_events.adauga(stare, event(payload=[]))
    with pytest.raises(ValueError, match="Paginare"):
        tracker_events.lista(stare, {"limit": ["999"]})
    with pytest.raises(ValueError, match="Filtru"):
        tracker_events.lista(stare, {"reviewed": ["maybe"]})


def _get_request(stare, query=""):
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/tracker-evenimente" + query
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    handler.do_GET()
    return result[0]


def _post_request(stare, payload):
    raw = json.dumps(payload).encode()
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/tracker-evenimente"
    handler.rfile = io.BytesIO(raw)
    handler.headers = {
        "Host": "localhost:8123",
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    handler.do_POST()
    return result[0]


def test_http_tracker_endpoint_reads_and_writes_events(tmp_path):
    stare = state(tmp_path)

    code, data = _post_request(stare, {"action": "add", **event()})
    assert code == 200
    assert data["event"]["event_type"] == "committee_assignment"

    code, data = _get_request(stare, "?project_id=PL-x%2010/2026")
    assert code == 200
    assert data["total"] == 1
    event_id = data["events"][0]["id"]
    code, data = _post_request(
        stare, {"action": "review", "id": event_id, "reviewer": "ana", "note": "ok"}
    )
    assert code == 200
    assert data["event"]["review"]["reviewed"] is True
    assert _get_request(stare, "?limit=bad")[0] == 400
