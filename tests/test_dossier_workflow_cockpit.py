from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import (
    browser_workspace,
    dosare,
    law_rule_drafts,
    note_manuale,
    propuneri,
    revizuiri,
    rule_candidate_queue,
)
from tests.test_dosare import request

DOSAR_ID = "d" * 32
PROPOSAL_ID = "e" * 32
DRAFT_ID = "f" * 32
SOURCE_HASH = "a" * 64


@pytest.fixture
def state(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    return SimpleNamespace(
        initiative=tmp_path / "public-source-v1.db",
        date_dir=None,
        dosare_db=private / "dosare.db",
    )


def _create_dossier_with_matrix_run(state, monkeypatch):
    path = dosare.cale(state)
    dosare.creeaza(
        path,
        {
            "id": DOSAR_ID,
            "titlu": "Lacune achizitii",
            "intrebare": "Ce lipseste pentru achizitii?",
            "domeniu": "achizitii publice",
        },
    )
    report = {
        "gasit": True,
        "acte": {"acte": [{"act_id": "lege-98-2016"}]},
        "rand": {
            "exemple": {
                "viduri": [
                    {
                        "act_id": "lege-98-2016",
                        "locator": "art7.alin2",
                        "text": "Autoritatea contractanta publica anuntul in SEAP.",
                        "sursa_url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
                        "sursa_sha256": SOURCE_HASH,
                    }
                ]
            }
        },
        "referinte_ue": [],
        "markdown": "# Matrice achizitii",
    }
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    run = dosare.salveaza_rulare(
        state, {"dosar_id": DOSAR_ID, "filtre": {"emitent": "Parlamentul"}}
    )
    finding = revizuiri.constatari(run)[0]
    return path, run, finding


def _selected_evidence(run, finding):
    evidence = finding["dovada"]
    return {
        "dosar_id": DOSAR_ID,
        "run_id": run["id"],
        "finding_id": finding["id"],
        "source": {
            "kind": "matrix_gap",
            "title": "Lacuna SEAP",
            "type": "lacuna",
            "act_id": evidence["act_id"],
            "locator": evidence["locator"],
            "quote": "private selected evidence quote",
            "source_url": evidence["sursa_url"],
            "source_hash": evidence["sursa_sha256"],
            "reasoning": "private legal staff note",
            "status": "ready_for_review",
        },
        "rule": {
            "text": evidence["text"],
            "modality": "obligation",
            "review_state": "machine_detected",
            "actor": "autoritatea contractanta",
            "action": "publica anuntul in SEAP",
            "confidence": "medium",
        },
    }


def test_matrix_evidence_item_has_no_dead_end_to_note_proposal_rule_backup_restore(
    state, tmp_path, monkeypatch
):
    path, run, finding = _create_dossier_with_matrix_run(state, monkeypatch)
    workflow = dosare.evidence_workflow(path, _selected_evidence(run, finding))

    assert workflow["contract"] == "dossier-evidence-workflow-v1"
    assert workflow["actions"]["save_evidence"]["enabled"] is True
    assert workflow["actions"]["draft_proposal"]["enabled"] is True
    assert workflow["actions"]["queue_rule_candidate"]["enabled"] is True
    assert workflow["actions"]["backup_export"]["explicit_user_action_required"] is True
    assert workflow["actions"]["source_update"]["private_work_survives"] is True

    note = note_manuale.salveaza(path, workflow["actions"]["save_evidence"]["payload"])
    queued = rule_candidate_queue.executa(
        path, workflow["actions"]["queue_rule_candidate"]["payload"]
    )
    draft = law_rule_drafts.promoveaza(
        path,
        {
            "id": DRAFT_ID,
            "dosar_id": DOSAR_ID,
            "queue_id": queued["id"],
            "accepted_by": "legal reviewer",
            "acceptance_note": "Structura pastreaza sursa citata.",
        },
    )
    proposal = propuneri.salveaza(
        path,
        {
            "id": PROPOSAL_ID,
            "dosar_id": DOSAR_ID,
            "rulare_id": run["id"],
            "constatare_id": finding["id"],
            "revizie": 0,
            "titlu": "Clarificare publicare SEAP",
            "text": "Text propus pentru lucru privat.",
            "motiv": "Pornit din dovada selectata in matrice.",
        },
    )
    cockpit = dosare.cockpit(path, DOSAR_ID)

    assert note["id"] == workflow["actions"]["save_evidence"]["payload"]["id"]
    assert proposal["id"] == PROPOSAL_ID
    assert draft["queue_id"] == queued["id"]
    assert cockpit["counts"] == {
        "runs": 1,
        "notes": 1,
        "proposals": 1,
        "rule_candidates": 1,
        "rule_drafts": 1,
        "draft_recovery_items": 0,
    }
    assert cockpit["recent"]["notes"][0]["id"] == note["id"]
    assert cockpit["recent"]["proposals"][0]["id"] == PROPOSAL_ID
    assert cockpit["recent"]["rule_candidates"][0]["id"] == queued["id"]
    assert cockpit["privacy"]["summary_omits_note_body_and_proposal_text"] is True
    summary_json = json.dumps(cockpit, ensure_ascii=False)
    assert "private selected evidence quote" not in summary_json
    assert "private legal staff note" not in summary_json
    assert "Text propus pentru lucru privat" not in summary_json

    restored = tmp_path / "restored.db"
    dosare.backup(path, restored)
    assert dosare.cockpit(restored, DOSAR_ID)["counts"] == cockpit["counts"]


def test_private_dossier_work_survives_source_update_boundary(state, monkeypatch):
    path, run, finding = _create_dossier_with_matrix_run(state, monkeypatch)
    workflow = dosare.evidence_workflow(path, _selected_evidence(run, finding))
    note_manuale.salveaza(path, workflow["actions"]["save_evidence"]["payload"])
    before = dosare.cockpit(path, DOSAR_ID)

    state.initiative = state.initiative.with_name("public-source-v2.db")
    state.date_dir = state.initiative.with_name("public-release-v2")
    after = dosare.cockpit(dosare.cale(state), DOSAR_ID)

    assert dosare.cale(state) == path
    assert after["counts"] == before["counts"]
    assert after["actions"]["source_update"]["uploads_private_data"] is False
    update_boundary = json.dumps(after["actions"]["source_update"], ensure_ascii=False)
    assert "private selected evidence quote" not in update_boundary
    assert "private legal staff note" not in update_boundary


def test_browser_workspace_routes_cockpit_without_upload_or_foreign_access(state, monkeypatch):
    path, run, finding = _create_dossier_with_matrix_run(state, monkeypatch)
    body = _selected_evidence(run, finding)

    workflow = browser_workspace.route(state, "/api/dosare/cockpit/evidence", {}, body, "POST")
    note = browser_workspace.route(
        state, "/api/dosare/note", {}, workflow["actions"]["save_evidence"]["payload"], "POST"
    )
    cockpit = browser_workspace.route(state, "/api/dosare/cockpit", {"id": [DOSAR_ID]}, {}, "GET")

    assert path == dosare.cale(state)
    assert note["id"] == workflow["actions"]["save_evidence"]["payload"]["id"]
    assert cockpit["counts"]["notes"] == 1
    assert cockpit["actions"]["restore_backup"]["validates_schema_before_replace"] is True
    assert cockpit["privacy"]["server_uploads_private_data"] is False
    assert request(state, "GET", "/api/dosare/cockpit?id=" + DOSAR_ID, host="evil.test")[0] == 403
    assert (
        request(state, "POST", "/api/dosare/cockpit/evidence", body, origin="https://evil.test")[0]
        == 403
    )
