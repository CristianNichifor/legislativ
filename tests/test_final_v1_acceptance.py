import json
import subprocess

from scripts import final_v1_acceptance


def test_final_v1_acceptance_runs_one_vertical_flow(tmp_path):
    out = final_v1_acceptance.run(tmp_path)

    assert out["contract"] == "final-v1-vertical-acceptance-flow-v1"
    assert out["status"] == "passed"
    assert out["manifest"]["large_release_required"] is False
    assert out["project_id"] == "PL-x acceptance-procurement-001"
    assert all(out["checks"].values())
    assert out["summary"]["search_results"] >= 1
    assert out["summary"]["workbench_rows"] >= 2
    assert out["summary"]["matrix_entries"]["prevederi"] >= 1
    assert out["summary"]["evidence_events"] >= 2
    assert out["summary"]["evidence_notes"] == 1
    assert out["summary"]["mcp_timeline_events"] >= 2
    assert out["summary"]["draft_tokens"] > 0


def test_final_v1_acceptance_keeps_boundaries_explicit(tmp_path):
    out = final_v1_acceptance.run(tmp_path)

    text = json.dumps(out, ensure_ascii=False)
    assert "nu reconstruiește dataseturi" in text
    assert "serverul nu apelează modele" in text
    assert "textul UE real rămâne de importat" in text
    assert "Înlocuiește fixture-ul cu primul set mic de date reale adjudecat" in text


def test_final_v1_acceptance_cli_outputs_json(tmp_path):
    result = subprocess.run(
        [
            "python",
            "-m",
            "scripts.final_v1_acceptance",
            "--work-dir",
            str(tmp_path / "run"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    out = json.loads(result.stdout)

    assert out["contract"] == "final-v1-vertical-acceptance-flow-v1"
    assert out["status"] == "passed"
    assert out["checks"]["mcp_uses_same_project"] is True
