import io
import json
from types import SimpleNamespace

import pytest

from scripts import (
    achizitii_econsultare,
    cellar,
    depozit,
    documente_proiecte,
    dosare,
    tracker_events,
)
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
    sync_status = listed["sources"][0]["sync_status"]
    assert {
        key: sync_status[key]
        for key in (
            "state",
            "label",
            "severity",
            "freshness",
            "freshness_label",
            "freshness_state",
            "can_queue",
            "can_sync",
            "can_review",
            "next_action",
        )
    } == {
        "state": "discovered",
        "label": "Source known by URL or public identifier; no fetch attempted in this queue.",
        "severity": "ready",
        "freshness": "never_synced",
        "freshness_label": "Nesincronizată; nu există încă o citire locală.",
        "freshness_state": "missing",
        "can_queue": True,
        "can_sync": True,
        "can_review": False,
        "next_action": "Pune sursa în coadă sau sincronizeaz-o explicit.",
    }
    assert sync_status["freshness_status"]["state"] == "missing"
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
    assert families["consultare_minister"] == "Consultări ministere"
    assert families["monitorul_oficial_pi"] == "Monitorul Oficial · Partea I"
    assert families["monitorul_oficial_other_parts"] == "Monitorul Oficial · Părțile II-VII"
    assert families["monitorul_oficial_local"] == "Monitorul Oficial Local"
    assert families["avize"] == "Avize și opinii instituționale"
    assert "consultare_econsultare" in registry.SYNC_FAMILIES
    assert "consultare_guvern" in registry.SYNC_FAMILIES
    assert "consultare_minister" in registry.SYNC_FAMILIES
    assert "avize" in registry.SYNC_FAMILIES
    assert "monitorul_oficial_pi" in registry.SYNC_FAMILIES
    assert "monitorul_oficial_pi" in registry.ANCHOR_SYNC_FAMILIES


def test_registry_bootstraps_required_official_source_anchors(tmp_path):
    stare = state(tmp_path)

    out = registry.executa(stare, {"action": "bootstrap"})
    again = registry.executa(stare, {"action": "bootstrap"})

    assert out["contract"] == "source-bootstrap-v1"
    assert out["created"] == 14
    assert again["created"] == 0
    assert again["updated"] == 14
    listed = registry.lista(stare)
    by_family = {row["family"]: row for row in listed["sources"]}
    assert len(by_family) == 14
    assert by_family["legislatie_ro"]["url"] == "https://legislatie.just.ro/"
    assert by_family["consultare_econsultare"]["url"].startswith("https://e-consultare.gov.ro/")
    assert by_family["ue_cellar"]["url"].startswith("https://op.europa.eu/")
    assert by_family["monitorul_oficial_local"]["url"].startswith("https://www.mdlpa.ro/")
    assert by_family["monitorul_oficial_other_parts"]["url"].startswith(
        "https://monitoruloficial.ro/"
    )
    assert by_family["camera"]["sync_status"]["can_sync"] is True
    assert by_family["consultare_guvern"]["sync_status"]["freshness"] == "family_anchor"
    assert (
        "Verifică sursa oficială de bază"
        in by_family["consultare_guvern"]["sync_status"]["next_action"]
    )


def test_registry_syncs_bootstrap_anchor_with_bounded_official_snapshot(monkeypatch, tmp_path):
    stare = state(tmp_path)
    boot = registry.executa(stare, {"action": "bootstrap"})
    camera = next(row for row in boot["sources"] if row["family"] == "camera")
    monkeypatch.setattr(
        registry,
        "_fetch_official_anchor",
        lambda url: {
            "http_status": 200,
            "content_hash": "b" * 64,
            "title": "Camera Deputaților",
            "content_type": "text/html",
            "bytes": 128,
            "truncated": False,
            "error": "",
        },
    )

    synced = registry.executa(stare, {"action": "sync", "id": camera["id"]})

    assert synced["state"] == "unchanged"
    assert synced["last_hash"] == "b" * 64
    assert synced["parser_version"] == registry.ANCHOR_PARSER_VERSION
    selected = registry.lista(stare, {"id": [camera["id"]]})["sources"][0]
    assert selected["snapshots"][0]["summary"]["title"] == "Camera Deputaților"
    assert selected["attempts"][0]["state"] == "unchanged"


