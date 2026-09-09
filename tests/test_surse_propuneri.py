import copy
import sqlite3

import pytest

from scripts import analize_propuneri, dosare, interventii_propuneri, propuneri, surse_propuneri
from tests import test_analize_propuneri as support
from tests.test_dosare import request as http

case = support.case
structured = support.structured


def compare(state, req, revision=1, analysis_id=None):
    return surse_propuneri.verifica(
        state, req["dosar_id"], req["rulare_id"], req["constatare_id"], revision, analysis_id
    )


def initial(state, path, req):
    proposal = support.save_text(path, req)
    analysis = analize_propuneri.salveaza(state, support.request(req))
    return proposal, analysis


def test_readonly_comparison_separates_metadata_text_dates_and_history(structured):
    state, path, _, req, _ = structured
    proposal, analysis = initial(state, path, req)
    before = path.read_bytes()
    first = compare(state, req)
    assert first["stare"] == "neschimbat" and not first["salvata"]
    assert first["analiza_baza_id"] == analysis["id"]
    assert first["propunere_sha256"] == surse_propuneri.sha(proposal)
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE acte SET citit_la='2026-09-10'")
    meta = compare(state, req)
    assert meta["stare"] == "neschimbat" and meta["dependente"][0]["metadate_schimbate"]
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Updated <script> local text'")
    changed = compare(state, req)
    assert changed["stare"] == "schimbat" and not changed["comparatie_incompleta"]
    dep = changed["dependente"][0]
    assert dep["inainte"].endswith("Original local text")
    assert dep["dupa"].endswith("Updated <script> local text") and dep["diferente"]
    assert dep["sha256_curent"] != dep["sha256_retinut"]
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Original local text',vigoare_pana_la='2026-09-10'")
    dates = compare(state, req)
    assert dates["stare"] == "schimbat" and not dates["dependente"][0]["diferente"]
    assert path.read_bytes() == before
    assert support.history(path, req)["selectata"] == analysis


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM acte",
        "DELETE FROM provizii",
        "DROP TABLE provizii",
        "UPDATE provizii SET text=''",
        "INSERT INTO provizii SELECT * FROM provizii",
    ],
)
def test_unavailable_or_ambiguous_is_never_unchanged(structured, sql):
    state, path, _, req, _ = structured
    initial(state, path, req)
    with sqlite3.connect(state.corpus) as con:
        con.execute(sql)
    data = compare(state, req)
    assert data["stare"] == "indisponibil" and data["comparatie_incompleta"]


def test_partial_baseline_and_unknown_contract_not_comparable(structured, monkeypatch):
    state, path, _, req, _ = structured
    proposal = support.save_text(path, req)
    with monkeypatch.context() as m:
        m.setattr(analize_propuneri, "MAX_SOURCE_BYTES", 0)
        baseline = analize_propuneri.salveaza(state, support.request(req))
    assert compare(state, req)["stare"] == "indisponibil"
    for patch in ({"engine_version": "future"}, {"schema_version": 9}, {"surse_sha256": "invalid"}):
        data = surse_propuneri.compara(state, proposal, baseline | patch)
        assert data["stare"] == "nesuportat" and data["comparatie_incompleta"]
    malformed = copy.deepcopy(baseline)
    malformed["surse"][0]["sha256"] = "bad"
    malformed["surse_sha256"] = surse_propuneri.sha(malformed["surse"])
    assert surse_propuneri.compara(state, proposal, malformed)["stare"] == "nesuportat"


