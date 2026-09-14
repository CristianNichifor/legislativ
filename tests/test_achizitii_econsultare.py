import json
from types import SimpleNamespace

import pytest

from scripts import achizitii_econsultare as ec
from scripts import source_registry as registry
from scripts import tracker_events

HTML = """
<html>
  <body>
    <h1>Proiect de hotărâre privind serviciile publice</h1>
    <dl>
      <dt>Autoritate inițiatoare</dt><dd>Ministerul Dezvoltării</dd>
      <dt>Termen limită</dt><dd>15.10.2026</dd>
    </dl>
    <p>Documentul este în consultare publică.</p>
    <a href="/upload/proiect.pdf">Proiect act normativ</a>
    <a href="https://e-consultare.gov.ro/upload/fundamentare.docx">Notă de fundamentare</a>
  </body>
</html>
""".encode()

ACTIONGRID = json.dumps(
    {
        "results": [
            {
                "id": "3758",
                "datePublished": "2026-09-14T00:01:13.4750961+03:00",
                "fields": [
                    {"Name": "StartConsDesc", "FormattedValue": "11/09/2026"},
                    {"Name": "StatusProiect", "FormattedValue": "Consultare Publică"},
                    {
                        "Name": "Detalii1",
                        "FormattedValue": (
                            "Proiect de Ordin privind transporturile <br> "
                            "<i><small>Ordin de Ministru - MINISTERUL TRANSPORTURILOR"
                            "</small></i>"
                        ),
                    },
                    {
                        "Name": "Detaliiproiect",
                        "FormattedValue": (
                            'Detalii <a href="https://e-consultare.gov.ro/'
                            "Proiecte-Legislative-Publice/"
                            'Propunere-Proiecte-Dezbatere-Publica/a/b">'
                            "...mai multe detalii</a>"
                        ),
                    },
                    {
                        "Name": "Termeneproiectlegislativ",
                        "FormattedValue": (
                            "Interval Consultare Publica:11/09/2026 - 28/09/2026<br>"
                            "Termen limită transmitere propuneri: 28/09/2026"
                        ),
                    },
                ],
            }
        ]
    },
    ensure_ascii=False,
).encode()


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def test_econsultare_parser_extracts_bounded_snapshot():
    out = ec.parseaza(HTML, "https://e-consultare.gov.ro/consultare/123")

    assert out["contract"] == "econsultare-source-snapshot-v1"
    assert out["family"] == "consultare_econsultare"
    assert out["summary"] == {
        "title": "Proiect de hotărâre privind serviciile publice",
        "authority": "Ministerul Dezvoltării",
        "status": "open",
        "deadline": "15.10.2026",
        "deadline_iso": "2026-10-15",
        "documents": 2,
        "document_metadata": {
            "total": 2,
            "by_type": {"docx": 1, "pdf": 1},
            "with_hash": 0,
            "labels": ["Notă de fundamentare", "Proiect act normativ"],
        },
        "truncated": False,
    }
    assert out["documents"] == [
        {
            "url": "https://e-consultare.gov.ro/upload/fundamentare.docx",
            "label": "Notă de fundamentare",
        },
        {
            "url": "https://e-consultare.gov.ro/upload/proiect.pdf",
            "label": "Proiect act normativ",
        },
    ]
    assert len(ec.snapshot_hash(out)) == 64


def test_econsultare_rejects_non_official_urls():
    with pytest.raises(ValueError, match="e-consultare.gov.ro"):
        ec.url_oficial("https://example.com/consultare/123")