def test_registry_syncs_all_bootstrap_anchors(monkeypatch, tmp_path):
    stare = state(tmp_path)
    monkeypatch.setattr(
        registry,
        "_fetch_official_anchor",
        lambda url: {
            "http_status": 200,
            "content_hash": registry._stable_hash({"url": url}),
            "title": "Official source",
            "content_type": "text/html",
            "bytes": 64,
            "truncated": False,
            "error": "",
        },
    )

    synced = registry.executa(stare, {"action": "sync_bootstrap"})

    assert synced["contract"] == "source-bootstrap-anchor-sync-v1"
    assert synced["total"] == 14
    assert synced["counts"] == {"unchanged": 14}
    listed = registry.lista(stare)
    assert {row["state"] for row in listed["sources"]} == {"unchanged"}


def test_registry_discovers_econsultare_listing_sources(monkeypatch, tmp_path):
    stare = state(tmp_path)
    detail_url = "https://e-consultare.gov.ro/Proiecte-Legislative-Publice/a/b"
    snapshot = {
        "contract": "econsultare-source-snapshot-v1",
        "family": "consultare_econsultare",
        "url": detail_url,
        "summary": {
            "title": "Proiect consultare publică",
            "authority": "Ministerul Test",
            "status": "open",
            "deadline": "28/09/2026",
            "deadline_iso": "2026-09-28",
            "documents": 0,
            "document_metadata": {"total": 0, "by_type": {}, "with_hash": 0, "labels": []},
            "truncated": False,
        },
        "title": "Proiect consultare publică",
        "authority": "Ministerul Test",
        "status": "open",
        "deadline": "28/09/2026",
        "documents": [],
        "truncated": False,
    }

    monkeypatch.setattr(
        achizitii_econsultare,
        "descopera_actiongrid",
        lambda limit=50: {
            "contract": "econsultare-actiongrid-discovery-v1",
            "listing_url": achizitii_econsultare.LISTING_URL,
            "endpoint_url": achizitii_econsultare.ACTIONGRID_URL,
            "http_status": 200,
            "snapshots": [snapshot],
            "total": 1,
            "limit": limit,
            "limitations": ["fixture"],
        },
    )

    out = registry.executa(stare, {"action": "discover_econsultare", "limit": 20})

    assert out["contract"] == "source-registry-econsultare-discovery-v1"
    assert out["created"] == 1
    assert out["updated"] == 0
    assert out["stored_snapshots"] == 1
    assert out["tracker_events"] == 2
    assert out["sources"][0]["identifier"] == detail_url
    assert out["sources"][0]["state"] == "changed"
    selected = registry.lista(stare, {"id": [out["sources"][0]["id"]]})["sources"][0]
    assert selected["snapshots"][0]["summary"]["title"] == "Proiect consultare publică"
    events = tracker_events.lista(
        stare, {"source_family": ["consultare_econsultare"], "limit": ["10"]}
    )
    assert events["total"] == 2
    assert {event["event_type"] for event in events["events"]} == {
        "public_consultation_announced",
        "public_consultation_opened",
    }
    assert all(event["project_id"] == detail_url for event in events["events"])

    again = registry.executa(stare, {"action": "discover_econsultare", "limit": 20})
    assert again["created"] == 0
    assert again["updated"] == 1
    assert again["sources"][0]["state"] == "unchanged"


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
    unavailable = registry.executa(stare, {"family": "ue_cellar", "identifier": "32019R0001"})
    registry.executa(stare, {"action": "queue", "id": unchanged["id"]})
    registry.executa(stare, {"action": "queue", "id": metadata["id"]})
    registry.executa(stare, {"action": "queue", "id": failure["id"]})
    registry.executa(stare, {"action": "queue", "id": unavailable["id"]})

    def import_celex(state, request):
        if request["celex"] == "32014L0024":
            write_eu_text(stare, request["celex"], "Text existent")
            return {"celex": request["celex"], "stare": "ok", "limba": "RON", "schimbat": False}
        if request["celex"] == "32018R1805":
            return {"celex": request["celex"], "stare": "metadate", "schimbat": False}
        if request["celex"] == "32019R0001":
            return {
                "celex": request["celex"],
                "stare": "indisponibil",
                "schimbat": False,
                "nota": "Cellar nu a returnat manifestari pentru limbile cerute.",
            }
        raise ValueError("Preluarea UE a esuat sau sursa depaseste limitele disponibile.")

    monkeypatch.setattr("scripts.achizitii_ue.importa", import_celex)

    unchanged_result = registry.executa(stare, {"action": "sync", "id": unchanged["id"]})
    metadata_result = registry.executa(stare, {"action": "sync", "id": metadata["id"]})
    assert unchanged_result["state"] == "unchanged"
    assert metadata_result["state"] == "needs_review"
    unavailable_result = registry.executa(stare, {"action": "sync", "id": unavailable["id"]})
    assert unavailable_result["state"] == "unavailable"
    assert unavailable_result["last_error"] == "language_unavailable"
    with registry._open(registry.cale(stare)) as con:
        note = con.execute(
            "SELECT note FROM source_attempts WHERE source_id=? AND state='unavailable'",
            (unavailable["id"],),
        ).fetchone()["note"]
    assert "limbile cerute" in note
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
        con.execute(
            "INSERT INTO initiativa_etapa"
            "(plx_id,ord,data,camera,actiune,comisii,steno_ids,steno_idm) "
            "VALUES ('plx-10-2026',1,'2026-01-15','Camera Deputaților',"
            "'înscris pe ordinea de zi a plenului',NULL,'1234','6')"
        )
        con.execute(
            "INSERT INTO initiativa_aviz(plx_id,de_la,data,sens,numar,primit) "
            "VALUES ('plx-10-2026','Consiliul Legislativ','2026-01-12','favorabil','8',1)"
        )
        con.execute(
            "INSERT INTO initiativa_vot"
            "(plx_id,data,camera,intrebare,pentru,contra,abtineri,rezultat,absenti,idv) "
            "VALUES ('plx-10-2026','2026-01-20','Camera Deputaților','adoptare',200,30,4,"
            "'adoptat',1,'99')"
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
        "opinion_received",
        "report_filed",
        "plenary_agenda",
        "vote_recorded",
    }
    assert events["events"][0]["source_id"] == row["id"]
    assert any(
        event["event_type"] == "vote_recorded"
        and event["payload"]["nominal_url"].endswith("Nominal?idv=99")
        for event in events["events"]
    )
    report = next(event for event in events["events"] if event["event_type"] == "report_filed")
    assert report["payload"]["documents"][0]["label"] == "Raport"
    assert report["payload"]["documents"][0]["url"] == "https://www.cdep.ro/proiecte/a.pdf"
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
    assert selected["snapshots"][0]["parliamentary_evidence"]["counts"]["reports"] == 1
    assert selected["snapshots"][0]["parliamentary_evidence"]["counts"]["votes"] == 1

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


