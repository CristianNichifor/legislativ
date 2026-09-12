from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from scripts import dosare, law_rule_drafts, rule_candidate_queue
from scripts.server import face_handler

DOSAR_ID = "b" * 32
QUEUE_ID = "1" * 32
DRAFT_ID = "c" * 32


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def create_dossier(state):
    return dosare.creeaza(dosare.cale(state), {"id": DOSAR_ID, "titlu": "Reguli achiziții"})


def candidate(**patch):
    data = {
        "provision_id": "ro:lege-98-2016#art7.alin2",
        "act_id": "lege-98-2016",
        "locator": "art7.alin2",
        "source_hash": "a" * 64,
        "text": "Autoritatea contractantă publică anunțul în SEAP.",
        "modality": "obligation",
        "review_state": "machine_detected",
        "actor": "autoritatea contractantă",
        "condition": "procedura este inițiată",
        "action": "publică anunțul în SEAP",
        "deadline": "",
        "exceptions": [],
        "effect": "",
        "reviewer": "",
    }
    data.update(patch)
    return data


def request(state, method, url, body=None, host="localhost:8123", origin=None, length=None):
    handler = object.__new__(face_handler(state))
    handler.path = url
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {"Host": host, "Content-Length": str(len(raw) if length is None else length)}
    if origin:
        handler.headers["Origin"] = origin
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def save_candidate(path, payload=None):
    return rule_candidate_queue.salveaza(
        path,
        {"id": QUEUE_ID, "dosar_id": DOSAR_ID, "candidate": payload or candidate()},
    )


def promote_request(**patch):
    data = {
        "id": DRAFT_ID,
        "dosar_id": DOSAR_ID,
        "queue_id": QUEUE_ID,
        "accepted_by": "Cristian",
        "acceptance_note": "Structura exprimă obligația din textul citat.",
    }
    data.update(patch)
    return data


def test_reviewable_candidate_promotes_to_immutable_draft_rule(state):
    create_dossier(state)
    path = dosare.cale(state)
    saved = save_candidate(path)

    draft = law_rule_drafts.promoveaza(path, promote_request())
    listed = law_rule_drafts.lista(path, DOSAR_ID)

    assert draft["contract"] == "law-rule-draft-v1"
    assert draft["status"] == "draft_rule_not_legal_verdict"
    assert draft["queue_id"] == QUEUE_ID
    assert draft["candidate_id"] == saved["candidate_id"]
    assert draft["provision_id"] == "ro:lege-98-2016#art7.alin2"
    assert draft["actor"] == "autoritatea contractantă"
    assert draft["action"] == "publică anunțul în SEAP"
    assert draft["source_candidate"]["contract"] == "rule-candidate-v1"
    assert "nu este regulă executabilă validată juridic" in draft["limitari"][0]
    assert listed["total"] == 1
    assert listed["items"][0]["draft_id"] == DRAFT_ID

    with pytest.raises(ValueError):
        law_rule_drafts.promoveaza(path, promote_request(id="d" * 32))

    with dosare._open(path, write=True) as con, pytest.raises(Exception, match="append-only"):
        con.execute("DELETE FROM law_rule_drafts WHERE id=?", (DRAFT_ID,))


def test_rule_draft_promotion_rejects_unstructured_candidates_and_filters(state):
    create_dossier(state)
    path = dosare.cale(state)
    save_candidate(path, candidate(actor="", action=""))

    with pytest.raises(ValueError, match="fără structură"):
        law_rule_drafts.promoveaza(path, promote_request())

    path2 = state.initiative.with_name("second.db")
    dosare.creeaza(path2, {"id": DOSAR_ID, "titlu": "Reguli achiziții"})
    save_candidate(path2)
    law_rule_drafts.promoveaza(path2, promote_request())

    assert law_rule_drafts.lista(path2, DOSAR_ID, act_id="lege-98-2016")["total"] == 1
    assert law_rule_drafts.lista(path2, DOSAR_ID, act_id="alta-lege")["total"] == 0
    assert (
        law_rule_drafts.lista(path2, DOSAR_ID, provision_id="ro:lege-98-2016#art7.alin2")["total"]
        == 1
    )


def test_rule_draft_http_is_local_only(state):
    create_dossier(state)
    path = dosare.cale(state)
    save_candidate(path)
    body = {"action": "promote", **promote_request()}

    assert (
        request(state, "POST", "/api/dosare/rule-drafts", body, origin="https://evil.test")[0]
        == 403
    )

    code, draft = request(state, "POST", "/api/dosare/rule-drafts", body)
    assert code == 200
    assert draft["contract"] == "law-rule-draft-v1"

    code, listed = request(state, "GET", "/api/dosare/rule-drafts?id=" + DOSAR_ID)
    assert code == 200
    assert listed["total"] == 1
    assert listed["items"][0]["candidate_id"] == draft["candidate_id"]
