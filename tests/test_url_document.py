"""The public portal URL for an act: stored source, or one rebuilt from its portal id."""

from __future__ import annotations

from scripts.depozit import url_document


def test_prefers_the_stored_source_url():
    assert url_document("https://exemplu.ro/act", "999") == "https://exemplu.ro/act"


def test_rebuilds_from_the_portal_id_when_no_source():
    assert url_document("", "290673") == "https://legislatie.just.ro/Public/DetaliiDocument/290673"
    assert url_document(None, "290673").endswith("/290673")


def test_empty_when_neither_is_known():
    assert url_document("", "") == ""
    assert url_document(None, None) == ""
