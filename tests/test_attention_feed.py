import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

from scripts import attention_feed, depozit, source_registry, tracker_events
from scripts.cdep import Initiativa


def state(tmp_path):
    return SimpleNamespace(
        corpus=tmp_path / "corpus.db",
        initiative=tmp_path / "initiative.db",
        eu=tmp_path / "eu.db",
    )


def test_attention_feed_combines_registry_tracker_and_lifecycle_items(tmp_path):
    stare = state(tmp_path)
    source = source_registry.descopera(
        stare, {"family": "camera", "identifier": "PL-x 10/2026", "label": "Fișă proiect"}
    )
    source_registry.pune_in_coada(stare, source["id"])
    source_registry.inregistreaza(
        stare,
        {"id": source["id"], "state": "failed", "error_category": "fetch_failed"},
    )
    with depozit.deschide(stare.initiative) as con:
        depozit.scrie_initiativa(
            con,
            Initiativa(
                plx_id="PL-x 11/2026",
                cam=2,
                idp="11",
                senat_id="",
                tip="propunere",
                titlu="Proiect cu stadiu necunoscut",
                obiect="test",
                urgenta=False,
                stadiu="",
                camera_decizionala="Camera Deputaților",
                data_inreg="2026-01-01",
                sursa_url="https://www.cdep.ro/p",
            ),
        )
    tracker_events.adauga(
        stare,
        {
            "event_type": "opinion_received",
            "project_id": "PL-x 10/2026",
            "source_family": "avize",
            "source_url": "https://www.cdep.ro/p",
            "occurred_at": "2026-01-05T00:00:00+00:00",
            "title": "Aviz primit",
            "payload": {"issuer": "Consiliul Legislativ"},
        },
    )

    out = attention_feed.lista(stare)

    assert out["contract"] == "legislative-attention-feed-v1"
    assert out["counts"]["source"] == 1
    assert out["counts"]["tracker_event"] == 1
    assert out["counts"]["project_lifecycle"] == 1
    assert any(item["source_family"] == "avize" for item in out["items"])


def test_attention_feed_surfaces_deadline_soon_source_snapshot_without_fetching(tmp_path):
    stare = state(tmp_path)
    source = source_registry.descopera(
        stare,
        {
            "family": "consultare_econsultare",
            "identifier": "consultare-1",
            "label": "Consultare buget",
            "url": "https://e-consultare.gov.ro/consultare/1",
        },
    )
    source_registry._store_snapshot(
        stare,
        source["id"],
        "a" * 64,
        {
            "contract": "econsultare-snapshot-v1",
            "summary": {
                "title": "Consultare buget",
                "deadline": "2026-09-20",
                "status": "open",
            },
        },
        "test.v1",
    )

    original_now = attention_feed.datetime

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 11, tzinfo=tz or UTC)

    attention_feed.datetime = FixedDatetime
    try:
        out = attention_feed.lista(stare)
    finally:
        attention_feed.datetime = original_now

    item = out["items"][0]
    assert item["kind"] == "source"
    assert item["state"] == "deadline_soon"
    assert item["attention_label"] == "Termen apropiat"
    assert item["deadline"]["days_until"] == 9


def test_attention_feed_surfaces_recent_lifecycle_stage_change(tmp_path):
    stare = state(tmp_path)
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 40/2026',2,'40','Lege stage','Raport depus',"
            "'2026-09-11T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect40')"
        )
        con.execute(
            "INSERT INTO initiativa_etapa(plx_id,ord,data,camera,actiune) "
            "VALUES ('PL-x 40/2026',1,'2026-09-10','Camera Deputaților','Raport depus')"
        )
        con.commit()

    original_now = attention_feed.lifecycle.datetime

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 11, tzinfo=tz or UTC)

    attention_feed.lifecycle.datetime = FixedDatetime
    try:
        out = attention_feed.lista(stare)
    finally:
        attention_feed.lifecycle.datetime = original_now

    item = next(item for item in out["items"] if item["kind"] == "project_lifecycle")
    assert item["state"] == "recent_stage_change"
    assert item["attention_label"] == "Stadiu schimbat recent"
    assert item["project_id"] == "PL-x 40/2026"


def test_attention_feed_validates_limit(tmp_path):
    try:
        attention_feed.lista(state(tmp_path), {"limit": ["999"]})
    except ValueError as exc:
        assert "Limită" in str(exc)
    else:
        raise AssertionError("expected invalid limit")


def test_http_attention_feed_route(tmp_path):
    from scripts.server import face_handler

    stare = state(tmp_path)
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/needs-attention?limit=10"
    handler.rfile = None
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_GET()

    assert result[0][0] == 200
    assert result[0][1]["contract"] == "legislative-attention-feed-v1"


def test_http_monitor_replay_route_stores_publication_event(tmp_path):
    from scripts.server import face_handler

    stare = state(tmp_path)
    with sqlite3.connect(stare.corpus) as con:
        con.execute(
            "CREATE TABLE documente (cheie_act TEXT, id_portal TEXT, publicat TEXT, "
            "monitor INTEGER, republicare INTEGER, sursa_url TEXT, text TEXT, adus_la TEXT)"
        )
        con.execute(
            "INSERT INTO documente VALUES (?,?,?,?,?,?,?,?)",
            (
                "lege-98-2016",
                "178667",
                "2016-05-23",
                390,
                0,
                "https://legislatie.just.ro/Public/DetaliiDocument/178667",
                "",
                "2026-09-12T10:00:00+00:00",
            ),
        )
    with depozit.deschide(stare.initiative):
        pass
    raw = b'{"limit": 20}'
    handler = object.__new__(face_handler(stare))
    handler.path = "/api/monitor-reconciliere"
    handler.rfile = SimpleNamespace(read=lambda length: raw)
    handler.headers = {
        "Host": "localhost:8123",
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_POST()

    assert result[0][0] == 200
    assert result[0][1]["stored"] == 1
    listed = tracker_events.lista(stare, {"event_type": ["published_in_monitor"]})
    assert listed["total"] == 1
