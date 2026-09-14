from __future__ import annotations

import json
import subprocess

from scripts import real_project_pilot


def test_real_project_pilot_runs_checked_in_public_source_flow(tmp_path):
    out = real_project_pilot.run(tmp_path)

    assert out["contract"] == "real-project-pilot-flow-v1"
    assert out["status"] == "passed"
    assert out["project_id"] == "PL-x 33/2025"
    assert all(out["checks"].values())
    assert out["summary"]["consultations"] >= 1
    assert out["summary"]["evidence_events"] >= 2


def test_real_project_pilot_cli_outputs_json(tmp_path):
    result = subprocess.run(
        [
            "python",
            "-m",
            "scripts.real_project_pilot",
            "--work-dir",
            str(tmp_path / "run"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    out = json.loads(result.stdout)

    assert out["contract"] == "real-project-pilot-flow-v1"
    assert out["status"] == "passed"
    assert out["checks"]["consultation_link_visible"] is True
