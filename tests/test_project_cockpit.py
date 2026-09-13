import io
from types import SimpleNamespace

import pytest

from scripts import depozit, dosare, note_manuale, project_cockpit, source_registry, tracker_events
from scripts.server import face_handler
from tests.test_dosare import ID, create


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def add_project(stare):
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 10/2026',2,'10','Lege cockpit','Raport depus',"
            "'2026-09-10T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect10')"
        )
        con.commit()


def add_event(stare, **patch):
    data = {
        "event_type": "report_filed",
        "project_id": "PL-x 10/2026",
        "source_family": "camera",
        "source_url": "https://www.cdep.ro/proiect10",
        "occurred_at": "2026-09-12T10:00:00+00:00",
        "title": "Raport depus",
        "payload": {"stage": "report"},
        "content_hash": "a" * 64,
    }
    data.update(patch)
    return tracker_events.adauga(stare, data)["event"]


def add_attention_source(stare):
    row = source_registry.executa(stare, {"family": "camera", "identifier": "PL-x 10/2026"})
    source_registry.executa(stare, {"action": "queue", "id": row["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "fetched",
            "content_hash": "a" * 64,
            "parser_version": "test",
        },
    )
    return source_registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "changed",
            "content_hash": "b" * 64,
            "parser_version": "test",
        },
    )


def test_project_cockpit_combines_lifecycle_tracker_source_and_evidence(tmp_path):
    stare = state(tmp_path)
    create(stare)
    add_project(stare)
    add_event(stare)
    add_attention_source(stare)
    note_manuale.salveaza(
        dosare.cale(stare),
        {
            "id": "b" * 32,
            "dosar_id": ID,
            "revizie": 0,
            "title": "Lacună de redactare",
            "type": "lacuna",
            "act_id": "PL-x 10/2026",
            "locator": "art. 1",
            "evidence_quote": "Raport depus.",
            "source_url": "https://www.cdep.ro/proiect10",
            "source_hash": "a" * 64,
            "reasoning": "Trebuie verificată corelarea cu raportul.",
            "status": "ready_for_review",
        },
    )

    out = project_cockpit.build(
        stare, {"project_id": ["PL-x 10/2026"], "dossier_id": [ID], "event_limit": ["20"]}
    )

    assert out["contract"] == "project-cockpit-summary-v1"
    assert out["lifecycle"]["project"]["project_id"] == "PL-x 10/2026"
    assert out["tracker"]["total"] == 1
    assert out["tracker"]["unreviewed"] == 1
    assert out["tracker"]["by_stage"]["report"]["count"] == 1
    assert out["tracker"]["latest_event"]["event_type"] == "report_filed"
    assert out["source_attention"]["needs_attention"] is True
    assert out["source_attention"]["registry_source_state"] == "changed"
    assert out["source_attention"]["source_family"] == "camera"
    assert out["source_attention"]["source_family_label"] == "Camera Deputaților"
    assert out["source_attention"]["source_label"] == "PL-x 10/2026"
    assert out["source_attention"]["next_action"] == "Revizuiește schimbarea sursei urmărite."
    assert out["evidence_pack"]["notes"] == 1
    assert {action["key"] for action in out["next_actions"]} >= {
        "review_tracker_events",
        "sync_attention_sources",
        "open_evidence_pack",
    }
    assert any("nu reprezintă verdict juridic" in item for item in out["limitari"])


def test_project_cockpit_reports_local_limitations_without_creating_tracker(tmp_path):
    stare = state(tmp_path)
    add_project(stare)

    out = project_cockpit.build(stare, {"project_id": ["PL-x 10/2026"]})

    assert out["tracker"]["total"] == 0
    assert out["evidence_pack"]["available"] is True
    assert out["next_actions"][0]["key"] == "link_dossier"
    assert not tracker_events.cale(stare).exists()


def test_project_cockpit_validates_identifiers_and_limits(tmp_path):
    stare = state(tmp_path)

    with pytest.raises(ValueError, match="Identificator"):
        project_cockpit.build(stare, {"project_id": ["<bad>"]})
    with pytest.raises(ValueError, match="Paginare"):
        project_cockpit.build(stare, {"project_id": ["PL-x 10/2026"], "event_limit": ["101"]})


def test_http_project_cockpit_endpoint_reads_summary(tmp_path):
    stare = state(tmp_path)
    add_project(stare)
    add_event(stare)
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/project-cockpit?project_id=PL-x%2010/2026"
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_GET()

    code, data = result[0]
    assert code == 200
    assert data["contract"] == "project-cockpit-summary-v1"
    assert data["tracker"]["total"] == 1
