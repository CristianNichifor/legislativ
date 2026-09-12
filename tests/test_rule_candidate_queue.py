from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from scripts import dosare, rule_candidate_queue
from scripts.server import face_handler

DOSAR_ID = "b" * 32


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


def test_rule_candidate_queue_groups_validated_candidates(state):
    create_dossier(state)
    path = dosare.cale(state)

    saved = [
        rule_candidate_queue.salveaza(
            path, {"id": f"{i:032x}", "dosar_id": DOSAR_ID, "candidate": payload}
        )
        for i, payload in enumerate(
            [
                candidate(actor="", action=""),
                candidate(modality="vague_standard", text="Termen rezonabil."),
                candidate(modality="not_codeable", text="Statul sprijină dezvoltarea."),
                candidate(text="Autoritatea publică anunțul.", action="anunță public"),
                candidate(review_state="human_reviewed", text="Autoritatea transmite notificarea."),
            ],
            start=1,
        )
    ]

    queue = rule_candidate_queue.lista(path, DOSAR_ID)

    assert {item["bucket"] for item in saved} == {
        "needs_more_structure",
        "needs_legal_review",
        "not_codeable",
        "reviewable",
        "human_reviewed",
    }
    assert queue["contract"] == "rule-candidate-review-queue-v1"
    assert queue["counts"]["needs_more_structure"] == 1
    assert queue["counts"]["needs_legal_review"] == 1
    assert queue["counts"]["not_codeable"] == 1
    assert queue["counts"]["reviewable"] == 1
    assert queue["counts"]["human_reviewed"] == 1
    assert queue["groups"]["needs_more_structure"][0]["actiuni"]["complete_structure"] is True
    assert queue["groups"]["needs_legal_review"][0]["actiuni"]["legal_review"] is True
    assert queue["groups"]["not_codeable"][0]["actiuni"]["keep_as_non_codeable"] is True
    assert queue["groups"]["reviewable"][0]["actiuni"]["promote_to_rule"] is True
    assert any("nu este verdict juridic" in item for item in queue["limitari"])


def test_rule_candidate_queue_filters_and_rejects_invalid_records(state):
    create_dossier(state)
    path = dosare.cale(state)
    saved = rule_candidate_queue.salveaza(
        path,
        {"id": "1" * 32, "dosar_id": DOSAR_ID, "candidate": candidate(actor="", action="")},
    )

    filtered = rule_candidate_queue.lista(path, DOSAR_ID, bucket="needs_more_structure")
    assert filtered["total"] == 1
    assert filtered["items"][0]["candidate_id"] == saved["candidate_id"]
    assert rule_candidate_queue.lista(path, DOSAR_ID, bucket="reviewable")["total"] == 0

    with pytest.raises(ValueError):
        rule_candidate_queue.lista(path, DOSAR_ID, bucket="accepted")
    with pytest.raises(ValueError):
        rule_candidate_queue.salveaza(
            path,
            {
                "id": "2" * 32,
                "dosar_id": DOSAR_ID,
                "candidate": candidate(source_hash="bad"),
            },
        )
    with pytest.raises(ValueError):
        rule_candidate_queue.salveaza(
            path,
            {"id": "3" * 32, "dosar_id": DOSAR_ID, "candidate": candidate(actor="", action="")},
        )


def test_rule_candidate_queue_http_is_local_only(state):
    create_dossier(state)
    body = {
        "action": "save",
        "id": "4" * 32,
        "dosar_id": DOSAR_ID,
        "candidate": candidate(),
    }

    assert request(state, "POST", "/api/dosare/reguli", body, origin="https://evil.test")[0] == 403
    assert request(state, "POST", "/api/dosare/reguli", body, length=16001)[0] == 413

    code, saved = request(state, "POST", "/api/dosare/reguli", body)
    assert code == 200
    assert saved["candidate"]["contract"] == "rule-candidate-v1"

    code, queue = request(state, "GET", "/api/dosare/reguli?id=" + DOSAR_ID)
    assert code == 200
    assert queue["total"] == 1
    assert queue["items"][0]["bucket"] == "reviewable"