def test_registry_syncs_ministry_consultation_metadata_to_tracker(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_minister",
            "identifier": "mdlap-consultare-1",
            "url": "https://www.mdlpa.ro/pages/proiect-hg-consultare",
            "label": "Consultare ministerială HG servicii publice",
        },
    )

    synced = registry.executa(
        stare,
        {
            "action": "sync",
            "id": row["id"],
            "metadata": {
                "title": "Proiect HG privind serviciile publice",
                "authority": "Ministerul Dezvoltării",
                "deadline": "15.10.2026",
                "status": "open",
                "project_id": "mdlap-consultare-1",
                "documents": [
                    {
                        "url": "https://www.mdlpa.ro/uploads/proiect.pdf",
                        "label": "Proiect act normativ",
                        "content_hash": "e" * 64,
                    }
                ],
                "tags": ["servicii publice"],
            },
        },
    )

    assert synced["state"] == "changed"
    assert synced["parser_version"] == registry.MANUAL_METADATA_PARSER_VERSION
    assert synced["sync_status"]["can_sync"] is True
    assert synced["tracker_sync"] == {
        "contract": "source-sync-tracker-events-v1",
        "stored": 2,
        "event_types": {
            "public_consultation_announced": 1,
            "public_consultation_opened": 1,
        },
    }
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["snapshots"][0]["summary"] == {
        "title": "Proiect HG privind serviciile publice",
        "authority": "Ministerul Dezvoltării",
        "status": "open",
        "deadline": "15.10.2026",
        "deadline_iso": "2026-10-15",
        "documents": 1,
        "document_metadata": {
            "total": 1,
            "by_type": {"pdf": 1},
            "with_hash": 1,
            "labels": ["Proiect act normativ"],
        },
        "truncated": False,
    }
    events = tracker_events.lista(stare, {"source_family": ["consultare_minister"]})
    assert events["total"] == 2
    by_type = {event["event_type"]: event for event in events["events"]}
    assert by_type["public_consultation_opened"]["project_id"] == "mdlap-consultare-1"
    assert by_type["public_consultation_opened"]["payload"]["attachment_hashes"] == ["e" * 64]
    assert by_type["public_consultation_opened"]["content_hash"] == synced["last_hash"]

    listed = registry.lista(stare)
    assert listed["counts"]["consultare_minister:changed"] == 1