def test_econsultare_discovers_official_actiongrid_listing(monkeypatch):
    monkeypatch.setattr(ec, "descarca_actiongrid", lambda: (ACTIONGRID, 200))

    out = ec.descopera_actiongrid(limit=10)

    assert out["contract"] == "econsultare-actiongrid-discovery-v1"
    assert out["http_status"] == 200
    assert out["listing_url"] == "https://e-consultare.gov.ro/Consultare-public%C4%83"
    assert out["endpoint_url"].startswith("https://e-consultare.gov.ro/DesktopModules/")
    assert out["total"] == 1
    assert out["snapshots"][0]["url"].endswith("/a/b")
    assert out["snapshots"][0]["summary"]["authority"] == "MINISTERUL TRANSPORTURILOR"
    assert out["snapshots"][0]["summary"]["deadline"] == "28/09/2026"


def test_econsultare_snapshot_builds_open_tracker_event_candidate():
    snapshot = ec.parseaza(HTML, "https://e-consultare.gov.ro/consultare/123")

    candidate = ec.tracker_event_candidate(
        snapshot,
        source_id="src_123",
        content_hash="a" * 64,
        observed_at="2026-09-13T10:00:00+00:00",
    )

    assert candidate == {
        "event_type": "public_consultation_opened",
        "project_id": "https://e-consultare.gov.ro/consultare/123",
        "source_family": "consultare_econsultare",
        "source_id": "src_123",
        "source_url": "https://e-consultare.gov.ro/consultare/123",
        "occurred_at": "2026-10-15T00:00:00+00:00",
        "observed_at": "2026-09-13T10:00:00+00:00",
        "title": "Proiect de hotărâre privind serviciile publice",
        "payload": {
            "authority": "Ministerul Dezvoltării",
            "project_url": "https://e-consultare.gov.ro/consultare/123",
            "status": "open",
            "deadline": "2026-10-15T00:00:00+00:00",
            "documents": snapshot["documents"],
            "document_metadata": snapshot["document_metadata"],
        },
        "content_hash": "a" * 64,
    }


def test_econsultare_snapshot_builds_first_class_tracker_events():
    previous = ec.parseaza(HTML, "https://e-consultare.gov.ro/consultare/123")
    snapshot = ec.parseaza(
        HTML.replace(b"15.10.2026", b"20.10.2026").replace(
            b"</body>", b'<a href="/upload/impact.pdf">Studiu impact</a></body>'
        ),
        "https://e-consultare.gov.ro/consultare/123",
    )

    events = ec.tracker_event_candidates(
        snapshot,
        previous_snapshot=previous,
        source_id="src_123",
        content_hash="c" * 64,
        observed_at="2026-09-13T10:00:00+00:00",
    )

    by_type = {event["event_type"]: event for event in events}
    assert set(by_type) == {
        "public_consultation_announced",
        "public_consultation_opened",
        "public_consultation_deadline_changed",
        "public_consultation_document_added",
    }
    assert (
        by_type["public_consultation_deadline_changed"]["payload"]["previous_deadline"]
        == "2026-10-15T00:00:00+00:00"
    )
    assert (
        by_type["public_consultation_deadline_changed"]["payload"]["deadline"]
        == "2026-10-20T00:00:00+00:00"
    )
    assert by_type["public_consultation_document_added"]["payload"]["documents"] == [
        {
            "url": "https://e-consultare.gov.ro/upload/impact.pdf",
            "label": "Studiu impact",
        }
    ]


def test_econsultare_snapshot_builds_closed_tracker_event_candidate():
    snapshot = ec.parseaza(HTML, "https://e-consultare.gov.ro/consultare/123")
    snapshot["summary"]["status"] = "closed"
    snapshot["status"] = "closed"

    candidate = ec.tracker_event_candidate(
        snapshot,
        source_id="src_123",
        content_hash="b" * 64,
        observed_at="2026-09-13T10:00:00+00:00",
    )

    assert candidate["event_type"] == "public_consultation_closed"
    assert candidate["occurred_at"] == "2026-10-15T00:00:00+00:00"
    assert candidate["payload"] == {
        "authority": "Ministerul Dezvoltării",
        "project_url": "https://e-consultare.gov.ro/consultare/123",
        "status": "closed",
        "closed_at": "2026-10-15T00:00:00+00:00",
    }


