import io
from types import SimpleNamespace

from scripts import dosare, note_manuale, project_evidence_pack, tracker_events
from scripts.server import face_handler
from tests.test_dosare import ID, create


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def add_event(stare, **patch):
    data = {
        "event_type": "public_consultation_opened",
        "project_id": "PL-x 10/2026",
        "source_family": "consultare_econsultare",
        "source_url": "https://e-consultare.gov.ro/consultare/10",
        "occurred_at": "2026-09-12T10:00:00+00:00",
        "title": "Consultare deschisă",
        "payload": {"authority": "MDLPA", "stage": "consultare"},
        "content_hash": "a" * 64,
    }
    data.update(patch)
    return tracker_events.adauga(stare, data)["event"]


def test_project_evidence_pack_collects_tracker_and_dossier_notes(tmp_path):
    stare = state(tmp_path)
    create(stare)
    event = add_event(stare)
    tracker_events.marcheaza_revizuit(
        stare, {"id": event["id"], "reviewer": "ana", "note": "corelat cu fișa sursei"}
    )
    note_manuale.salveaza(
        dosare.cale(stare),
        {
            "id": "b" * 32,
            "dosar_id": ID,
            "revizie": 0,
            "title": "Risc consultare",
            "type": "necorelare",
            "act_id": "PL-x 10/2026",
            "locator": "consultare",
            "evidence_quote": "Consultarea publică este deschisă.",
            "source_url": "https://e-consultare.gov.ro/consultare/10",
            "source_hash": "a" * 64,
            "reasoning": "Trebuie corelată înainte de redactare.",
            "status": "ready_for_review",
        },
    )

    out = project_evidence_pack.build(stare, {"project_id": ["PL-x 10/2026"], "dossier_id": [ID]})

    assert out["contract"] == "project-evidence-pack-v1"
    assert out["summary"]["events"] == 1
    assert out["summary"]["reviewed_events"] == 1
    assert out["summary"]["notes"] == 1
    assert out["evidence"][0]["source_family"] == "consultare_econsultare"
    assert out["dossier_notes"][0]["title"] == "Risc consultare"
    assert any("nu verdict juridic" in item for item in out["limitari"])


def test_project_evidence_pack_reports_missing_tracker_without_creating_file(tmp_path):
    stare = state(tmp_path)

    out = project_evidence_pack.build(stare, {"project_id": ["PL-x 10/2026"]})

    assert out["source_status"] == "missing"
    assert out["summary"]["events"] == 0
    assert out["next_actions"] == [
        "Sincronizează sursele proiectului sau verifică identificatorul proiectului."
    ]
    assert not tracker_events.cale(stare).exists()


def test_project_evidence_pack_validates_project_id(tmp_path):
    stare = state(tmp_path)

    try:
        project_evidence_pack.build(stare, {"project_id": ["<bad>"]})
    except ValueError as exc:
        assert "Identificator" in str(exc)
    else:
        raise AssertionError("Expected invalid project id")


def test_http_project_evidence_pack_endpoint_reads_pack(tmp_path):
    stare = state(tmp_path)
    add_event(stare)
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/project-evidence-pack?project_id=PL-x%2010/2026"
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_GET()

    code, data = result[0]
    assert code == 200
    assert data["contract"] == "project-evidence-pack-v1"
    assert data["summary"]["events"] == 1