def test_registry_ministry_consultation_missing_metadata_enters_review_queue(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_minister",
            "identifier": "minister-partial-1",
            "url": "https://www.mdlpa.ro/pages/consultare-partiala",
            "label": "Consultare ministerială incompletă",
        },
    )

    synced = registry.executa(
        stare,
        {
            "action": "sync",
            "id": row["id"],
            "metadata": {
                "title": "Proiect fără metadata completă",
                "project_id": "minister-partial-1",
            },
        },
    )

    assert synced["state"] == "needs_review"
    assert synced["tracker_sync"]["event_types"]["public_consultation_metadata_review"] == 1
    review_queue = tracker_events.lista(
        stare,
        {
            "source_family": ["consultare_minister"],
            "event_type": ["public_consultation_metadata_review"],
            "reviewed": ["0"],
        },
    )
    assert review_queue["total"] == 1
    assert review_queue["events"][0]["payload"]["missing"] == [
        "authority",
        "status",
        "deadline",
    ]


def test_registry_syncs_government_consultation_metadata_to_tracker(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_guvern",
            "identifier": "gov-consultare-1",
            "url": "https://sgg.gov.ro/1/transparenta-decizionala/proiect-hg-test/",
            "label": "Consultare Guvern HG servicii publice",
        },
    )

    synced = registry.executa(
        stare,
        {
            "action": "sync",
            "id": row["id"],
            "metadata": {
                "title": "Proiect HG privind serviciile publice",
                "authority": "Guvernul României",
                "deadline": "15.10.2026",
                "status": "open",
                "project_id": "gov-consultare-1",
                "documents": [
                    {
                        "url": "https://sgg.gov.ro/1/wp-content/uploads/proiect-hg.pdf",
                        "label": "Proiect hotărâre",
                        "content_hash": "f" * 64,
                    }
                ],
                "tags": ["guvern", "servicii publice"],
            },
        },
    )

    assert synced["state"] == "changed"
    assert synced["parser_version"] == registry.MANUAL_METADATA_PARSER_VERSION
    assert synced["tracker_sync"] == {
        "contract": "source-sync-tracker-events-v1",
        "stored": 2,
        "event_types": {
            "public_consultation_announced": 1,
            "public_consultation_opened": 1,
        },
    }
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["snapshots"][0]["summary"] == {
        "title": "Proiect HG privind serviciile publice",
        "authority": "Guvernul României",
        "status": "open",
        "deadline": "15.10.2026",
        "deadline_iso": "2026-10-15",
        "documents": 1,
        "document_metadata": {
            "total": 1,
            "by_type": {"pdf": 1},
            "with_hash": 1,
            "labels": ["Proiect hotărâre"],
        },
        "truncated": False,
    }
    events = tracker_events.lista(stare, {"source_family": ["consultare_guvern"]})
    assert events["total"] == 2
    by_type = {event["event_type"]: event for event in events["events"]}
    assert by_type["public_consultation_opened"]["project_id"] == "gov-consultare-1"
    assert by_type["public_consultation_opened"]["payload"]["authority"] == "Guvernul României"
    assert by_type["public_consultation_opened"]["payload"]["attachment_hashes"] == ["f" * 64]


