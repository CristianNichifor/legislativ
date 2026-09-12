import json
from pathlib import Path

from scripts import e2e_user_flows

ROOT = Path(__file__).resolve().parents[1]


def test_e2e_user_flows_report_current_finish_state():
    report = e2e_user_flows.run(ROOT)

    assert report["contract"] == "e2e-user-flows-v1"
    assert report["summary"] == {"ready": 4, "partial": 2, "missing": 0, "total": 6}
    assert {flow["key"] for flow in report["flows"]} >= {
        "public_to_local_workspace",
        "source_update_rollback",
        "dossier_note_proposal",
        "eu_risk_context",
        "law_as_code_review",
        "acceptance_dashboard",
    }
    assert report["status"] == "attention"


def test_e2e_user_flows_cli_json(capsys):
    assert e2e_user_flows.main(["--root", str(ROOT), "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["contract"] == "e2e-user-flows-v1"
    assert out["summary"]["missing"] == 0