def test_explicit_reassessment_persists_basis_diff_and_retry_snapshot(structured, monkeypatch):
    state, path, _, req, _ = structured
    _, baseline = initial(state, path, req)
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed source'")
    request = support.request(req, ident="e" * 32) | {"analiza_baza_id": baseline["id"]}
    reassessed = analize_propuneri.salveaza(state, request)
    result = reassessed["reevaluare"]
    assert result["salvata"] and result["stare"] == "schimbat"
    assert result["analiza_baza_id"] == baseline["id"]
    assert support.history(path, req, analysis_id=baseline["id"])["selectata"] == baseline
    assert support.history(path, req)["selectata"] == reassessed
    assert compare(state, req)["stare"] == "neschimbat"
    state.corpus.unlink()
    with monkeypatch.context() as m:
        m.setattr(analize_propuneri, "executa", lambda *a: pytest.fail("Retry ran engine"))
        m.setattr(analize_propuneri, "compara", lambda *a, **kw: pytest.fail("Retry compared"))
        assert analize_propuneri.salveaza(state, request) == reassessed
    with pytest.raises(ValueError, match="alta baza"):
        analize_propuneri.salveaza(state, support.request(req, ident="e" * 32))
    backup = path.with_name("backup.db")
    dosare.backup(path, backup)
    exported = propuneri.exporta(
        backup, req["dosar_id"], req["rulare_id"], req["constatare_id"], 1, reassessed["id"]
    )
    assert exported["analiza"]["reevaluare"] == result
    assert "Changed source" in exported["markdown"]
    assert "Original local text" in exported["markdown"]


def test_new_revision_never_borrows_previous_source_baseline(structured):
    state, path, _, req, _ = structured
    proposal, baseline = initial(state, path, req)
    support.save_text(path, req | {"id": "c" * 32, "revizie": 1}, proposal["text"])
    assert compare(state, req, revision=2)["stare"] == "nesuportat"
    with pytest.raises(ValueError):
        compare(state, req, revision=2, analysis_id=baseline["id"])
    with pytest.raises(ValueError):
        analize_propuneri.salveaza(
            state, support.request(req, 2, "e" * 32) | {"analiza_baza_id": baseline["id"]}
        )


def test_structured_target_available_without_analysis_and_changed_mixed_sources(structured):
    state, path, _, req, intent = structured
    preview = interventii_propuneri.pregateste(state, intent)
    propuneri.salveaza(
        path, req | {"text": preview["text_compus"], "interventie": preview["cerere"]}, state
    )
    assert compare(state, req)["stare"] == "neschimbat"
    assert compare(state, req)["dependente"][0]["tip"] == "tinta_structurata"
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='New target'")
    assert compare(state, req)["stare"] == "schimbat"
    # Whole-act capture can be partial while the exact structured target is comparable.
    with sqlite3.connect(state.corpus) as con:
        con.execute("INSERT INTO provizii VALUES ('lege-98-2016','art2',2,'',NULL,NULL)")
    analize_propuneri.salveaza(state, support.request(req))
    result = compare(state, req)
    assert result["stare"] == "schimbat" and result["comparatie_incompleta"]
    assert result["totaluri"] == {"schimbat": 1, "neschimbat": 0, "indisponibil": 1}


def test_bounded_excerpt_and_exceeded_act_coverage_are_explicit(structured):
    state, path, _, req, _ = structured
    proposal, baseline = initial(state, path, req)
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text=?", ("Changed line\n" * 2000,))
    result = compare(state, req)
    dep = result["dependente"][0]
    assert dep["text_trunchiat"] and dep["diferente_trunchiate"]
    assert len(dep["dupa"]) <= surse_propuneri.MAX_TEXT
    assert len(dep["diferente"]) <= surse_propuneri.MAX_DIFF_LINES
    baseline["acoperire"]["acte_recunoscute"] = 21
    result = surse_propuneri.compara(state, proposal, baseline)
    assert result["comparatie_incompleta"]


def test_http_boundaries_and_wrong_baseline_ownership(structured):
    state, path, _, req, _ = structured
    _, baseline = initial(state, path, req)
    url = "/api/dosare/propuneri/surse"
    query = (
        f"?id={req['dosar_id']}&rulare_id={req['rulare_id']}"
        f"&constatare_id={req['constatare_id']}&revizie=1&analiza_id={baseline['id']}"
    )
    assert http(state, "GET", url + query)[0] == 200
    assert http(state, "GET", url + query, origin="https://evil.test")[0] == 403
    assert http(state, "GET", url + query, host="evil:8123")[0] == 403
    assert http(state, "GET", url + query.replace("revizie=1", "revizie=bad"))[0] == 400
    assert http(state, "GET", url + query.replace(baseline["id"], "f" * 32))[0] == 400
    dosare.creeaza(path, {"id": "f" * 32, "titlu": "Other dossier"})
    assert http(state, "GET", url + query.replace(req["dosar_id"], "f" * 32))[0] == 400
    state.date_dir = "static"
    assert http(state, "GET", url + query)[0] == 400