def test_registry_discovers_government_consultation_metadata(tmp_path):
    stare = state(tmp_path)

    out = registry.executa(
        stare,
        {
            "action": "discover_guvern",
            "title": "Proiect HG privind serviciile publice",
            "url": "https://sgg.gov.ro/1/transparenta-decizionala/proiect-hg-test/",
            "project_id": "HG servicii publice",
            "deadline": "15.10.2026",
            "status": "open",
        },
    )

    assert out["contract"] == "source-registry-guvern-consultation-discovery-v1"
    assert out["tracker_events"] == 2
    assert out["source"]["family"] == "consultare_guvern"
    assert out["source"]["state"] == "changed"
    assert out["source"]["tracker_sync"]["event_types"] == {
        "public_consultation_announced": 1,
        "public_consultation_opened": 1,
    }
    events = tracker_events.lista(stare, {"source_family": ["consultare_guvern"]})
    assert events["total"] == 2
    assert all(event["project_id"] == "HG servicii publice" for event in events["events"])


def test_registry_discovers_government_consultation_rejects_non_sgg(tmp_path):
    stare = state(tmp_path)

    with pytest.raises(ValueError, match="sgg.gov.ro"):
        registry.executa(
            stare,
            {
                "action": "discover_guvern",
                "title": "Proiect HG",
                "url": "https://example.test/proiect-hg",
                "project_id": "HG 1",
            },
        )


def test_registry_syncs_avize_metadata_to_opinion_tracker_event(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "avize",
            "identifier": "aviz-cl-8-2026",
            "url": "https://www.clr.ro/avize/8-2026.pdf",
            "label": "Aviz Consiliul Legislativ",
        },
    )

    synced = registry.executa(
        stare,
        {
            "action": "sync",
            "id": row["id"],
            "metadata": {
                "project_id": "PL-x 10/2026",
                "issuer": "Consiliul Legislativ",
                "position": "favorabil cu observații",
                "observations": "Corelare terminologică necesară.",
                "document_hash": "f" * 64,
                "occurred_at": "2026-09-12",
            },
        },
    )

    assert synced["state"] == "changed"
    assert synced["tracker_sync"]["event_types"] == {"opinion_received": 1}
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["snapshots"][0]["summary"] == {
        "issuer": "Consiliul Legislativ",
        "position": "favorabil cu observații",
        "observations": True,
        "document_hash": "f" * 64,
        "documents": 0,
        "truncated": False,
    }
    events = tracker_events.lista(stare, {"source_family": ["avize"]})
    assert events["total"] == 1
    assert events["events"][0]["event_type"] == "opinion_received"
    assert events["events"][0]["project_id"] == "PL-x 10/2026"
    assert events["events"][0]["payload"]["issuer"] == "Consiliul Legislativ"
    assert events["events"][0]["payload"]["document_hash"] == "f" * 64


