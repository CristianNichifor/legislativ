from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts import acoperire_surse, depozit, documente_proiecte, source_registry


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", eu=tmp_path / "eu.db")


def test_source_coverage_reports_missing_attention_and_project_stage_quality(tmp_path):
    stare = state(tmp_path)
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 1/2026',2,'1','Lege','Etapă nouă',"
            "'2026-07-01T00:00:00+00:00','2026-07-01','https://www.cdep.ro/p1')"
        )
        con.commit()
    row = source_registry.executa(stare, {"family": "camera", "identifier": "PL-x 1/2026"})
    source_registry.executa(stare, {"action": "queue", "id": row["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "failed",
            "error_category": "fetch_failed",
        },
    )

    out = acoperire_surse.raport(stare, now=datetime(2026, 9, 12, tzinfo=UTC), stale_days=30)

    camera = next(row for row in out["families"] if row["family"] == "camera")
    assert camera["status"] == "attention"
    assert camera["attention"] == 1
    assert camera["failed"] == 1
    assert camera["fetched"] == 0
    assert camera["changed"] == 0
    assert camera["support"]["state"] == "supported"
    assert camera["support"]["label"] == "Suportată"
    assert camera["next_action"].startswith("Deschide rândurile eșuate")
    assert {action["key"] for action in camera["actions"]} >= {
        "add_source",
        "open_family",
        "sync_selected",
        "retry_failures",
        "create_note",
        "parser_details",
    }
    local_mo = next(row for row in out["families"] if row["family"] == "monitorul_oficial_local")
    assert local_mo["required"] is False
    assert local_mo["status"] == "missing"
    assert local_mo["support"]["state"] == "metadata_only"
    other_mo = next(
        row for row in out["families"] if row["family"] == "monitorul_oficial_other_parts"
    )
    assert other_mo["required"] is False
    assert other_mo["support"]["policy"].startswith("Părțile II-VII")
    assert out["missing_required"] >= 1
    assert out["attention_sources"] == 1
    assert out["unsynced_required"] == 0
    assert out["projects"]["total"] == 1
    assert out["projects"]["unknown"] == 1
    assert out["projects"]["stale"] == 1
    assert {b["kind"] for b in out["blockers"]} >= {
        "missing_family",
        "source_attention",
        "unknown_stage",
        "stale_project",
    }
    assert out["portfolio"]["contract"] == "source-portfolio-v1"
    assert out["portfolio"]["monitorul_oficial_policy"]["part_i"] == "ingest"
    families = {row["key"]: row for row in out["portfolio"]["families"]}
    assert families["consultare_econsultare"]["tier"] == "required"
    assert families["monitorul_oficial_pi"]["tier"] == "required"
    assert families["monitorul_oficial_local"]["tier"] == "deferred"
    assert families["camera"]["coverage_status"] == "attention"
    assert families["camera"]["tracked_sources"] == 1
    assert out["portfolio"]["storage_estimates"]["serious"]["gb_max"] == 665
    assert out["status"] == "blocked"


def test_source_coverage_exposes_parliamentary_document_evidence_counts(tmp_path):
    stare = state(tmp_path)
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 2/2026',2,'2','Lege','Raport depus',"
            "'2026-09-10T00:00:00+00:00','2026-09-01','https://www.cdep.ro/p2')"
        )
        con.commit()
    stare.documente_db = tmp_path / "documente.db"
    documente_proiecte.salveaza_linkuri(
        stare,
        "PL-x 2/2026",
        [
            {
                "url": "https://www.cdep.ro/proiecte/raport.pdf",
                "label": "Raport favorabil",
                "status": "available",
            },
            {"url": "", "label": "Aviz legacy", "status": "unavailable"},
        ],
        "https://www.cdep.ro/p2",
    )

    out = acoperire_surse.raport(stare, now=datetime(2026, 9, 12, tzinfo=UTC))

    camera = next(row for row in out["families"] if row["family"] == "camera")
    assert camera["parliamentary_evidence_counts"] == {
        "documents": 2,
        "reports": 1,
        "votes": 0,
        "avize": 1,
        "unavailable_documents": 1,
    }


def test_source_coverage_bootstrap_turns_missing_into_unsynced(tmp_path):
    stare = state(tmp_path)
    boot = source_registry.executa(stare, {"action": "bootstrap"})

    out = acoperire_surse.raport(stare, now=datetime(2026, 9, 12, tzinfo=UTC))

    assert boot["created"] == 14
    assert out["missing_required"] == 0
    assert out["unsynced_required"] == len(acoperire_surse.REQUIRED_FAMILIES)
    assert out["unsynced_sources"] == len(acoperire_surse.REQUIRED_FAMILIES)
    assert out["attention_sources"] == 0
    assert out["status"] == "blocked"
    assert {row["status"] for row in out["families"] if row["required"]} == {"unsynced"}
    assert {row["status"] for row in out["families"] if not row["required"]} == {"unsynced"}
    assert {row["next_action"] for row in out["families"] if row["required"]} == {
        "Sincronizează rânduri selectate până au stare locală verificată."
    }
    assert {blocker["kind"] for blocker in out["blockers"]} == {"source_unsynced"}


def test_source_coverage_accepts_verified_official_anchors(monkeypatch, tmp_path):
    stare = state(tmp_path)
    monkeypatch.setattr(
        source_registry,
        "_fetch_official_anchor",
        lambda url: {
            "http_status": 200,
            "content_hash": source_registry._stable_hash({"url": url}),
            "title": "Official source",
            "content_type": "text/html",
            "bytes": 64,
            "truncated": False,
            "error": "",
        },
    )

    synced = source_registry.executa(stare, {"action": "sync_bootstrap"})
    out = acoperire_surse.raport(stare, now=datetime(2026, 9, 12, tzinfo=UTC))

    assert synced["counts"] == {"unchanged": 14}
    assert out["missing_required"] == 0
    assert out["unsynced_required"] == 0
    assert out["attention_sources"] == 0
    assert {row["status"] for row in out["families"] if row["required"]} == {"ok"}
    assert {row["fetched"] for row in out["families"] if row["required"]} == {1}
    assert all(row["last_checked"] for row in out["families"] if row["required"])


def test_source_coverage_handles_missing_stores_and_validates_stale_days(tmp_path):
    stare = state(tmp_path)
    out = acoperire_surse.raport(stare, now=datetime(2026, 9, 12, tzinfo=UTC))

    assert out["status"] == "blocked"
    assert out["projects"]["total"] == 0
    assert out["limitari"]

    with pytest.raises(ValueError, match="actualitate"):
        acoperire_surse.raport(stare, stale_days=0)
