from types import SimpleNamespace

import pytest

from scripts import source_registry as registry


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def test_registry_discovers_lists_queues_and_records_one_source(tmp_path):
    stare = state(tmp_path)

    row = registry.executa(
        stare,
        {
            "action": "discover",
            "family": "ue_cellar",
            "identifier": "32014L0024",
            "url": "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024",
            "label": "Directiva achiziții",
        },
    )
    assert row["state"] == "discovered"
    assert row["id"].startswith("src_")
    again = registry.executa(
        stare,
        {"action": "discover", "family": "ue_cellar", "identifier": "32014L0024"},
    )
    assert again["url"] == row["url"]

    listed = registry.lista(stare)
    assert listed["total"] == 1
    assert listed["families"]["ue_cellar"].startswith("Drept UE")
    assert listed["sources"][0]["identifier"] == "32014L0024"

    queued = registry.executa(stare, {"action": "queue", "id": row["id"]})
    assert queued["state"] == "queued"

    fetched = registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "fetched",
            "http_status": 200,
            "content_hash": "a" * 64,
            "parser_version": "cellar-v1",
        },
    )
    assert fetched["state"] == "fetched"
    assert fetched["last_hash"] == "a" * 64
    assert fetched["parser_version"] == "cellar-v1"

    filtered = registry.lista(stare, {"family": ["ue_cellar"], "state": ["fetched"]})
    assert filtered["total"] == 1
    assert filtered["counts"]["ue_cellar:fetched"] == 1


def test_registry_rejects_invalid_sources_and_transitions(tmp_path):
    stare = state(tmp_path)
    with pytest.raises(ValueError, match="Familie"):
        registry.executa(stare, {"family": "other", "identifier": "x"})
    with pytest.raises(ValueError, match="URL"):
        registry.executa(stare, {"family": "ccr", "url": "file:///tmp/x"})

    row = registry.executa(stare, {"family": "ccr", "identifier": "decizie-1"})
    with pytest.raises(ValueError, match="Tranziție"):
        registry.executa(stare, {"action": "record", "id": row["id"], "state": "changed"})
    queued = registry.executa(stare, {"action": "queue", "id": row["id"]})
    assert queued["state"] == "queued"
    with pytest.raises(ValueError, match="Hash"):
        registry.executa(
            stare,
            {"action": "record", "id": row["id"], "state": "fetched", "content_hash": "nope"},
        )


def test_registry_missing_store_lists_empty_without_creating_file(tmp_path):
    stare = state(tmp_path)
    out = registry.lista(stare)
    assert out["total"] == 0
    assert out["sources"] == []
    assert not registry.cale(stare).exists()
