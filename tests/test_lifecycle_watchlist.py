import io
import json
from types import SimpleNamespace

from scripts import depozit, lifecycle_watchlist, source_registry, tracker_events
from scripts.server import face_handler


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def seed_project(stare):
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 10/2026',2,'10','Lege urmărită','Raport depus',"
            "'2026-09-12T10:00:00+00:00','2026-09-01',"
            "'https://www.cdep.ro/pls/proiecte/upl_pck.proiect?idp=10')"
        )
        con.execute(
            "INSERT INTO initiativa_etapa(plx_id,ord,data,camera,actiune) "
            "VALUES ('PL-x 10/2026',1,'2026-09-12','Camera Deputaților','Raport depus')"
        )
        con.commit()


def add_event(stare, event_type, source_family, title, occurred_at, **payload):
    return tracker_events.adauga(
        stare,
        {
            "event_type": event_type,
            "project_id": "PL-x 10/2026",
            "source_family": source_family,
            "source_url": payload.pop("source_url", "https://www.cdep.ro/proiect10"),
            "occurred_at": occurred_at,
            "title": title,
            "payload": payload,
        },
    )["event"]


def test_lifecycle_watchlist_follow_surfaces_public_path_status_and_missing_evidence(tmp_path):
    stare = state(tmp_path)
    seed_project(stare)
    add_event(
        stare,
        "public_consultation_opened",
        "consultare_econsultare",
        "Consultare publică deschisă",
        "2026-09-01T10:00:00+00:00",
        source_url="https://e-consultare.gov.ro/consultare/10",
        authority="MDLPA",
    )
    add_event(
        stare,
        "committee_assignment",
        "camera",
        "Comisie sesizată",
        "2026-09-08T10:00:00+00:00",
        committee="Comisia juridică",
    )
    add_event(
        stare,
        "report_filed",
        "camera",
        "Raport depus",
        "2026-09-12T10:00:00+00:00",
        committee="Comisia juridică",
    )

    lifecycle_watchlist.adauga(
        stare, {"project_id": "PL-x 10/2026", "label": "Lege urmărită"}
    )
    out = lifecycle_watchlist.lista(stare)

    assert out["contract"] == "project-lifecycle-watchlist-v1"
    item = out["items"][0]
    assert item["project_id"] == "PL-x 10/2026"
    assert item["state"] == "changed"
    assert item["needs_attention"] is True
    assert item["stage"]["key"] == "report"
    assert item["latest_stage"]["key"] == "report"
    assert item["latest_stage"]["timestamp"] == "2026-09-12T10:00:00+00:00"
    assert item["source"]["url"].startswith("https://www.cdep.ro/")
    assert item["source"]["timestamp"] == "2026-09-01"
    assert item["uncertainty"]["level"] == "low"
    coverage = {row["key"]: row["state"] for row in item["path_coverage"]}
    assert coverage["consultation"] == "present"
    assert coverage["committee"] == "present"
    assert coverage["report"] == "present"
    assert coverage["opinion"] == "missing"
    assert coverage["vote"] == "missing"
    assert coverage["publication"] == "missing"
    assert "missing_publication" in item["missing"]


def test_lifecycle_watchlist_becomes_user_complete_when_path_events_exist(tmp_path):
    stare = state(tmp_path)
    seed_project(stare)
    for event_type, family, title, when, payload in [
        (
            "public_consultation_opened",
            "consultare_econsultare",
            "Consultare publică deschisă",
            "2026-09-01T10:00:00+00:00",
            {"source_url": "https://e-consultare.gov.ro/consultare/10"},
        ),
        ("committee_assignment", "camera", "Comisie sesizată", "2026-09-08T10:00:00+00:00", {}),
        ("opinion_received", "avize", "Aviz primit", "2026-09-09T10:00:00+00:00", {}),
        ("report_filed", "camera", "Raport depus", "2026-09-12T10:00:00+00:00", {}),
        ("vote_recorded", "senat", "Vot înregistrat", "2026-09-13T10:00:00+00:00", {}),
        (
            "published_in_monitor",
            "monitorul_oficial_pi",
            "Publicat în Monitorul Oficial",
            "2026-09-14T10:00:00+00:00",
            {"source_url": "https://legislatie.just.ro/Public/DetaliiDocument/10"},
        ),
    ]:
        add_event(stare, event_type, family, title, when, **payload)
    lifecycle_watchlist.adauga(stare, {"project_id": "PL-x 10/2026"})

    item = lifecycle_watchlist.lista(stare)["items"][0]

    assert {row["state"] for row in item["path_coverage"]} == {"present"}
    assert item["latest_stage"]["key"] == "published"
    assert item["latest_stage"]["source_family"] == "monitorul_oficial_pi"
    assert item["latest_stage"]["source_url"] == "https://legislatie.just.ro/Public/DetaliiDocument/10"


def test_lifecycle_watchlist_tracks_registry_changes_and_review_marker(tmp_path):
    stare = state(tmp_path)
    seed_project(stare)
    source = source_registry.descopera(
        stare,
        {
            "family": "camera",
            "identifier": "PL-x 10/2026",
            "url": "https://www.cdep.ro/proiect10",
            "label": "Fișă CDEP",
        },
    )
    source_registry.pune_in_coada(stare, source["id"])
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "fetched",
            "content_hash": "0" * 64,
            "parser_version": "test",
        },
    )
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "changed",
            "content_hash": "a" * 64,
            "parser_version": "test",
        },
    )
    lifecycle_watchlist.adauga(stare, {"project_id": "PL-x 10/2026"})

    changed = lifecycle_watchlist.lista(stare)["items"][0]
    assert changed["state"] == "changed"
    assert changed["source"]["registry_source_id"] == source["id"]
    assert "tracked_source_needs_review" in changed["uncertainty"]["reasons"]

    reviewed = lifecycle_watchlist.marcheaza_revizuit(
        stare, {"project_id": "PL-x 10/2026", "note": "Verificat."}
    )
    assert reviewed["reviewed"] is True


def _request(stare, method, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/lifecycle-watchlist"
    handler.rfile = io.BytesIO(raw)
    handler.headers = {
        "Host": "localhost:8123",
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_http_lifecycle_watchlist_endpoint_reads_and_writes(tmp_path):
    stare = state(tmp_path)
    seed_project(stare)

    code, data = _request(stare, "POST", {"action": "add", "project_id": "PL-x 10/2026"})
    assert code == 200
    assert data["watch"]["project_id"] == "PL-x 10/2026"

    code, data = _request(stare, "GET")
    assert code == 200
    assert data["items"][0]["project_id"] == "PL-x 10/2026"

    code, data = _request(
        stare, "POST", {"action": "review", "project_id": "PL-x 10/2026", "note": "ok"}
    )
    assert code == 200
    assert data["watch"]["reviewed"] is True

    code, data = _request(stare, "POST", {"action": "delete", "project_id": "PL-x 10/2026"})
    assert code == 200
    assert data["deleted"] is True