def test_econsultare_tracker_candidate_uses_observed_at_without_deadline():
    snapshot = {
        "url": "https://e-consultare.gov.ro/consultare/123",
        "summary": {"title": "Consultare fără termen", "status": "unknown"},
        "documents": [],
    }

    candidate = ec.tracker_event_candidate(
        snapshot,
        source_id="src_123",
        observed_at="2026-09-13T10:00:00+00:00",
    )

    assert candidate["event_type"] == "public_consultation_opened"
    assert candidate["occurred_at"] == "2026-09-13T10:00:00+00:00"
    assert "deadline" not in candidate["payload"]
    events = ec.tracker_event_candidates(
        snapshot,
        source_id="src_123",
        observed_at="2026-09-13T10:00:00+00:00",
    )
    assert events[-1]["event_type"] == "public_consultation_metadata_review"


def test_registry_syncs_one_econsultare_source(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_econsultare",
            "url": "https://e-consultare.gov.ro/consultare/123",
            "label": "Consultare servicii publice",
        },
    )

    monkeypatch.setattr(ec, "descarca", lambda url: (HTML, 200))
    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert changed["state"] == "changed"
    assert changed["last_hash"]
    assert changed["parser_version"] == ec.PARSER_VERSION
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["sync_status"]["can_sync"] is True
    assert selected["snapshots"][0]["parser_version"] == ec.PARSER_VERSION
    assert selected["snapshots"][0]["summary"]["documents"] == 2
    events = tracker_events.lista(
        stare, {"source_family": ["consultare_econsultare"], "limit": ["10"]}
    )
    assert events["total"] == 2
    by_type = {event["event_type"]: event for event in events["events"]}
    assert {"public_consultation_announced", "public_consultation_opened"} <= set(by_type)
    assert by_type["public_consultation_opened"]["project_id"] == (
        "https://e-consultare.gov.ro/consultare/123"
    )
    assert by_type["public_consultation_opened"]["occurred_at"] == "2026-10-15T00:00:00+00:00"
    assert by_type["public_consultation_opened"]["payload"]["authority"] == "Ministerul Dezvoltării"
    assert by_type["public_consultation_opened"]["source_id"] == row["id"]
    assert by_type["public_consultation_opened"]["content_hash"] == changed["last_hash"]

    unchanged = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert unchanged["state"] == "unchanged"


def test_registry_econsultare_changed_and_needs_review(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_econsultare",
            "identifier": "https://e-consultare.gov.ro/consultare/123",
        },
    )
    monkeypatch.setattr(ec, "descarca", lambda url: (HTML, 200))
    first = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert first["state"] == "changed"

    changed_html = HTML.replace(b"15.10.2026", b"20.10.2026")
    monkeypatch.setattr(ec, "descarca", lambda url: (changed_html, 200))
    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert changed["state"] == "changed"
    assert changed["last_hash"] != first["last_hash"]
    assert changed["tracker_sync"]["event_types"]["public_consultation_deadline_changed"] == 1

    bare = b"<html><body><p>Consultare publica fara documente.</p></body></html>"
    monkeypatch.setattr(ec, "descarca", lambda url: (bare, 200))
    review = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert review["state"] == "needs_review"
    assert review["last_error"] == ""
    assert review["tracker_sync"]["event_types"]["public_consultation_metadata_review"] == 1


def test_registry_econsultare_records_bounded_failure(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {"family": "consultare_econsultare", "url": "https://e-consultare.gov.ro/consultare/404"},
    )

    def fail(url):
        raise ValueError("Pagina e-consultare nu este disponibilă.")

    monkeypatch.setattr(ec, "descarca", fail)
    failed = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert failed["state"] == "failed"
    assert failed["last_error"] == "fetch_failed"
    assert failed["tracker_sync"]["event_types"] == {"public_consultation_source_unavailable": 1}
