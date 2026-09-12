import io
import json
from types import SimpleNamespace

import pytest

from scripts import cellar, depozit, documente_proiecte, dosare, tracker_events
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


def write_project(stare, plx="plx-10-2026"):
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la) "
            "VALUES (?,2,'10','Proiect test','la comisii','2026-01-01')",
            (plx,),
        )
        con.commit()


def write_dossier(stare, ident="a" * 32):
    return dosare.creeaza(
        dosare.cale(stare),
        {
            "id": ident,
            "titlu": "Dosar impact",
            "intrebare": "Ce se schimbă?",
            "domeniu": "test",
        },
    )


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
    assert listed["sources"][0]["sync_status"] == {
        "state": "discovered",
        "label": "Source known by URL or public identifier; no fetch attempted in this queue.",
        "severity": "ready",
        "can_queue": True,
        "can_sync": True,
        "can_review": False,
        "next_action": "Pune sursa în coadă sau sincronizeaz-o explicit.",
    }
    selected = registry.lista(stare, {"id": [row["id"]]})
    assert selected["total"] == 1
    assert selected["sources"][0]["id"] == row["id"]

    queued = registry.executa(stare, {"action": "queue", "id": row["id"]})
    assert queued["state"] == "queued"
    assert queued["sync_status"]["can_queue"] is False
    assert queued["sync_status"]["can_sync"] is True
    assert (
        queued["sync_status"]["next_action"]
        == "Rulează sincronizarea pentru această singură sursă."
    )

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
    assert fetched["sync_status"]["severity"] == "ready"

    filtered = registry.lista(stare, {"family": ["ue_cellar"], "state": ["fetched"]})
    assert filtered["total"] == 1
    assert filtered["counts"]["ue_cellar:fetched"] == 1
    assert filtered["sources"][0]["attempts"][0]["state"] == "fetched"
    assert filtered["sources"][0]["attempts"][0]["content_hash"] == "a" * 64


def test_registry_status_contract_for_non_sync_source(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "ccr", "identifier": "decizie-1"})

    assert row["sync_status"]["can_queue"] is False
    assert row["sync_status"]["can_sync"] is False
    assert row["sync_status"]["can_review"] is False
    assert row["sync_status"]["severity"] == "ready"


def test_registry_names_precise_public_source_families():
    families = registry.families()

    assert families["consultare_econsultare"] == "Consultări publice · e-consultare"
    assert families["monitorul_oficial_pi"] == "Monitorul Oficial · Partea I"
    assert families["monitorul_oficial_other_parts"] == "Monitorul Oficial · Părțile II-VII"
    assert families["monitorul_oficial_local"] == "Monitorul Oficial Local"
    assert families["avize"] == "Avize și opinii instituționale"
    assert "consultare_econsultare" in registry.SYNC_FAMILIES
    assert "monitorul_oficial_pi" not in registry.SYNC_FAMILIES


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


def test_registry_syncs_real_project_sheet_snapshot_history(monkeypatch, tmp_path):
    stare = state(tmp_path)
    write_project(stare)
    row = registry.executa(stare, {"family": "camera", "identifier": "plx-10-2026"})
    html = '<a href="https://www.cdep.ro/proiecte/a.pdf">Raport</a>'
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiativa_etapa"
            "(plx_id,ord,data,camera,actiune,comisii,steno_ids,steno_idm) "
            "VALUES ('plx-10-2026',0,'2026-01-10','Camera Deputaților',"
            "'raport favorabil depus','Comisia juridică',NULL,NULL)"
        )
        con.commit()

    monkeypatch.setattr(
        documente_proiecte,
        "descarca",
        lambda url, *args: html.encode(),
    )

    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert changed["state"] == "changed"
    assert changed["last_hash"]
    events = tracker_events.lista(stare, {"project_id": ["plx-10-2026"]})
    assert {event["event_type"] for event in events["events"]} == {
        "committee_assignment",
        "report_filed",
    }
    assert events["events"][0]["source_id"] == row["id"]
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["snapshots"][0]["content_hash"] == changed["last_hash"]
    assert selected["snapshots"][0]["parser_version"] == "achizitii_proiecte.v1"
    assert selected["snapshots"][0]["summary"] == {
        "plx": "plx-10-2026",
        "operation": "descopera",
        "fisa_url": "https://www.cdep.ro/ords/pls/proiecte/upl_pck2015.proiect?cam=2&idp=10",
        "documents": 1,
        "versions": 0,
        "imported_status": "",
        "truncated": False,
    }

    unchanged = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert unchanged["state"] == "unchanged"

    html = '<a href="https://www.cdep.ro/proiecte/b.pdf">Raport nou</a>'
    changed_again = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert changed_again["state"] == "changed"
    assert changed_again["last_hash"] != changed["last_hash"]
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert [s["summary"]["documents"] for s in selected["snapshots"]] == [1, 1, 1]
    assert [a["state"] for a in selected["attempts"][:2]] == ["changed", "fetched"]


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