def test_registry_syncs_monitor_part_i_metadata_to_publication_tracker_event(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "monitorul_oficial_pi",
            "identifier": "lege-98-2016",
            "url": "https://monitoruloficial.ro/Monitorul-Oficial--PI--390--2016.html",
            "label": "Publicare Legea 98/2016",
        },
    )

    synced = registry.executa(
        stare,
        {
            "action": "sync",
            "id": row["id"],
            "metadata": {
                "title": "Legea 98/2016 publicată",
                "project_id": "lege-98-2016",
                "number": "390",
                "date": "2016-05-23",
                "part": "I",
            },
        },
    )

    assert synced["state"] == "changed"
    assert synced["parser_version"] == registry.MANUAL_METADATA_PARSER_VERSION
    assert synced["tracker_sync"]["event_types"] == {"published_in_monitor": 1}
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    summary = selected["snapshots"][0]["summary"]
    publication_reference = summary.pop("publication_reference")
    assert summary == {
        "title": "Legea 98/2016 publicată",
        "authority": "",
        "part": "I",
        "number": "390",
        "date": "2016-05-23",
        "documents": 0,
        "source_policy": "publication_tracker",
        "unsupported_full_text": False,
        "truncated": False,
    }
    assert publication_reference["contract"] == "monitor-publication-reference-v1"
    assert publication_reference["lifecycle_state"] == "published_monitor"
    assert publication_reference["status"] == "published_reference"
    assert publication_reference["full_text"]["state"] == "not_loaded"
    events = tracker_events.lista(stare, {"source_family": ["monitorul_oficial_pi"]})
    assert events["total"] == 1
    assert events["events"][0]["event_type"] == "published_in_monitor"
    assert events["events"][0]["project_id"] == "lege-98-2016"
    assert events["events"][0]["payload"]["number"] == 390
    assert events["events"][0]["payload"]["date"] == "2016-05-23"
    assert events["events"][0]["payload"]["lifecycle_state"] == "published_monitor"


def test_registry_syncs_monitor_local_metadata_without_tracker_event(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "monitorul_oficial_local",
            "identifier": "cluj-hcl-1-2026",
            "url": "https://www.mdlpa.ro/pages/monitoruloficiallocal",
        },
    )

    synced = registry.executa(
        stare,
        {
            "action": "sync",
            "id": row["id"],
            "metadata": {
                "title": "HCL locală",
                "project_id": "cluj-hcl-1-2026",
                "number": "12",
                "date": "2026-02-01",
            },
        },
    )

    assert synced["state"] == "changed"
    assert synced["tracker_sync"]["stored"] == 0
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    summary = selected["snapshots"][0]["summary"]
    assert summary["source_policy"] == "metadata_only_manual_document"
    assert summary["unsupported_full_text"] is True
    assert summary["publication_reference"]["contract"] == "monitor-publication-reference-v1"
    assert summary["publication_reference"]["lifecycle_state"] == "publication_reference_pending"
    assert summary["publication_reference"]["full_text"]["state"] == "manual_or_on_demand"


def test_registry_manual_metadata_needs_review_when_tracker_fields_are_missing(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "avize", "url": "https://example.test/aviz.pdf"})

    synced = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert synced["state"] == "needs_review"
    assert synced["tracker_sync"] == {
        "contract": "source-sync-tracker-events-v1",
        "stored": 0,
        "event_types": {},
    }
    assert synced["last_hash"]


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


def test_registry_lists_latest_source_change_contract(tmp_path):
    stare = state(tmp_path)
    row = registry.executa(stare, {"family": "consultare_econsultare", "identifier": "c1"})
    registry._store_snapshot(
        stare,
        row["id"],
        "a" * 64,
        {
            "contract": "econsultare-snapshot-v1",
            "summary": {"title": "Consultare", "deadline": "2026-09-20", "status": "open"},
            "documents": [{"url": "https://example.test/initial.pdf", "label": "Expunere"}],
        },
        "test.v1",
    )
    registry._store_snapshot(
        stare,
        row["id"],
        "b" * 64,
        {
            "contract": "econsultare-snapshot-v1",
            "summary": {"title": "Consultare", "deadline": "2026-09-25", "status": "closed"},
            "documents": [
                {"url": "https://example.test/initial.pdf", "label": "Expunere"},
                {"url": "https://example.test/raport.pdf", "label": "Raport final"},
            ],
        },
        "test.v1",
    )

    listed = registry.lista(stare, {"id": [row["id"]]})["sources"][0]

    assert listed["latest_change"]["contract"] == "source-change-detection-v1"
    assert [change["type"] for change in listed["latest_change"]["changes"]] == [
        "new_committee_report",
        "deadline_changed",
        "consultation_closed",
    ]
