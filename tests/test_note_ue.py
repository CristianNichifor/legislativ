import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import achizitii_ue, dosare, note_manuale, note_ue
from tests.test_dosare import ID, create
from tests.test_dosare import request as http
from tests.test_instantanee_ue import write

CELEX = "32018R1805"


@pytest.fixture
def source_backed_case(tmp_path):
    state = SimpleNamespace(
        corpus=tmp_path / "corpus.db",
        eu=tmp_path / "eu.db",
        initiative=tmp_path / "initiative.db",
        date_dir=None,
    )
    create(state)
    with sqlite3.connect(state.corpus) as con:
        con.execute("CREATE TABLE acte(id TEXT, titlu TEXT, sursa_url TEXT, citit_la TEXT)")
        con.execute(
            "INSERT INTO acte VALUES "
            "('lege-98-2016','Legea achizițiilor','https://legislatie.just.ro/test','2026-01-01')"
        )
        con.execute(
            "CREATE TABLE provizii(act_id TEXT,locator TEXT,ord INTEGER,text TEXT,"
            "vigoare_de_la TEXT,vigoare_pana_la TEXT)"
        )
        con.execute(
            "INSERT INTO provizii VALUES "
            "('lege-98-2016','art1',1,'Text românesc păstrat local.',NULL,NULL)"
        )
    write(state, "Articolul 1\nObiectul\nObligație UE păstrată local.\nArticolul 2\nAlt text.")
    snapshot = achizitii_ue.detaliu(state, CELEX)["curenta"]["id"]
    selection = {
        "dosar_id": ID,
        "national": {"kind": "prevedere", "act_id": "lege-98-2016", "locator": "art1"},
        "eu": {"celex": CELEX, "instantanee": snapshot, "locator": "art1"},
        "issue_state": "possible_conflict",
    }
    return state, selection


def test_preview_is_source_backed_read_only_and_not_a_verdict(source_backed_case):
    state, selection = source_backed_case
    before = {p: p.read_bytes() for p in (dosare.cale(state), state.corpus, state.eu)}

    result = note_ue.preview(state, selection)

    assert result["state"] == "ready_for_human_review"
    assert result["base"]["legal_effect"] == "unknown"
    assert result["note_candidate"] is None
    assert result["base"]["national_evidence"]["quote"] == "Text românesc păstrat local."
    assert "Obligație UE" in result["base"]["eu_evidence"]["quote"]
    assert result["base"]["eu_evidence"]["language"] == "RON"
    assert all(p.read_bytes() == data for p, data in before.items())


def test_save_revalidates_base_and_stores_manual_risk_note(source_backed_case):
    state, selection = source_backed_case
    preview = note_ue.preview(state, selection)
    saved = note_ue.save(
        state,
        {
            **selection,
            "id": "b" * 32,
            "base_sha256": preview["base_sha256"],
            "title": "Risc UE de verificat",
            "uncertainty": "Aplicabilitatea exactă trebuie confirmată de jurist.",
            "rationale": "Textele par să trateze aceeași obligație.",
            "status": "ready_for_review",
        },
    )

    assert saved["type"] == "risc_ue"
    assert saved["act_id"] == "lege-98-2016"
    assert saved["locator"] == "art1"
    assert saved["status"] == "ready_for_review"
    reasoning = json.loads(note_manuale.citeste(dosare.cale(state), ID, "b" * 32)["reasoning"])
    assert reasoning["issue_state"] == "possible_conflict"
    assert reasoning["human_review_status"] == "ready_for_review"
    assert reasoning["national"]["text_sha256"]
    assert reasoning["eu"]["article_sha256"]
    assert reasoning["limitations"]
    context = saved["proposal_context"]
    assert context["contract"] == "ro-eu-proposal-context-v1"
    assert context["kind"] == "possible_eu_issue"
    assert context["legal_effect"] == "unknown"
    assert context["issue_state"] == "possible_conflict"
    assert context["national"]["act_id"] == "lege-98-2016"
    assert context["national"]["locator"] == "art1"
    assert context["eu"]["celex"] == CELEX
    assert context["eu"]["snapshot_id"] == selection["eu"]["instantanee"]
    assert "verdict de conformitate" in context["limitations"][0]
    assert reasoning["proposal_context"] == context


def test_missing_sources_block_and_hash_tampering_is_rejected(source_backed_case):
    state, selection = source_backed_case
    assert note_ue.preview(state, {**selection, "eu": {**selection["eu"], "locator": "art999"}})[
        "blockers"
    ] == [{"side": "eu", "code": "ambiguous_or_missing_locator"}]

    with pytest.raises(ValueError, match="schimbat"):
        note_ue.save(
            state,
            {
                **selection,
                "id": "c" * 32,
                "base_sha256": "0" * 64,
                "title": "Risc UE",
                "uncertainty": "Necunoscut.",
                "rationale": "Test.",
                "status": "ready_for_review",
            },
        )
    assert note_manuale.lista(dosare.cale(state), ID)["total"] == 0


def test_local_http_boundaries_and_static_rejection(source_backed_case):
    state, selection = source_backed_case
    url = "/api/dosare/note-ue/previzualizare"
    assert http(state, "POST", url, selection)[0] == 200
    assert http(state, "POST", url, selection, origin="https://evil.test")[0] == 403
    assert http(state, "POST", url, selection, host="evil:8123")[0] == 403
    assert http(state, "POST", url, selection, length=16001)[0] == 413
    state.date_dir = "static"
    assert http(state, "POST", url, selection)[0] == 400
