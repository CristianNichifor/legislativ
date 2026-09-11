import csv
import json
from pathlib import Path

from scripts import acceptare_date_reale as acceptance
from scripts.dosare import LAW_WORKBENCH_ENGINE_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_real_data_acceptance_runs_workbench_without_synthetic_bridge(monkeypatch):
    calls = []

    def fake_request(_httpd, path="/api/date", body=None, *, timeout=1800):
        calls.append((path, body, timeout))
        if path.startswith("/api/fisa-act?"):
            return {"gasit": True, "act_id": "lege-98-2016"}
        if path == "/api/dosare/rulari" and body:
            return {
                "id": "rulare-real",
                "engine_version": LAW_WORKBENCH_ENGINE_VERSION,
                "raport": {
                    "referinte_ue": [
                        {"celex": "32014L0024", "mentionari": 2},
                        {"celex": "32018R1805", "mentionari": 1},
                    ],
                    "rand": {
                        "semnale": {
                            "viduri": 0,
                            "neconstitutionale": 0,
                            "initiative_in_lucru": 1,
                            "amendamente_primite": 2,
                        }
                    },
                },
            }
        if path.startswith("/api/dosare/revizuiri?"):
            return {"constatari": []}
        if path == "/api/ue/surse?celex=32014L0024":
            return {"celex": "32014L0024", "stare": "neimportat", "curenta": None}
        if path == "/api/ue/surse?celex=32018R1805":
            return {
                "celex": "32018R1805",
                "stare": "text_disponibil",
                "curenta": {"sursa": {"limba": "RON"}},
                "instantanee": [{"id": "1"}],
            }
        raise AssertionError((path, body))

    monkeypatch.setattr(acceptance, "request", fake_request)
    out = acceptance.pilot_workbench(
        object(),
        "b" * 32,
        search_results={"results": [{"act_id": "lege-98-2016"}]},
    )

    assert out["status"] == "passed"
    assert out["engine_version"] == LAW_WORKBENCH_ENGINE_VERSION
    assert out["signals"] == {
        "viduri": 0,
        "neconstitutionale": 0,
        "initiative_in_lucru": 1,
        "amendamente_primite": 2,
        "referinte_ue": 2,
    }
    assert out["eu_availability"] == {
        "total": 2,
        "text_importat": 1,
        "text_romanian": 1,
        "text_english": 0,
        "metadata_only": 0,
        "neimportate": 1,
        "referinte": [
            {
                "celex": "32014L0024",
                "mentionari": 2,
                "importat": False,
                "stare": "neimportat",
                "text_romanian": False,
                "text_english": False,
                "limba_text": None,
                "manifestari": 0,
                "instantanee": 0,
                "comanda_import": None,
            },
            {
                "celex": "32018R1805",
                "mentionari": 1,
                "importat": True,
                "stare": "text_disponibil",
                "text_romanian": True,
                "text_english": False,
                "limba_text": "RON",
                "manifestari": 0,
                "instantanee": 1,
                "comanda_import": None,
            },
        ],
    }
    assert out["reviewable_findings"] == 0
    assert out["finding_to_proposal"] == "not_exercised_no_authentic_gap_or_ccr_finding"
    assert calls[0][0] == "/api/fisa-act?act=lege-98-2016"
    assert calls[1][1] == {"dosar_id": "b" * 32, "filtre": {"act": "lege-98-2016"}}


def test_real_data_acceptance_reports_when_no_act_can_be_selected(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise AssertionError

    monkeypatch.setattr(acceptance, "request", fail_request)

    assert acceptance.pilot_workbench(object(), "b" * 32, search_results={"results": []}) == {
        "status": "skipped_no_search_act",
        "finding_to_proposal": "not_exercised_no_act",
    }


def test_checked_in_acceptance_record_matches_measurement_row():
    record = json.loads((ROOT / "docs/v1_acceptance_pilot_2026-09-11.json").read_text())
    rows = {
        row["case_id"]: row
        for row in csv.DictReader((ROOT / "data/v1_acceptance_measurements.csv").open())
    }
    workflow = rows["workflow-001"]
    eu_availability = rows["eu-availability-001"]

    assert record["acceptance_output"]["workbench"]["status"] == "passed"
    assert (
        record["acceptance_output"]["workbench"]["engine_version"] == LAW_WORKBENCH_ENGINE_VERSION
    )
    assert record["acceptance_output"]["dossier_survived_rollback"]
    assert record["acceptance_output"]["workbench"]["reviewable_findings"] == 0
    assert (
        record["acceptance_output"]["workbench"]["finding_to_proposal"]
        == "not_exercised_no_authentic_gap_or_ccr_finding"
    )
    assert workflow["source_sha256"] == record["release"]["manifest_sha256"]
    assert workflow["observed_count"] == "1"
    assert workflow["true_positive"] == "1"
    assert workflow["blocker"] == "no"
    assert record["acceptance_output"]["workbench"]["eu_availability"]["neimportate"] == 8
    assert eu_availability["source_sha256"] == record["release"]["manifest_sha256"]
    assert eu_availability["expected_count"] == "8"
    assert eu_availability["observed_count"] == "0"
    assert eu_availability["false_negative"] == "8"
    assert eu_availability["blocker"] == "yes"
