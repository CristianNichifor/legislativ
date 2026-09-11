from types import SimpleNamespace

import pytest

from scripts import dosare, note_manuale
from tests.test_dosare import ID, OTHER, create, request


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def note_payload(**patch):
    return {
        "id": "c" * 32,
        "dosar_id": ID,
        "revizie": 0,
        "title": "Lacună privind norme lipsă",
        "type": "lacuna",
        "act_id": "lege-98-2016",
        "locator": "art7",
        "evidence_quote": "Guvernul aprobă normele metodologice.",
        "source_url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
        "source_hash": "a" * 64,
        "reasoning": "Nu există normele indicate în corpusul local.",
        "status": "draft",
        **patch,
    }


def test_manual_notes_save_update_list_and_reopen(state):
    create(state)
    path = dosare.cale(state)

    first = note_manuale.salveaza(path, note_payload())

    assert first["id"] == "c" * 32
    assert first["type"] == "lacuna"
    assert first["status"] == "draft"
    assert first["revizie"] == 0
    assert note_manuale.citeste(path, ID, first["id"]) == first
    assert note_manuale.lista(path, ID)["total"] == 1

    retry = note_manuale.salveaza(path, note_payload())
    assert retry == first

    changed = note_manuale.salveaza(
        path,
        note_payload(
            revizie=0,
            status="ready-for-review",
            reasoning="Dovada este selectată; trebuie revizie juridică.",
        ),
    )
    assert changed["revizie"] == 1
    assert changed["status"] == "ready_for_review"
    assert changed["reasoning"].startswith("Dovada")
    assert note_manuale.lista(path, ID, status="ready_for_review")["total"] == 1
    assert note_manuale.lista(path, ID, status="draft")["total"] == 0

    with pytest.raises(ValueError, match="modificată"):
        note_manuale.salveaza(path, note_payload(revizie=0, status="reviewed"))


def test_manual_notes_validate_identity_source_and_ownership(state):
    create(state)
    create(state, OTHER)
    path = dosare.cale(state)
    note_manuale.salveaza(path, note_payload())

    for patch in (
        {"unexpected": "x"},
        {"id": "../x"},
        {"title": " "},
        {"type": "gap"},
        {"status": "accepted"},
        {"source_url": "file:///tmp/x"},
        {"source_hash": "bad"},
        {"evidence_quote": "\x00"},
        {"revizie": -1},
    ):
        with pytest.raises(ValueError):
            note_manuale.salveaza(path, note_payload(**patch))

    with pytest.raises(ValueError, match="altui dosar"):
        note_manuale.salveaza(path, note_payload(dosar_id=OTHER))
    with pytest.raises(ValueError, match="inexistent"):
        note_manuale.citeste(path, OTHER, "c" * 32)


def test_manual_notes_http_boundaries(state):
    create(state)
    body = note_payload()

    assert request(state, "POST", "/api/dosare/note", body, origin="https://evil.test")[0] == 403
    assert request(state, "POST", "/api/dosare/note", body, length=16001)[0] == 413
    assert request(state, "POST", "/api/dosare/note", body)[0] == 200
    assert request(state, "GET", "/api/dosare/note?id=" + ID)[1]["total"] == 1
    assert request(state, "GET", "/api/dosare/note?id=" + ID + "&status=draft")[1]["total"] == 1
    assert (
        request(state, "GET", "/api/dosare/note?id=" + ID + "&note_id=" + body["id"])[1]["title"]
        == body["title"]
    )
    assert request(state, "GET", "/api/dosare/note?id=" + ID + "&status=bad")[0] == 400
    assert request(state, "GET", "/api/dosare/note", host="evil.test:8123")[0] == 403

    state.date_dir = "static"
    assert request(state, "GET", "/api/dosare/note?id=" + ID)[0] == 400
