from __future__ import annotations

import io
import json
from types import SimpleNamespace

from scripts import dosare, law_rule_drafts, law_rule_execution, rule_candidate_queue
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
