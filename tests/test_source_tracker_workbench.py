import io
from types import SimpleNamespace

from scripts import depozit, source_registry, source_tracker_workbench, tracker_events
from scripts.server import face_handler


def state(tmp_path):
    return SimpleNamespace(
        corpus=tmp_path / "corpus.db",
        initiative=tmp_path / "initiative.db",
        eu=tmp_path / "eu.db",
    )


def request(stare, method, url):
    handler = object.__new__(face_handler(stare))
    handler.path = url
    handler.rfile = io.BytesIO(b"")
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def seed_workbench(tmp_path):
    stare = state(tmp_path)
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 10/2026',2,'10','Lege urmărită','Raport depus',"
            "'2026-09-12T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect10')"
        )
        con.execute(
            "INSERT INTO initiativa_etapa(plx_id,ord,data,camera,actiune) "
            "VALUES ('PL-x 10/2026',1,'2026-09-12','Camera Deputaților','Raport depus')"
        )
        con.commit()
    source = source_registry.descopera(
        stare,
        {
            "family": "camera",
            "identifier": "PL-x 10/2026",
            "url": "https://www.cdep.ro/proiect10",
            "label": "Fișă proiect urmărit",
        },
    )
    source_registry.pune_in_coada(stare, source["id"])
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "fetched",
            "content_hash": "a" * 64,
            "parser_version": "test.v1",
        },
    )
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "changed",
            "content_hash": "b" * 64,
            "parser_version": "test.v1",
        },
    )
    tracker_events.adauga(
        stare,
        {
            "event_type": "report_filed",
            "project_id": "PL-x 10/2026",
            "source_family": "camera",
            "source_id": source["id"],
            "source_url": "https://www.cdep.ro/proiect10",
            "occurred_at": "2026-09-12T12:00:00+00:00",
            "title": "Raport depus",
            "content_hash": "b" * 64,
            "payload": {"committee": "Comisia juridică"},
        },
    )
    return stare, source


def test_source_tracker_workbench_groups_sources_tracker_lifecycle_and_actions(tmp_path):
    stare, source = seed_workbench(tmp_path)

    out = source_tracker_workbench.build(stare)

    assert out["contract"] == "source-tracker-lifecycle-workbench-v1"
    assert out["summary"]["sources_attention"] == 1
    assert out["summary"]["tracker_unreviewed"] == 1
    assert out["summary"]["projects_attention"] >= 1
    assert out["summary"]["reviewable_sources"] >= 1
    assert out["summary"]["evidence_links"] >= 2
    assert out["counts"]["source"] == 1
    assert out["counts"]["tracker_event"] == 1
    assert out["counts"]["project_lifecycle"] >= 1
    assert any(action["key"] == "review_tracker_events" for action in out["next_actions"])
    assert any(action["key"] == "review_changed_sources" for action in out["next_actions"])
    source_row = next(row for row in out["rows"] if row["kind"] == "source")
    assert source_row["source_id"] == source["id"]
    assert source_row["actions"]["review_source"] is True
    assert source_row["actions"]["open_evidence"] is True
    assert source_row["official_url"] == "https://www.cdep.ro/proiect10"
    event_row = next(row for row in out["rows"] if row["kind"] == "tracker_event")
    assert event_row["actions"]["review_event"] is True
    assert event_row["content_hash"] == "b" * 64


def test_http_source_tracker_workbench_route(tmp_path):
    stare, _source = seed_workbench(tmp_path)

    code, data = request(stare, "GET", "/api/source-tracker-workbench?event_limit=10")

    assert code == 200
    assert data["contract"] == "source-tracker-lifecycle-workbench-v1"
    assert data["summary"]["tracker_unreviewed"] == 1


def test_source_tracker_workbench_validates_limits(tmp_path):
    try:
        source_tracker_workbench.build(state(tmp_path), {"event_limit": ["999"]})
    except ValueError as exc:
        assert "Limită workbench" in str(exc)
    else:
        raise AssertionError("expected invalid workbench limit")
