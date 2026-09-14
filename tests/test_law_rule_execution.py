from __future__ import annotations

import io
import json
from datetime import date
from types import SimpleNamespace

from scripts import depozit, dosare, law_rule_drafts, law_rule_execution, rule_candidate_queue
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.graf import _deschide_graf, construieste
from scripts.server import face_handler

DOSAR_ID = "b" * 32
QUEUE_ID = "1" * 32
DRAFT_ID = "c" * 32


def create_dossier(path):
    return dosare.creeaza(path, {"id": DOSAR_ID, "titlu": "Reguli achiziții"})


def candidate(**patch):
    data = {
        "provision_id": "ro:lege-98-2016#art3",
        "act_id": "lege-98-2016",
        "locator": "art3",
        "source_hash": "a" * 64,
        "text": "Guvernul aprobă normele metodologice.",
        "modality": "obligation",
        "review_state": "human_reviewed",
        "actor": "Guvernul",
        "condition": "legea intră în vigoare",
        "action": "aprobă normele metodologice",
        "deadline": "30 zile",
        "exceptions": [],
        "effect": "",
        "reviewer": "Cristian",
    }
    data.update(patch)
    return data


def save_draft(path, payload=None):
    rule_candidate_queue.salveaza(
        path, {"id": QUEUE_ID, "dosar_id": DOSAR_ID, "candidate": payload or candidate()}
    )
    return law_rule_drafts.promoveaza(
        path,
        {
            "id": DRAFT_ID,
            "dosar_id": DOSAR_ID,
            "queue_id": QUEUE_ID,
            "accepted_by": "Cristian",
            "acceptance_note": "Obligația este explicită în text.",
        },
    )


def state_with_vid(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)
    state.vid = [
        {
            "act_id": "lege-98-2016",
            "locator": "art3",
            "text": "Guvernul aprobă normele metodologice.",
            "instrument": "hg",
            "scadenta": "2016-06-25",
            "zile_intarziere": 100,
            "severitate": "blocking",
            "cautat": "act de tip «hg» care trimite la lege-98-2016",
            "candidati": ["ordin-1-2017"],
            "limitari": ["Corpusul nu se declară complet pentru actele de tip «hg»."],
        }
    ]
    state.are_graf = lambda: False
    return state


def graph_with_repeal(tmp_path):
    corpus = tmp_path / "corpus.db"
    with depozit.deschide(corpus) as con:
        rec = Inregistrare(
            titlu="LEGE nr. 200",
            tip_act="LEGE",
            numar="200",
            an=None,
            data_vigoare=date(2020, 1, 1),
            emitent="X",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/2000",
            text="Articolul 15 din Legea nr. 98/2016 se abrogă.",
        )
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf = tmp_path / "graf.db"
    construieste(str(corpus), str(graf))
    con = _deschide_graf(str(graf), readonly=True)
    con.close()
    return graf


def state_with_graph(tmp_path):
    state = state_with_vid(tmp_path)
    state.graf = str(graph_with_repeal(tmp_path))
    state.are_graf = lambda: True
    state.republicari = lambda _acte: {}
    return state


