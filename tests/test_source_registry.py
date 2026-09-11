import io
import json
from types import SimpleNamespace

import pytest

from scripts import cellar
from scripts import source_registry as registry
from scripts.server import face_handler


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", eu=tmp_path / "eu.db")


def write_eu_text(stare, celex="32014L0024", text="Text oficial UE"):
    manifestation = cellar.ManifestareUE(
        celex=celex,
        work_uri="http://work",
        expression_uri="http://expr",
        manifestation_uri="http://manifest",
        limba="RON",
        format="TXT",
        item_url="https://publications.europa.eu/resource/cellar/test/DOC_1",
        titlu="Directiva",
        data_document="2014-02-26",
        tip_uri=None,
        in_vigoare=True,
    )
    with cellar.deschide(stare.eu) as con:
        cellar.scrie_celex(con, celex, [manifestation], manifestation, text)


def test_registry_discovers_lists_queues_and_records_one_source(tmp_path):
    stare = state(tmp_path)

    row = registry.executa(
        stare,
        {
            "action": "discover",
            "family": "ue_cellar",
            "identifier": "32014L0024",
            "url": "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024",
            "label": "Directiva achiziții",
        },
    )
    assert row["state"] == "discovered"
    assert row["id"].startswith("src_")
    again = registry.executa(
        stare,
        {"action": "discover", "family": "ue_cellar", "identifier": "32014L0024"},
    )
    assert again["url"] == row["url"]

    listed = registry.lista(stare)
    assert listed["total"] == 1
    assert listed["families"]["ue_cellar"].startswith("Drept UE")
    assert listed["sources"][0]["identifier"] == "32014L0024"

    queued = registry.executa(stare, {"action": "queue", "id": row["id"]})
    assert queued["state"] == "queued"

    fetched = registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "fetched",
            "http_status": 200,
            "content_hash": "a" * 64,
            "parser_version": "cellar-v1",
        },
    )
    assert fetched["state"] == "fetched"
    assert fetched["last_hash"] == "a" * 64
    assert fetched["parser_version"] == "cellar-v1"

    filtered = registry.lista(stare, {"family": ["ue_cellar"], "state": ["fetched"]})
    assert filtered["total"] == 1
    assert filtered["counts"]["ue_cellar:fetched"] == 1
    assert filtered["sources"][0]["attempts"][0]["state"] == "fetched"
    assert filtered["sources"][0]["attempts"][0]["content_hash"] == "a" * 64


def test_registry_rejects_invalid_sources_and_transitions(tmp_path):
    stare = state(tmp_path)
    with pytest.raises(ValueError, match="Familie"):
        registry.executa(stare, {"family": "other", "identifier": "x"})
    with pytest.raises(ValueError, match="URL"):
        registry.executa(stare, {"family": "ccr", "url": "file:///tmp/x"})

    row = registry.executa(stare, {"family": "ccr", "identifier": "decizie-1"})
    with pytest.raises(ValueError, match="Tranziție"):
        registry.executa(stare, {"action": "record", "id": row["id"], "state": "changed"})
    queued = registry.executa(stare, {"action": "queue", "id": row["id"]})
    assert queued["state"] == "queued"
    with pytest.raises(ValueError, match="Hash"):
        registry.executa(
            stare,
            {"action": "record", "id": row["id"], "state": "fetched", "content_hash": "nope"},
        )


def test_registry_missing_store_lists_empty_without_creating_file(tmp_path):
    stare = state(tmp_path)
    out = registry.lista(stare)
    assert out["total"] == 0
    assert out["sources"] == []
    assert not registry.cale(stare).exists()


def test_registry_syncs_one_queued_eu_source(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "ue_cellar", "identifier": "32014L0024"})

    def import_celex(state, request):
        assert state is stare
        assert request == {"celex": "32014L0024"}
        write_eu_text(stare, request["celex"], "Text nou")
        return {"celex": request["celex"], "stare": "ok", "limba": "RON", "schimbat": True}

    monkeypatch.setattr("scripts.achizitii_ue.importa", import_celex)
    out = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert out["state"] == "changed"
    assert out["last_hash"]
    assert out["parser_version"] == "achizitii_ue.v1"
    with registry._open(registry.cale(stare)) as con:
        attempts = con.execute(
            "SELECT state FROM source_attempts WHERE source_id=? ORDER BY seq", (row["id"],)
        ).fetchall()
    assert [r["state"] for r in attempts] == ["fetched", "changed"]


