from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts import acoperire_surse, depozit, source_registry


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
    assert out["missing_required"] >= 1
    assert out["attention_sources"] == 1
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
    assert out["portfolio"]["storage_estimates"]["serious"]["gb_max"] == 630
    assert out["status"] == "blocked"


def test_source_coverage_handles_missing_stores_and_validates_stale_days(tmp_path):
    stare = state(tmp_path)
    out = acoperire_surse.raport(stare, now=datetime(2026, 9, 12, tzinfo=UTC))

    assert out["status"] == "blocked"
    assert out["projects"]["total"] == 0
    assert out["limitari"]

    with pytest.raises(ValueError, match="actualitate"):
        acoperire_surse.raport(stare, stale_days=0)