def request(state, method, url, body=None):
    handler = object.__new__(face_handler(state))
    handler.path = url
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {"Host": "localhost:8123", "Content-Length": str(len(raw))}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_rule_draft_execution_matches_delegated_norm_gap(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    draft = save_draft(path)

    result = law_rule_execution.delegated_norms(state, path, DOSAR_ID, act_id="lege-98-2016")

    assert result["contract"] == "law-rule-execution-v1"
    assert result["status"] == "deterministic_rule_draft_check_preview"
    assert result["eligible_rule_drafts"] == 1
    assert result["candidate_issues"] == 1
    row = result["rows"][0]
    assert row["contract"] == "law-rule-execution-row-v1"
    assert row["rule_draft_id"] == draft["draft_id"]
    assert row["status"] == "candidate_issue_not_verdict"
    assert row["provision_id"] == "ro:lege-98-2016#art3"
    assert row["matched_checks"][0]["status"] == "candidate_gap_not_verdict"
    assert row["matched_checks"][0]["evidence"]["near_candidates"] == ["ordin-1-2017"]
    assert any("nu este verdict juridic" in item for item in row["limitations"])


def test_rule_draft_execution_keeps_no_signal_distinct_from_compliance(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(path, candidate(locator="art4", provision_id="ro:lege-98-2016#art4"))

    result = law_rule_execution.delegated_norms(state, path, DOSAR_ID)

    assert result["candidate_issues"] == 0
    assert result["rows"][0]["status"] == "no_local_candidate_signal"
    assert "Nu execută reguli ca adevăr juridic" in result["limitations"][1]


def test_rule_draft_execution_http_endpoint(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(path)

    code, result = request(
        state, "GET", f"/api/dosare/rule-drafts/checks?id={DOSAR_ID}&act=lege-98-2016"
    )

    assert code == 200
    assert result["contract"] == "law-rule-execution-v1"
    assert result["rows"][0]["rule_draft_id"] == DRAFT_ID


def test_rule_draft_text_execution_matches_supplied_project_text(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(path)

    result = law_rule_execution.draft_text(
        path,
        {
            "id": DOSAR_ID,
            "act": "lege-98-2016",
            "text": "Art. 3. Guvernul aprobă normele metodologice în termen de 30 zile.",
        },
    )

    assert result["contract"] == "law-rule-draft-text-execution-v1"
    assert result["status"] == "deterministic_draft_text_rule_check"
    assert result["possible_matches"] == 1
    row = result["rows"][0]
    assert row["contract"] == "law-rule-draft-text-execution-v1-row"
    assert row["status"] == "possible_match_not_verdict"
    assert row["checks"]["actor_found"] is True
    assert row["checks"]["action_found"] is True
    assert row["checks"]["deadline_found"] is True
    assert "nu verdict juridic" in row["limitations"][0]


def test_rule_draft_text_flags_obligation_without_actor(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(path)

    result = law_rule_execution.draft_text(
        path,
        {
            "id": DOSAR_ID,
            "text": "Art. 3. Se aprobă normele metodologice în termen de 30 zile.",
        },
        state,
    )

    row = result["rows"][0]
    assert row["status"] == "candidate_issue_not_verdict"
    assert row["issue_candidates"][0]["code"] == "obligation_actor_missing"
    assert row["issue_candidates"][0]["status"] == "candidate_issue_not_legal_verdict"
    assert row["issue_candidates"][0]["source"]["source_hash"] == "a" * 64
    assert "nu verdict juridic" in row["issue_candidates"][0]["limitations"][0]


def test_rule_draft_text_flags_procedure_missing_deadline_and_body(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(
        path,
        candidate(
            modality="procedure",
            text="Autoritatea publică stabilește procedura în 10 zile dacă primește cererea.",
            actor="Autoritatea publică",
            action="stabilește procedura",
            deadline="10 zile",
            condition="dacă primește cererea",
        ),
    )

    result = law_rule_execution.draft_text(
        path,
        {"id": DOSAR_ID, "text": "Autoritatea publică stabilește procedura."},
        state,
    )

    codes = {issue["code"] for issue in result["rows"][0]["issue_candidates"]}
    assert {"procedure_deadline_missing", "procedure_body_missing"} <= codes
    assert result["candidate_issues"] >= 2


def test_rule_draft_text_flags_missing_or_ambiguous_reference_act(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)

    result = law_rule_execution.draft_text(
        path,
        {"id": DOSAR_ID, "text": "Se aplică art. 5 în termen de 30 de zile."},
        state,
    )

    assert result["candidate_issues"] == 1
    issue = result["issue_candidates"][0]
    assert issue["code"] == "reference_missing_or_ambiguous_act"
    assert issue["source"]["quote"] == "art. 5"


def test_rule_draft_text_flags_repealed_reference_when_graph_available(tmp_path):
    state = state_with_graph(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)

    result = law_rule_execution.draft_text(
        path,
        {"id": DOSAR_ID, "text": "Se aplică articolul 15 din Legea nr. 98/2016."},
        state,
    )

    issue = result["issue_candidates"][0]
    assert issue["code"] == "amends_repealed_provision"
    assert issue["evidence"]["act_id"] == "lege-98-2016"
    assert issue["evidence"]["locator"] == "art15"
    assert result["checks"]["graph_repeal_or_change"] is True


def test_rule_draft_text_surfaces_saved_eu_conflict_hypothesis(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    result_json = {
        "state": "linked_hypothesis",
        "baza": {"selection": {"celex": "32014L0024", "locator": "art1"}},
        "substantive_candidate": {
            "ipoteza": "potential_conflict",
            "obligatie": "achiziții publice transparente",
            "motiv": "ipoteză salvată",
        },
    }
    with dosare._open(path, write=True) as con:
        con.execute(
            "INSERT INTO rulari VALUES (?,?,?,?,?,?,?,?)",
            (
                "2" * 32,
                DOSAR_ID,
                "2026-09-14T00:00:00+00:00",
                "test",
                "d" * 64,
                "{}",
                "{}",
                "{}",
            ),
        )
        con.execute(
            "INSERT INTO propuneri VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "3" * 32,
                "2" * 32,
                "4" * 32,
                1,
                "d" * 64,
                "Propunere",
                "Text",
                "Motiv",
                "2026-09-14T00:00:00+00:00",
            ),
        )
        con.execute(
            "INSERT INTO legaturi_ue(id,propunere_id,creat_la,cerere_json,rezultat_json) "
            "VALUES (?,?,?,?,?)",
            (
                "5" * 32,
                "3" * 32,
                "2026-09-14T00:00:00+00:00",
                "{}",
                json.dumps(result_json),
            ),
        )

    result = law_rule_execution.draft_text(
        path,
        {"id": DOSAR_ID, "text": "Proiect privind achiziții publice transparente."},
        state,
    )

    assert result["checks"]["saved_eu_links"] is True
    assert result["issue_candidates"][0]["code"] == "selected_eu_article_potential_conflict"
    assert result["issue_candidates"][0]["source"]["celex"] == "32014L0024"


def test_rule_draft_text_execution_keeps_partial_match_distinct(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(path)

    result = law_rule_execution.draft_text(path, {"id": DOSAR_ID, "text": "Guvernul decide."})

    assert result["possible_matches"] == 0
    assert result["partial_matches"] == 1
    assert result["rows"][0]["status"] == "partial_match_needs_review"
    assert result["rows"][0]["missing_fields"] == [
        "action_found",
        "deadline_found",
        "condition_found",
    ]


def test_rule_draft_text_execution_http_endpoint(tmp_path):
    state = state_with_vid(tmp_path)
    path = dosare.cale(state)
    create_dossier(path)
    save_draft(path)

    code, result = request(
        state,
        "POST",
        "/api/dosare/rule-drafts/execute-draft",
        {"id": DOSAR_ID, "text": "Guvernul aprobă normele metodologice."},
    )

    assert code == 200
    assert result["contract"] == "law-rule-draft-text-execution-v1"
    assert result["rows"][0]["rule_draft_id"] == DRAFT_ID