def test_registry_attention_filter_and_review_action(monkeypatch, tmp_path):
    stare = state(tmp_path)
    changed = registry.executa(stare, {"family": "camera", "identifier": "PL-x 5"})
    ok = registry.executa(stare, {"family": "camera", "identifier": "PL-x 6"})
    unsupported = registry.executa(stare, {"family": "ccr", "identifier": "decizie-2"})

    def discover_project(state, request):
        return {
            "fisa_url": f"https://www.cdep.ro/proiecte/{request['plx']}",
            "documente": [{"url": "https://www.cdep.ro/proiecte/x.pdf", "label": request["plx"]}],
        }

    monkeypatch.setattr("scripts.achizitii_proiecte.executa", discover_project)
    changed_result = registry.executa(stare, {"action": "sync", "id": changed["id"]})
    ok_result = registry.executa(stare, {"action": "sync", "id": ok["id"]})
    registry.executa(stare, {"action": "review", "id": ok_result["id"]})

    attention = registry.lista(stare, {"attention": ["1"]})
    assert attention["attention_states"] == ["changed", "failed", "needs_review", "rate_limited"]
    assert [row["id"] for row in attention["sources"]] == [changed_result["id"]]

    reviewed = registry.executa(
        stare,
        {"action": "review", "id": changed_result["id"], "note": "Verificat în fișa proiectului."},
    )
    assert reviewed["state"] == "unchanged"
    assert reviewed["last_hash"] == changed_result["last_hash"]
    assert registry.lista(stare, {"attention": ["1"]})["total"] == 0

    with pytest.raises(ValueError, match="schimbate"):
        registry.executa(stare, {"action": "review", "id": unsupported["id"]})


def test_registry_changed_project_exposes_local_impact(monkeypatch, tmp_path):
    stare = state(tmp_path)
    write_dossier(stare)
    row = registry.executa(stare, {"family": "camera", "identifier": "PL-x 9"})

    with dosare._open(dosare.cale(stare), write=True) as con:
        con.execute(
            "INSERT INTO rulari "
            "(id,dosar_id,creat_la,engine_version,sha256,filtre_json,raport_json,dovezi_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                "9" * 32,
                "a" * 32,
                "2026-01-01T00:00:00+00:00",
                "matrice-proiecte-v1",
                "0" * 64,
                dosare._json({"emitent": "Parlamentul"}),
                dosare._json(
                    {
                        "selectie_proiecte": {
                            "a": {"plx_id": "PL-x 9", "versiune_id": "1" * 64},
                            "b": {"plx_id": "PL-x 10", "versiune_id": "2" * 64},
                        }
                    }
                ),
                dosare._json(
                    {
                        "manifest": {
                            "dependente": [
                                {
                                    "sursa": "proiect_importat",
                                    "plx_id": "PL-x 9",
                                    "versiune_id": "1" * 64,
                                }
                            ]
                        }
                    }
                ),
            ),
        )
        con.execute(
            "INSERT INTO watchlist_dosare "
            "(id,dosar_id,tip,valoare,eticheta,creat_la) VALUES (?,?,?,?,?,?)",
            (
                "8" * 32,
                "a" * 32,
                "project",
                "PL-x 9",
                "Proiect urmărit",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    def discover_project(state, request):
        return {
            "fisa_url": f"https://www.cdep.ro/proiecte/{request['plx']}",
            "documente": [{"url": "https://www.cdep.ro/proiecte/x.pdf", "label": request["plx"]}],
        }

    monkeypatch.setattr("scripts.achizitii_proiecte.executa", discover_project)
    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})
    listed = registry.lista(stare, {"id": [changed["id"]]})["sources"][0]

    assert changed["impact"]["contract"] == "changed-source-impact-v1"
    assert listed["impact"]["summary"]["affected_runs"] == 1
    assert listed["impact"]["summary"]["affected_dossiers"] == 1
    assert listed["impact"]["actions"]["open_affected_runs"] is True
    assert listed["impact"]["actions"]["mark_reviewed"] is True
    assert listed["impact"]["samples"]["runs"][0]["dosar_titlu"] == "Dosar impact"


