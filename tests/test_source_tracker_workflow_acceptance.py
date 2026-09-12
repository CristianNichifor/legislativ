import io
import json
from types import SimpleNamespace

from scripts import cellar, dosare
from scripts.server import face_handler


DOSSIER_ID = "a" * 32
NOTE_ID = "b" * 32


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", eu=tmp_path / "eu.db")


def request(stare, method, url, body=None):
    handler = object.__new__(face_handler(stare))
    raw = json.dumps(body).encode() if body is not None else b""
    handler.path = url
    handler.rfile = io.BytesIO(raw)
    handler.headers = {"Host": "localhost:8123", "Content-Length": str(len(raw))}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def write_eu_text(stare, celex, text):
    manifestation = cellar.ManifestareUE(
        celex=celex,
        work_uri="http://work",
        expression_uri="http://expr",
        manifestation_uri="http://manifest",
        limba="RON",
        format="TXT",
        item_url="https://publications.europa.eu/resource/cellar/test/DOC_1",
        titlu="Directiva test",
        data_document="2014-02-26",
        tip_uri=None,
        in_vigoare=True,
    )
    with cellar.deschide(stare.eu) as con:
        cellar.scrie_celex(con, celex, [manifestation], manifestation, text)


def note_payload(source, dossier_id=DOSSIER_ID):
    return {
        "id": NOTE_ID,
        "dosar_id": dossier_id,
        "revizie": 0,
        "title": "Risc UE legat de sursa sincronizată",
        "type": "risc_ue",
        "act_id": source["identifier"],
        "locator": "art2",
        "evidence_quote": "Text UE sincronizat pentru verificare.",
        "source_url": source["url"],
        "source_hash": source["last_hash"],
        "reasoning": "Nota păstrează referința la sursa locală sincronizată.",
        "status": "ready_for_review",
    }


def test_register_sync_tracker_timeline_and_dossier_note_reference_acceptance(
    monkeypatch, tmp_path
):
    stare = state(tmp_path)

    def import_celex(state_arg, request_arg):
        assert state_arg is stare
        write_eu_text(stare, request_arg["celex"], "Text UE sincronizat pentru verificare.")
        return {
            "celex": request_arg["celex"],
            "stare": "ok",
            "limba": "RON",
            "schimbat": True,
        }

    monkeypatch.setattr("scripts.achizitii_ue.importa", import_celex)

    code, source = request(
        stare,
        "POST",
        "/api/registru-surse",
        {
            "action": "discover",
            "family": "ue_cellar",
            "identifier": "32014L0024",
            "url": "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024",
            "label": "Directiva achiziții publice",
        },
    )
    assert code == 200
    assert source["state"] == "discovered"

    code, synced = request(
        stare, "POST", "/api/registru-surse", {"action": "sync", "id": source["id"]}
    )
    assert code == 200
    assert synced["state"] == "changed"
    assert synced["sync_status"]["can_review"] is True
    assert synced["last_hash"]
    assert synced["parser_version"] == "achizitii_ue.v1"

    dosare.creeaza(
        dosare.cale(stare),
        {
            "id": DOSSIER_ID,
            "titlu": "Dosar pentru sursă sincronizată",
            "intrebare": "Ce evenimente și note depind de sursă?",
            "domeniu": "acceptance",
        },
    )

    code, event = request(
        stare,
        "POST",
        "/api/tracker-evenimente",
        {
            "action": "add",
            "event_type": "committee_assignment",
            "project_id": "PL-x 10/2026",
            "dossier_id": DOSSIER_ID,
            "source_family": synced["family"],
            "source_id": synced["id"],
            "source_url": synced["url"],
            "content_hash": synced["last_hash"],
            "occurred_at": "2026-09-12T10:00:00+00:00",
            "title": "Comisie sesizată după sincronizare",
            "payload": {"committee": "Comisia juridică", "source_state": synced["state"]},
        },
    )
    assert code == 200
    assert event["event"]["source_id"] == synced["id"]

    code, project_timeline = request(
        stare, "GET", "/api/tracker-evenimente?project_id=PL-x%2010/2026"
    )
    assert code == 200
    assert project_timeline["contract"] == "legislative-tracker-events-v1"
    assert project_timeline["total"] == 1
    assert project_timeline["events"][0]["source_id"] == synced["id"]
    assert project_timeline["events"][0]["payload"]["source_state"] == "changed"

    code, dossier_timeline = request(
        stare, "GET", "/api/tracker-evenimente?dossier_id=" + DOSSIER_ID
    )
    assert code == 200
    assert dossier_timeline["total"] == 1
    assert dossier_timeline["events"][0]["project_id"] == "PL-x 10/2026"

    code, note = request(stare, "POST", "/api/dosare/note", note_payload(synced))
    assert code == 200
    assert note["source_url"] == synced["url"]
    assert note["source_hash"] == synced["last_hash"]
    assert note["act_id"] == synced["identifier"]

    code, notes = request(stare, "GET", "/api/dosare/note?id=" + DOSSIER_ID)
    assert code == 200
    assert notes["total"] == 1
    assert notes["note"][0]["id"] == NOTE_ID

    code, registry = request(stare, "GET", "/api/registru-surse?id=" + synced["id"])
    assert code == 200
    row = registry["sources"][0]
    assert row["id"] == synced["id"]
    assert row["impact"]["contract"] == "changed-source-impact-v1"
    assert row["impact"]["summary"]["affected_notes"] == 1
    assert row["impact"]["samples"]["notes"][0]["id"] == NOTE_ID
    assert row["impact"]["samples"]["notes"][0]["dosar_id"] == DOSSIER_ID
