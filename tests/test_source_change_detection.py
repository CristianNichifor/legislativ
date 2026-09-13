from scripts.source_change_detection import detect_changes


def test_detects_project_documents_reports_votes_and_monitor_publication():
    previous = {
        "content_hash": "a" * 64,
        "documents": [{"url": "https://example.test/initial.pdf", "label": "Expunere"}],
    }
    current = {
        "content_hash": "b" * 64,
        "monitorul_oficial": "MO 10/2026",
        "documents": [
            {"url": "https://example.test/initial.pdf", "label": "Expunere"},
            {"url": "https://example.test/raport.pdf", "label": "Raport favorabil"},
            {"url": "https://example.test/vot.pdf", "label": "Vot final"},
        ],
    }

    out = detect_changes(previous, current)

    assert out["contract"] == "source-change-detection-v1"
    assert out["changed"] is True
    assert out["severity"] == "attention"
    assert [change["type"] for change in out["changes"]] == [
        "new_committee_report",
        "new_vote",
        "published_in_monitor",
    ]


def test_detects_consultation_deadline_and_closed_state():
    out = detect_changes(
        {"summary": {"deadline": "2026-09-20", "status": "open"}},
        {"summary": {"deadline": "2026-09-25", "status": "closed"}},
    )

    assert [change["type"] for change in out["changes"]] == [
        "deadline_changed",
        "consultation_closed",
    ]
    assert out["changes"][0]["before"] == "2026-09-20"
    assert out["changes"][0]["after"] == "2026-09-25"


def test_detects_typed_timeline_events_without_guessing_other_events():
    out = detect_changes(
        {"events": [{"id": "e1", "event_type": "registered"}]},
        {
            "events": [
                {"id": "e1", "event_type": "registered"},
                {"id": "e2", "event_type": "report_filed", "title": "Raport depus"},
                {"id": "e3", "event_type": "final_vote", "title": "Vot final"},
                {"id": "e4", "event_type": "other", "title": "Corectură minoră"},
            ]
        },
    )

    assert [change["type"] for change in out["changes"]] == [
        "new_committee_report",
        "new_vote",
    ]


def test_hash_only_change_is_explicitly_unclassified():
    out = detect_changes({"content_hash": "a" * 64}, {"content_hash": "b" * 64})

    assert out["changed"] is True
    assert out["severity"] == "attention"
    assert out["changes"][0]["type"] == "content_hash_changed"
    assert "parserul nu a clasificat" in out["changes"][0]["label"]


def test_unchanged_snapshots_return_none_severity():
    out = detect_changes(
        {"content_hash": "a" * 64, "documents": [{"url": "https://example.test/a.pdf"}]},
        {"content_hash": "a" * 64, "documents": [{"url": "https://example.test/a.pdf"}]},
    )

    assert out["changed"] is False
    assert out["severity"] == "none"
    assert out["changes"] == []