def test_registry_celex_impact_counts_notes_rules_and_watchlist(tmp_path):
    stare = state(tmp_path)
    dossier = write_dossier(stare)
    path = dosare.cale(stare)
    row = registry.executa(stare, {"family": "ue_cellar", "identifier": "32014L0024"})
    registry.executa(stare, {"action": "queue", "id": row["id"]})
    changed = registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "fetched",
            "content_hash": "d" * 64,
            "parser_version": "achizitii_ue.v1",
        },
    )
    changed = registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "changed",
            "content_hash": changed["last_hash"],
            "parser_version": "achizitii_ue.v1",
        },
    )
    with dosare._open(path, write=True) as con:
        con.execute(
            "INSERT INTO note_manuale VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "b" * 32,
                dossier["id"],
                "Notă UE",
                "risc_ue",
                "32014L0024",
                "art1",
                "Text",
                "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024",
                "d" * 64,
                "Revizuiește sursa UE.",
                "needs_evidence",
                0,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        con.execute(
            "INSERT INTO watchlist_dosare "
            "(id,dosar_id,tip,valoare,eticheta,creat_la) VALUES (?,?,?,?,?,?)",
            (
                "c" * 32,
                dossier["id"],
                "celex",
                "32014L0024",
                "Directiva",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        con.execute(
            "INSERT INTO rule_candidate_queue "
            "(id,dosar_id,candidate_id,provision_id,act_id,locator,status,review_state,"
            "modality,source_hash,text_sha256,payload_json,creat_la) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "f" * 32,
                dossier["id"],
                "cand-1",
                "eu:32014L0024#art1",
                "32014L0024",
                "art1",
                "reviewable",
                "pending",
                "obligation",
                "d" * 64,
                "1" * 64,
                dosare._json({"contract": "rule-candidate-v1"}),
                "2026-01-01T00:00:00+00:00",
            ),
        )
        con.execute(
            "INSERT INTO law_rule_drafts "
            "(id,dosar_id,candidate_id,queue_id,provision_id,act_id,locator,modality,"
            "source_hash,text_sha256,accepted_by,acceptance_note,payload_json,creat_la) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "e" * 32,
                dossier["id"],
                "cand-1",
                "f" * 32,
                "eu:32014L0024#art1",
                "32014L0024",
                "art1",
                "obligation",
                "d" * 64,
                "1" * 64,
                "tester",
                "acceptat",
                dosare._json({"contract": "law-rule-draft-v1", "celex": "32014L0024"}),
                "2026-01-01T00:00:00+00:00",
            ),
        )

    listed = registry.lista(stare, {"id": [changed["id"]]})["sources"][0]
    impact = listed["impact"]

    assert impact["summary"]["affected_notes"] == 1
    assert impact["summary"]["affected_rule_drafts"] == 1
    assert impact["summary"]["affected_watchlist_items"] == 1
    assert impact["samples"]["notes"][0]["titlu"] == "Notă UE"
    assert impact["samples"]["rule_drafts"][0]["act_id"] == "32014L0024"
    assert impact["actions"]["create_review_note"] is True


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


def test_registry_post_route_syncs_one_source(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "ue_cellar", "identifier": "32014L0024"})

    def import_celex(state, request):
        write_eu_text(state, request["celex"], "Text oficial nou")
        return {"celex": request["celex"], "stare": "ok", "limba": "RON", "schimbat": True}

    monkeypatch.setattr("scripts.achizitii_ue.importa", import_celex)
    handler = object.__new__(face_handler(stare))
    body = json.dumps({"action": "sync", "id": row["id"]}).encode()
    handler.path = "/api/registru-surse"
    handler.rfile = io.BytesIO(body)
    handler.headers = {"Host": "localhost:8123", "Content-Length": str(len(body))}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))

    handler.do_POST()

    assert result[0][0] == 200
    assert result[0][1]["state"] == "changed"
    assert result[0][1]["last_hash"]
