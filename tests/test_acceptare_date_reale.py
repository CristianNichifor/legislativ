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


def test_real_data_acceptance_three_source_dossier_handoff(monkeypatch):
    calls = []

    def fake_request(_httpd, path="/api/date", body=None, *, timeout=1800):
        calls.append((path, body, timeout))
        if path == "/api/dosare/watchlist" and body:
            return {"ok": True}
        if path.startswith("/api/dosare/revizuiri?"):
            return {
                "manifest_surse_dosar": {
                    "contract": "dossier-source-manifest-v1",
                    "total": 3,
                    "attention": 3,
                    "surse": [
                        {"tip": "project", "valoare": "PL-x 33/2025"},
                        {
                            "tip": "keyword",
                            "valoare": "https://e-consultare.gov.ro/Consultare-publica/test",
                        },
                        {"tip": "celex", "valoare": "32014L0024"},
                    ],
                    "limitari": ["local"],
                },
                "markdown": "# Revizuire\n\n# Surse urmărite în dosar",
            }
        raise AssertionError((path, body))

    monkeypatch.setattr(acceptance, "request", fake_request)

    out = acceptance.pilot_three_source_dossier(
        object(),
        "b" * 32,
        "run-1",
        project_id="PL-x 33/2025",
        consultation_url="https://e-consultare.gov.ro/Consultare-publica/test",
        celex="32014L0024",
    )

    assert out["status"] == "passed"
    assert out["contract"] == "dossier-source-manifest-v1"
    assert out["total"] == 3
    assert out["kinds"] == ["celex", "keyword", "project"]
    assert out["markdown_includes_sources"] is True
    assert [call[1]["tip"] for call in calls[:3]] == ["project", "keyword", "celex"]


def source_handoff(**patch):
    return {
        "status": "passed",
        "contract": "dossier-source-manifest-v1",
        "total": 3,
        "kinds": ["celex", "keyword", "project"],
        "rollback_survived": True,
        **patch,
    }


def test_real_data_acceptance_reports_when_no_act_can_be_selected(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise AssertionError

    monkeypatch.setattr(acceptance, "request", fail_request)

    assert acceptance.pilot_workbench(object(), "b" * 32, search_results={"results": []}) == {
        "status": "skipped_no_search_act",
        "finding_to_proposal": "not_exercised_no_act",
    }


def test_real_data_acceptance_v2_marks_current_pilot_gaps_as_attention():
    result = {
        "acte": 2,
        "search_results": 3,
        "dossier_survived_rollback": True,
        "workbench": {
            "status": "passed",
            "reviewable_findings": 0,
            "finding_to_proposal": "not_exercised_no_authentic_gap_or_ccr_finding",
            "proposal_candidate_id": None,
            "eu_availability": {
                "total": 8,
                "text_importat": 0,
                "text_romanian": 0,
                "text_english": 0,
                "neimportate": 8,
            },
        },
        "source_handoff": source_handoff(),
    }

    out = acceptance.v2_readiness(result)

    assert out["contract"] == "real-data-acceptance-v2"
    assert out["status"] == "attention"
    assert out["blocked"] == []
    assert out["attention"] == ["authentic_finding_to_proposal", "eu_text_available"]
    gates = {gate["key"]: gate for gate in out["gates"]}
    assert gates["runtime_path"]["status"] == "passed"
    assert gates["authentic_finding_to_proposal"]["required"] is False
    assert gates["eu_text_available"]["evidence"]["missing"] == 8


def test_real_data_acceptance_v2_blocks_when_release_gates_are_required():
    result = {
        "acte": 2,
        "search_results": 3,
        "dossier_survived_rollback": True,
        "workbench": {
            "status": "passed",
            "reviewable_findings": 0,
            "finding_to_proposal": "not_exercised_no_authentic_gap_or_ccr_finding",
            "eu_availability": {"total": 1, "text_importat": 0, "neimportate": 1},
        },
        "source_handoff": source_handoff(),
    }

    out = acceptance.v2_readiness(
        result,
        require_reviewable_finding=True,
        require_eu_text=True,
    )

    assert out["status"] == "blocked"
    assert out["blocked"] == ["authentic_finding_to_proposal", "eu_text_available"]
    assert all(
        gate["required"]
        for gate in out["gates"]
        if gate["key"] in {"authentic_finding_to_proposal", "eu_text_available"}
    )


def test_real_data_acceptance_v2_passes_when_real_evidence_is_available():
    result = {
        "acte": 4,
        "search_results": 3,
        "dossier_survived_rollback": True,
        "workbench": {
            "status": "passed",
            "reviewable_findings": 1,
            "finding_to_proposal": "eligible_real_finding_available",
            "proposal_candidate_id": "finding-1",
            "eu_availability": {
                "total": 1,
                "text_importat": 1,
                "text_romanian": 1,
                "text_english": 0,
                "neimportate": 0,
            },
        },
        "source_handoff": source_handoff(),
    }

    out = acceptance.v2_readiness(
        result,
        require_reviewable_finding=True,
        require_eu_text=True,
    )

    assert out["status"] == "passed"
    assert out["blocked"] == []
    assert out["attention"] == []


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
