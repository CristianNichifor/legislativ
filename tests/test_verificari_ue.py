import copy
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import dosare, instantanee_ue, verificari_dovezi, verificari_ue
from tests.test_cellar import EU_TEXT
from tests.test_dosare import ID, create
from tests.test_instantanee_ue import capture, write


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(
        eu=tmp_path / "eu?#.db", initiative=tmp_path / "initiative.db", date_dir=None
    )


def evidence(state):
    return {"referinte_ue": [{"celex": "32018R1805"}], "surse_ue": capture(state)}


@pytest.mark.parametrize("change", ["none", "text", "language", "metadata", "missing", "hash"])
def test_separate_text_language_metadata_and_unknown(state, change):
    write(state)
    old = evidence(state)
    if change == "text":
        write(state, EU_TEXT + "\nAdditional wording.")
    elif change == "language":
        write(state, "Article 1\nAn English language version of the regulation.", "ENG")
    elif change == "missing":
        state.eu.unlink()
    elif change in ("metadata", "hash"):
        with sqlite3.connect(state.eu) as con:
            if change == "metadata":
                con.execute("UPDATE eu_acte SET citit_la='2030-01-01', item_url='https://changed'")
            else:
                con.execute("UPDATE eu_acte SET text_sha256='corrupt'")
    result = verificari_ue.verifica(state, old)
    item = result["surse"][0]
    assert item["stare"] == (
        "indisponibil"
        if change in ("missing", "hash")
        else "schimbat"
        if change in ("text", "language")
        else "neschimbat"
    )
    assert item["text_schimbat"] == (
        None if change in ("language", "missing", "hash") else change == "text"
    )
    assert result["comparatie_incompleta"] == (change in ("missing", "hash"))
    for version in (item["salvat"], item["curent"]):
        assert "text" not in (version or {}).get("sursa", {})
    if change == "metadata":
        assert item["metadate_schimbate"] is True
    if change == "language":
        assert item["limba_schimbata"] is True
    if change == "missing":
        assert not state.eu.exists()


@pytest.mark.parametrize(
    "change", ["legacy", "version", "algorithm", "id", "text", "truncated", "empty"]
)
def test_invalid_baseline_never_looks_verified(state, change):
    write(state)
    old = evidence(state)
    snapshot = old["surse_ue"]["instantanee"][0]
    if change == "legacy":
        old.pop("surse_ue")
    elif change == "version":
        old["surse_ue"]["schema_version"] = 999
    elif change == "algorithm":
        snapshot["algoritm"] = "unknown"
    elif change == "id":
        snapshot["id"] = "0" * 64
    elif change == "text":
        snapshot["sursa"]["text"] += " tampered"
    elif change == "truncated":
        old["surse_ue"]["trunchiat"] = True
    else:
        old["surse_ue"]["instantanee"] = []
    assert verificari_ue.verifica(state, old)["comparatie_incompleta"]


def test_later_import_does_not_backfill_unavailable_baseline(state, monkeypatch):
    old = evidence(state)
    write(state)
    result = verificari_ue.verifica(state, old)
    assert result["surse"][0]["stare"] == "indisponibil"
    assert result["surse"][0]["curent"]["stare"] == "capturat"
    valid = evidence(state)
    monkeypatch.setattr(instantanee_ue, "MAX_DOSSIER_BYTES", 1)
    assert verificari_ue.verifica(state, valid)["surse"][0]["stare"] == "indisponibil"


def test_check_history_retry_export_and_queue_counts_stay_independent(state, monkeypatch):
    write(state)
    create(state)
    report = {"gasit": True, "referinte_ue": [{"celex": "32018R1805"}], "markdown": "Report"}
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "Parlamentul"}})
    request = {"id": "c" * 32, "dosar_id": ID, "rulare_id": run["id"]}
    first = verificari_dovezi.salveaza(state, request)
    baseline = copy.deepcopy(first)
    write(state, EU_TEXT + "\nChanged text.")
    assert verificari_dovezi.salveaza(state, request) == first
    second = verificari_dovezi.salveaza(state, {**request, "id": "d" * 32})
    assert second["surse_ue"]["totaluri"]["schimbat"] == 1
    assert second["totaluri"]["schimbat"] == 0 and second["constatari"] == []
    assert first == baseline
    path = dosare.cale(state)
    history = verificari_dovezi.istoric(path, ID, run["id"], check_id=request["id"])
    assert history["selectata"] == first and history["total"] == 2
    assert verificari_dovezi.coada(path, status="schimbat")["total"] == 0
    assert dosare.rulari(path, ID, run["id"]) == run
    restored = path.with_name("restored.db")
    dosare.backup(path, restored)
    assert verificari_dovezi.istoric(restored, ID, run["id"])["selectata"] == second
