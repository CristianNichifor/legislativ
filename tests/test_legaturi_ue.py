import copy
import sqlite3

import pytest

from scripts import achizitii_ue, interventii_propuneri, propuneri
from scripts import legaturi_ue as links
from tests import test_interventii_propuneri, test_propuneri
from tests.test_dosare import request as http
from tests.test_instantanee_ue import write

case = test_propuneri.case
structured = test_interventii_propuneri.structured
CELEX = "32018R1805"


@pytest.fixture
def linked_case(structured):
    state, path, run, req, intent = structured
    state.eu = path.with_name("eu.db")
    write(
        state,
        "Articolul 1\nObligatii\nObligatie explicita de test.\nArticolul 2\nExceptii de test.",
    )
    snapshot = achizitii_ue.detaliu(state, CELEX)["curenta"]["id"]
    preview = interventii_propuneri.pregateste(state, intent)
    proposal = propuneri.salveaza(
        path, {**req, "text": preview["text_compus"], "interventie": preview["cerere"]}, state
    )
    selection = {k: req[k] for k in ("dosar_id", "rulare_id", "constatare_id")}
    selection.update(revizie=proposal["revizie"], celex=CELEX, instantanee=snapshot, locator="art1")
    return state, path, selection


def test_exact_retained_article_and_revision_without_writes(linked_case):
    state, path, selection = linked_case
    before = {p: p.read_bytes() for p in (path, state.eu, state.corpus)}
    result = links.preview(state, selection)
    assert result["state"] == "ready_for_explicit_link"
    assert result["scope"] == "contextual" and result["substantive_candidate"] is None
    assert "Obligatie" in result["baza"]["eu_article"]["text"]
    assert result["baza"]["eu_snapshot"]["id"] == selection["instantanee"]
    assert result["baza"]["context_applicability"] == "unknown"
    assert result["baza"]["proposal"]["interventie"]["tinta"]["text"] == "Original local text"
    assert all(p.read_bytes() == data for p, data in before.items())
    write(state, "Article 1\nNew unrelated English text.", "ENG")
    assert links.preview(state, selection) == result
    options = links.obligatii(state, CELEX, selection["instantanee"])
    assert [a["locator"] for a in options["articole"]] == ["art1", "art2"]
    assert options["sursa"]["limba"] == "RON"


@pytest.mark.parametrize(
    "patch",
    [
        {"revizie": True},
        {"revizie": 2},
        {"dosar_id": "f" * 32},
        {"instantanee": False},
        {"celex": "https://example.com"},
        {"extra": "text"},
        {"text": "Forged evidence"},
    ],
)
def test_selector_validation_and_ownership(linked_case, patch):
    state, _, selection = linked_case
    with pytest.raises(ValueError):
        links.preview(state, {**selection, **patch})


@pytest.mark.parametrize("locator", ["art999", "preambul", "document", "art1-2", ""])
def test_missing_or_unsupported_locator_blocks(linked_case, locator):
    state, _, selection = linked_case
    result = links.preview(state, {**selection, "locator": locator})
    assert result["state"] == "blocked_evidence" and result["substantive_candidate"] is None


def test_duplicate_article_not_disambiguated_by_parser_suffix(linked_case):
    state, _, selection = linked_case
    write(state, "Articolul 1\nOne.\nArticolul 1\nTwo.")
    snapshot = achizitii_ue.detaliu(state, CELEX)["curenta"]["id"]
    options = links.obligatii(state, CELEX, snapshot)
    assert not any(a["selectabil"] for a in options["articole"])
    assert links.preview(state, {**selection, "instantanee": snapshot})["blockers"]


def test_missing_text_and_free_text_proposal_remain_contextual(linked_case):
    state, path, selection = linked_case
    propuneri.salveaza(
        path,
        {
            "id": "c" * 32,
            **{k: selection[k] for k in ("dosar_id", "rulare_id", "constatare_id")},
            "revizie": 1,
            "titlu": "Free text",
            "text": "",
            "motiv": "",
        },
    )
    result = links.preview(
        state, {**selection, "revizie": 2, "celex": "32014L0024", "instantanee": ""}
    )
    assert result["state"] == "blocked_missing_text"
    assert {b["side"] for b in result["blockers"]} == {"national", "eu"}
    proposal = copy.deepcopy(links.preview(state, selection)["baza"]["proposal"])
    del proposal["interventie"]
    assert links._national(proposal)[0]["code"] == "unresolved_national_target"


def test_hash_tampering_and_bounds(linked_case, monkeypatch):
    state, _, selection = linked_case
    proposal = links.preview(state, selection)["baza"]["proposal"]
    proposal["interventie"]["tinta"]["text"] = "Forged"
    assert links._national(proposal)[0]["code"] == "unverified_hash"
    monkeypatch.setattr(links, "MAX_TEXT_BYTES", 10)
    assert links.preview(state, selection)["blockers"][0]["code"] == "capture_limit"
    monkeypatch.undo()
    # Corrupt both the current row and archived observation; neither is a valid fallback.
    with sqlite3.connect(state.eu) as con:
        con.execute("UPDATE eu_acte SET text_sha256='invalid'")
        con.execute("DROP TRIGGER eu_instantanee_no_update")
        con.execute(
            "UPDATE eu_instantanee "
            "SET snapshot_json=json_set(snapshot_json,'$.sursa.text','Forged')"
        )
    assert (
        links.preview(state, selection)["blockers"][0]["code"]
        == "snapshot_unavailable_or_invalid_hash"
    )


def test_local_http_security_and_read_only_preview(linked_case):
    state, path, selection = linked_case
    url = "/api/dosare/propuneri/legaturi-ue/previzualizare"
    before = path.read_bytes()
    assert http(state, "POST", url, selection)[0] == 200
    assert http(state, "POST", url, selection, origin="https://evil.test")[0] == 403
    assert http(state, "POST", url, selection, host="evil:8123")[0] == 403
    assert http(state, "POST", url, selection, length=16001)[0] == 413
    assert path.read_bytes() == before
    state.date_dir = "static"
    assert http(state, "POST", url, selection)[0] == 400


@pytest.mark.parametrize(
    "text", ["Articolul 1", "Articolul 1\nDefinitii\nArticolul 2\nAlta sectiune"]
)
def test_header_or_title_only_article_blocks_missing_body(linked_case, text):
    state, _, selected = linked_case
    write(state, text)
    snapshot = achizitii_ue.detaliu(state, CELEX)["curenta"]["id"]
    result = links.preview(state, {**selected, "instantanee": snapshot})
    assert result["state"] == "blocked_missing_text"
    assert result["substantive_candidate"] is None
