from __future__ import annotations

import sqlite3

import pytest

from scripts import provision_identity


@pytest.fixture
def con():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE acte(id TEXT PRIMARY KEY, sursa_url TEXT, citit_la TEXT)")
    db.execute("CREATE TABLE provizii(act_id TEXT, locator TEXT, ord INTEGER, text TEXT)")
    db.execute(
        "INSERT INTO acte(id, sursa_url, citit_la) VALUES (?,?,?)",
        (
            "lege-98-2016",
            "https://legislatie.just.ro/Public/DetaliiDocument/178667",
            "2026-09-12T10:00:00+00:00",
        ),
    )
    db.execute(
        "INSERT INTO provizii(act_id, locator, ord, text) VALUES (?,?,?,?)",
        ("lege-98-2016", "art7.alin2.litb", 1, "b) textul prevederii;"),
    )
    db.execute(
        "INSERT INTO provizii(act_id, locator, ord, text) VALUES (?,?,?,?)",
        ("lege-98-2016", "anx1.art2", 2, "Articolul 2 din anexă."),
    )
    yield db
    db.close()


@pytest.mark.parametrize(
    ("raw", "canonical", "kind", "parts"),
    [
        (
            "art. 7 alin. (2) lit. b)",
            "art7.alin2.litb",
            "litera",
            {"articol": "7", "alineat": "2", "litera": "b"},
        ),
        ("Articolul II", "artII", "articol", {"articol": "II"}),
        ("Anexa nr. 1 art. 2", "anx1.art2", "articol", {"anexa": "1", "articol": "2"}),
        ("text", "text", "document", {"document": "text"}),
    ],
)
def test_locator_inputs_normalize_to_stable_canonical_ids(raw, canonical, kind, parts):
    loc = provision_identity.normalize_locator(raw)

    assert loc.canonical == canonical
    assert loc.kind == kind
    assert loc.parts == parts


@pytest.mark.parametrize("raw", ["alin. (2)", "lit. b)", "pct. 3", "capitolul II", ""])
def test_ambiguous_or_unsupported_locator_is_rejected(raw):
    with pytest.raises(ValueError):
        provision_identity.normalize_locator(raw)


def test_provision_key_is_stable_and_human_readable():
    assert (
        provision_identity.provision_key(" lege-98-2016 ", "articolul 7 alineatul (2) lit. b)")
        == "ro:lege-98-2016#art7.alin2.litb"
    )


def test_resolve_preserves_source_snapshot_and_text_hash(con):
    out = provision_identity.resolve(con, "lege-98-2016", "art. 7 alin. (2) lit. b)").to_dict()

    assert out["contract"] == "provision-identity-v1"
    assert out["status"] == "available"
    assert out["provision_id"] == "ro:lege-98-2016#art7.alin2.litb"
    assert out["source_url"].startswith("https://legislatie.just.ro/")
    assert out["captured_at"] == "2026-09-12T10:00:00+00:00"
    assert len(out["source_hash"]) == 64
    assert out["source_version"] == out["captured_at"]
    assert out["rows"] == 1
    assert out["exact"] is True


def test_missing_provision_keeps_canonical_identity_without_guessing(con):
    out = provision_identity.resolve(con, "lege-98-2016", "art. 9").to_dict()

    assert out["status"] == "unavailable"
    assert out["provision_id"] == "ro:lege-98-2016#art9"
    assert out["source_hash"] == ""
    assert out["exact"] is False
    assert out["unavailable_reason"] == "provision-not-found"


def test_missing_act_is_distinct_from_missing_provision(con):
    out = provision_identity.resolve(con, "lege-1-1900", "art. 1").to_dict()

    assert out["status"] == "unavailable"
    assert out["unavailable_reason"] == "act-not-found"
