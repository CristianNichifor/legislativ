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
        "payload": {
            "authority": "MDLPA",
            "stage": "consultare",
            "evidence_quote": "Consultarea publică este deschisă.",
        },
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
    assert out["summary"]["drilldown_records"] == 2
    assert out["summary"]["missing_source_records"] == 0
    assert out["evidence"][0]["source_family"] == "consultare_econsultare"
    assert out["evidence"][0]["quote"] == "Consultarea publică este deschisă."
    assert out["evidence"][0]["source_hash"] == "a" * 64
    assert out["evidence"][0]["source_state"]["state"] == "available"
    assert out["evidence"][0]["uncertainty"]["level"] == "low"
    assert out["evidence"][0]["lifecycle_state"]["stage_key"] == "consultation_open"
    assert out["evidence"][0]["related_items"]["projects"][0]["id"] == "PL-x 10/2026"
    assert out["evidence"][0]["related_items"]["consultations"]
    assert out["evidence"][0]["not_legal_verdict"] is True
    assert out["evidence_records"][0]["contract"] == "evidence-drilldown-reference-v1"
    assert out["dossier_notes"][0]["title"] == "Risc consultare"
    assert out["dossier_notes"][0]["drilldown"]["quote"] == "Consultarea publică este deschisă."
    assert out["dossier_notes"][0]["drilldown"]["related_items"]["notes"][0]["id"] == "b" * 32
    assert any("nu verdict juridic" in item for item in out["limitari"])


def test_project_evidence_pack_drilldown_keeps_related_law_celex_monitor_rule_ids(tmp_path):
    stare = state(tmp_path)
    add_event(
        stare,
        event_type="published_in_monitor",
        source_family="monitorul_oficial_pi",
        source_url="https://monitoruloficial.ro/Monitorul-Oficial--PI--10--2026.html",
        source_id="monitor_pi_10_2026",
        title="Publicare Monitor",
        payload={
            "quote": "Legea a fost publicată în Monitorul Oficial.",
            "law_id": "lege-10-2026",
            "celex": "32024R0001",
            "monitor_number": "10/2026",
            "candidate_id": "rule-candidate-1",
        },
        content_hash="b" * 64,
    )

    out = project_evidence_pack.build(stare, {"project_id": ["PL-x 10/2026"]})
    drilldown = out["evidence"][0]["drilldown"]

    assert drilldown["quote"] == "Legea a fost publicată în Monitorul Oficial."
    assert drilldown["related_items"]["laws"][0]["id"] == "lege-10-2026"
    assert drilldown["related_items"]["celex"][0]["id"] == "32024R0001"
    assert any(item["id"] == "10/2026" for item in drilldown["related_items"]["monitor_references"])
    assert drilldown["related_items"]["rules"][0]["id"] == "rule-candidate-1"
    assert drilldown["not_legal_verdict"] is True


def test_project_evidence_pack_missing_source_rows_are_explicit_not_verdicts(tmp_path):
    stare = state(tmp_path)
    add_event(
        stare,
        event_type="public_consultation_source_unavailable",
        source_family="consultare_econsultare",
        source_url="",
        source_id="",
        title="Sursă consultare indisponibilă",
        payload={"status": "fetch_failed", "consultation_id": "ec-10"},
        content_hash="",
    )

    out = project_evidence_pack.build(stare, {"project_id": ["PL-x 10/2026"]})
    row = out["evidence"][0]

    assert out["summary"]["missing_source_records"] == 1
    assert row["source_state"] == {
        "state": "missing_source",
        "tracker_status": "ok",
        "missing": ["source_url", "source_hash"],
        "message": "Dovada nu are încă o sursă completă; nu poate susține o concluzie.",
    }
    assert row["uncertainty"]["level"] == "high"
    assert row["uncertainty"]["reasons"] == [
        "missing_source_url",
        "missing_source_hash",
        "missing_exact_quote",
        "human_review_pending",
    ]
    consultation_ids = {item["id"] for item in row["related_items"]["consultations"]}
    assert consultation_ids == {"PL-x 10/2026", "ec-10"}
    assert row["not_legal_verdict"] is True
    assert all("verdict juridic" in item for item in row["drilldown"]["limitations"][:1])


def test_project_evidence_pack_reports_missing_tracker_without_creating_file(tmp_path):
    stare = state(tmp_path)

    out = project_evidence_pack.build(stare, {"project_id": ["PL-x 10/2026"]})

    assert out["source_status"] == "missing"
    assert out["summary"]["events"] == 0
    assert out["summary"]["drilldown_records"] == 0
    assert out["summary"]["missing_source_records"] == 0
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
