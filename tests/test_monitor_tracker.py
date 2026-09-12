import sqlite3
from types import SimpleNamespace

from scripts import monitor_tracker, tracker_events


def test_act_publication_text_becomes_published_in_monitor_event():
    event = monitor_tracker.event_from_act_row(
        {
            "cheie_act": "lege-98-2016",
            "id_portal": "178667",
            "sursa_url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
            "text": "LEGE nr. 98 din 19 mai 2016\n"
            "Publicat in MONITORUL OFICIAL AL ROMANIEI, PARTEA I, nr. 390 "
            "din 23 mai 2016",
            "adus_la": "2026-09-12T10:00:00+00:00",
        }
    )

    assert event["event_type"] == "published_in_monitor"
    assert event["project_id"] == "lege-98-2016"
    assert event["source_family"] == "monitorul_oficial_pi"
    assert event["source_id"] == "178667"
    assert event["occurred_at"] == "2016-05-23T00:00:00+00:00"
    assert event["payload"]["part"] == "I"
    assert event["payload"]["number"] == 390
    assert event["payload"]["date"] == "2016-05-23"
    assert event["payload"]["act_id"] == "lege-98-2016"
    assert event["payload"]["source_hash"]


def test_republication_is_carried_in_payload_not_flattened():
    event = monitor_tracker.event_from_act_row(
        {
            "cheie_act": "lege-1-2000",
            "text": "Republicata in MONITORUL OFICIAL nr. 720 din 24 septembrie 2015",
        }
    )

    assert event["title"].startswith("Republicat in Monitorul Oficial")
    assert event["payload"]["republication"] is True


def test_project_status_with_monitor_reference_becomes_project_event():
    event = monitor_tracker.event_from_project_row(
        {
            "plx_id": "PL-x 10/2026",
            "stadiu": "Publicata in Monitorul Oficial nr. 100 din 5 martie 2026",
            "sursa_url": "https://www.cdep.ro/proiect",
            "citit_la": "2026-03-06T08:00:00+00:00",
        }
    )

    assert event["project_id"] == "PL-x 10/2026"
    assert event["payload"]["raw_status"].startswith("Publicata")
    assert event["payload"]["number"] == 100
    assert event["occurred_at"] == "2026-03-05T00:00:00+00:00"


def test_incomplete_and_non_part_i_references_do_not_emit():
    assert (
        monitor_tracker.event_from_project_row(
            {"plx_id": "PL-x 1/2026", "stadiu": "Publicata in Monitorul Oficial"}
        )
        is None
    )
    assert (
        monitor_tracker.event_from_act_row(
            {
                "cheie_act": "act-1",
                "text": "Publicat in MONITORUL OFICIAL, PARTEA II, nr. 10 din 1 mai 2026",
            }
        )
        is None
    )


def test_local_act_events_read_existing_document_publication_rows(tmp_path):
    db = tmp_path / "corpus.db"
    with sqlite3.connect(db) as con:
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

    events = monitor_tracker.local_act_events(db)

    assert len(events) == 1
    assert events[0]["payload"]["number"] == 390
    assert events[0]["payload"]["date"] == "2016-05-23"


def test_replay_to_tracker_uses_existing_store_deduplication(tmp_path):
    corpus = tmp_path / "corpus.db"
    tracker = tmp_path / "tracker.db"
    with sqlite3.connect(corpus) as con:
        con.execute(
            "CREATE TABLE documente (cheie_act TEXT, id_portal TEXT, publicat TEXT, "
            "monitor INTEGER, republicare INTEGER, sursa_url TEXT, text TEXT, adus_la TEXT)"
        )
        con.executemany(
            "INSERT INTO documente VALUES (?,?,?,?,?,?,?,?)",
            [
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
            ],
        )

    state = SimpleNamespace(tracker_events_db=tracker)
    first = monitor_tracker.replay_to_tracker(state, corpus_db=corpus)
    second = monitor_tracker.replay_to_tracker(state, corpus_db=corpus)
    listed = tracker_events.lista(state, {"event_type": ["published_in_monitor"]})

    assert first["stored"] == 1
    assert second["stored"] == 1
    assert listed["total"] == 1
    assert listed["events"][0]["payload"]["act_id"] == "lege-98-2016"


def test_reconcile_flags_missing_metadata_when_text_has_monitor_line():
    result = monitor_tracker.reconcile_act_row(
        {
            "cheie_act": "lege-98-2016",
            "text": "Publicat in MONITORUL OFICIAL AL ROMANIEI, PARTEA I, nr. 390 din 23 mai 2016",
        }
    )

    assert result["status"] == "needs_review"
    assert result["issues"] == ["missing_monitor_number", "missing_publication_date"]
    assert result["parsed"] == {"number": 390, "date": "2016-05-23"}
    assert result["event_available"] is True


def test_reconcile_flags_monitor_number_and_date_mismatches():
    result = monitor_tracker.reconcile_act_row(
        {
            "cheie_act": "lege-98-2016",
            "publicat": "2016-05-24",
            "monitor": 391,
            "text": "Publicat in MONITORUL OFICIAL AL ROMANIEI, PARTEA I, nr. 390 din 23 mai 2016",
        }
    )

    assert result["status"] == "needs_review"
    assert result["issues"] == ["monitor_number_mismatch", "publication_date_mismatch"]
    assert result["metadata"] == {"number": 391, "date": "2016-05-24"}
    assert result["parsed"] == {"number": 390, "date": "2016-05-23"}


def test_reconcile_rows_summarizes_issue_counts():
    report = monitor_tracker.reconcile_rows(
        [
            {
                "cheie_act": "lege-98-2016",
                "publicat": "2016-05-23",
                "monitor": 390,
                "text": "Publicat in MONITORUL OFICIAL nr. 390 din 23 mai 2016",
            },
            {
                "cheie_act": "lege-1-2026",
                "text": "Publicat in MONITORUL OFICIAL nr. 10 din 2 februarie 2026",
            },
        ]
    )

    assert report["contract"] == "monitor-publication-reconciliation-v1"
    assert report["total"] == 2
    assert report["needs_review"] == 1
    assert report["counts"] == {"missing_monitor_number": 1, "missing_publication_date": 1}
