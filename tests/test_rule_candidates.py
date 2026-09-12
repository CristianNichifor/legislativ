from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from scripts import rule_candidates
from scripts.browser_workspace import route
from scripts.server import face_handler


def payload(**patch):
    data = {
        "provision_id": "ro:lege-98-2016#art7.alin2",
        "act_id": "lege-98-2016",
        "locator": "art7.alin2",
        "source_hash": "a" * 64,
        "text": "Autoritatea contractantă publică anunțul în SEAP.",
        "modality": "obligation",
        "review_state": "human_reviewed",
        "actor": "autoritatea contractantă",
        "condition": "procedura este inițiată",
        "action": "publică anunțul în SEAP",
        "deadline": "",
        "exceptions": ["cazurile expres exceptate de lege"],
        "effect": "procedura poate fi contestată dacă publicarea lipsește",
        "reviewer": "test",
    }
    data.update(patch)
    return data


def test_rule_candidate_is_reviewable_and_source_bound():
    out = rule_candidates.validate(payload())

    assert out["contract"] == "rule-candidate-v1"
    assert out["status"] == "reviewable"
    assert len(out["candidate_id"]) == 32
    assert len(out["text_sha256"]) == 64
    assert out["source_hash"] == "a" * 64
    assert out["actor"] == "autoritatea contractantă"
    assert out["exceptions"] == ["cazurile expres exceptate de lege"]
    assert any("nu este o concluzie juridică" in item for item in out["limitations"])


def test_candidate_id_is_stable_for_same_normalized_payload():
    first = rule_candidates.validate(payload())
    second = rule_candidates.validate(payload())

    assert first["candidate_id"] == second["candidate_id"]


@pytest.mark.parametrize(
    ("modality", "status"),
    [
        ("not_codeable", "not_codeable"),
        ("vague_standard", "needs_legal_review"),
        ("obligation", "needs_more_structure"),
    ],
)
def test_non_executable_states_are_explicit(modality, status):
    out = rule_candidates.validate(payload(modality=modality, actor="", action=""))

    assert out["status"] == status
    assert out["limitations"]


@pytest.mark.parametrize(
    "patch",
    [
        {"source_hash": "x"},
        {"modality": "prediction"},
        {"review_state": "approved_by_ai"},
        {"exceptions": "none"},
        {"extra": "field"},
    ],
)
def test_invalid_candidate_payload_is_rejected(patch):
    with pytest.raises(ValueError):
        rule_candidates.validate(payload(**patch))


def request(state, method, url, body=None, host="localhost:8123", origin=None):
    handler = object.__new__(face_handler(state))
    handler.path = url
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {"Host": host, "Content-Length": str(len(raw))}
    if origin:
        handler.headers["Origin"] = origin
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_rule_candidate_preview_http_is_local_only(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)

    assert (
        request(
            state,
            "POST",
            "/api/dosare/rule-candidates/preview",
            payload(),
            origin="https://evil.test",
        )[0]
        == 403
    )
    code, data = request(state, "POST", "/api/dosare/rule-candidates/preview", payload())

    assert code == 200
    assert data["contract"] == "rule-candidate-v1"
    assert data["status"] == "reviewable"


def test_browser_workspace_routes_rule_candidate_preview(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")

    out = route(
        state,
        "/api/dosare/rule-candidates/preview",
        {},
        payload(modality="deadline"),
        method="POST",
    )

    assert out["contract"] == "rule-candidate-v1"
    assert out["modality"] == "deadline"