def test_registry_sync_records_unchanged_metadata_and_failures(monkeypatch, tmp_path):
    stare = state(tmp_path)
    unchanged = registry.executa(stare, {"family": "ue_cellar", "identifier": "32014L0024"})
    metadata = registry.executa(stare, {"family": "ue_cellar", "identifier": "32018R1805"})
    failure = registry.executa(stare, {"family": "ue_cellar", "identifier": "32016R0679"})
    registry.executa(stare, {"action": "queue", "id": unchanged["id"]})
    registry.executa(stare, {"action": "queue", "id": metadata["id"]})
    registry.executa(stare, {"action": "queue", "id": failure["id"]})

    def import_celex(state, request):
        if request["celex"] == "32014L0024":
            write_eu_text(stare, request["celex"], "Text existent")
            return {"celex": request["celex"], "stare": "ok", "limba": "RON", "schimbat": False}
        if request["celex"] == "32018R1805":
            return {"celex": request["celex"], "stare": "metadate", "schimbat": False}
        raise ValueError("Preluarea UE a esuat sau sursa depaseste limitele disponibile.")

    monkeypatch.setattr("scripts.achizitii_ue.importa", import_celex)

    unchanged_result = registry.executa(stare, {"action": "sync", "id": unchanged["id"]})
    metadata_result = registry.executa(stare, {"action": "sync", "id": metadata["id"]})
    assert unchanged_result["state"] == "unchanged"
    assert metadata_result["state"] == "needs_review"
    failed = registry.executa(stare, {"action": "sync", "id": failure["id"]})
    assert failed["state"] == "failed"
    assert failed["last_error"] == "fetch_failed"


def test_registry_syncs_one_project_document(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "parlament",
            "identifier": "PL-x 1",
            "url": "https://www.cdep.ro/proiecte/a.pdf",
        },
    )

    def import_project(state, request):
        assert state is stare
        assert request == {
            "plx": "PL-x 1",
            "operatie": "importa",
            "url": "https://www.cdep.ro/proiecte/a.pdf",
        }
        return {"id": "v1", "sha256": "b" * 64, "status": "extras", "text": "Text"}

    monkeypatch.setattr("scripts.achizitii_proiecte.executa", import_project)
    out = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert out["state"] == "changed"
    assert out["last_hash"] == "b" * 64
    assert out["parser_version"] == "achizitii_proiecte.v1"
    with registry._open(registry.cale(stare)) as con:
        attempts = con.execute(
            "SELECT state FROM source_attempts WHERE source_id=? ORDER BY seq", (row["id"],)
        ).fetchall()
    assert [r["state"] for r in attempts] == ["fetched", "changed"]


def test_registry_syncs_project_sheet_and_detects_unchanged(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "camera", "identifier": "PL-x 2"})

    def discover_project(state, request):
        assert request == {"plx": "PL-x 2", "operatie": "descopera"}
        return {
            "fisa_url": "https://www.cdep.ro/pls/proiecte/upl_pck2015.proiect?cam=2&idp=2",
            "documente": [{"url": "https://www.cdep.ro/proiecte/b.pdf", "label": "Raport"}],
        }

    monkeypatch.setattr("scripts.achizitii_proiecte.executa", discover_project)
    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert changed["state"] == "changed"
    unchanged = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert unchanged["state"] == "unchanged"


def test_registry_sync_records_project_review_and_failure(monkeypatch, tmp_path):
    stare = state(tmp_path)
    review = registry.executa(
        stare,
        {
            "family": "parlament",
            "identifier": "PL-x 3",
            "url": "https://www.cdep.ro/proiecte/c.pdf",
        },
    )
    failure = registry.executa(stare, {"family": "senat", "identifier": "PL-x 4"})

    def import_project(state, request):
        if request["plx"] == "PL-x 3":
            return {"id": "v1", "sha256": "c" * 64, "status": "ocr_necesar", "text": ""}
        raise ValueError("Sursa oficiala nu este disponibila.")

    monkeypatch.setattr("scripts.achizitii_proiecte.executa", import_project)

    needs_review = registry.executa(stare, {"action": "sync", "id": review["id"]})
    assert needs_review["state"] == "needs_review"
    failed = registry.executa(stare, {"action": "sync", "id": failure["id"]})
    assert failed["state"] == "failed"
    assert failed["last_error"] == "fetch_failed"


def test_registry_sync_rejects_unsupported_sources(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "ccr", "identifier": "decizie-1"})
    with pytest.raises(ValueError, match="nu are sincronizare"):
        registry.executa(stare, {"action": "sync", "id": row["id"]})


def test_registry_post_route_is_allowlisted(tmp_path):
    stare = state(tmp_path)
    handler = object.__new__(face_handler(stare))
    body = json.dumps(
        {"action": "discover", "family": "parlament", "identifier": "PL-x 1/2024"}
    ).encode()
    handler.path = "/api/registru-surse"
    handler.rfile = io.BytesIO(body)
    handler.headers = {"Host": "localhost:8123", "Content-Length": str(len(body))}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_POST()

    assert result[0][0] == 200
    assert result[0][1]["family"] == "parlament"
