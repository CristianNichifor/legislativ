import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import evaluari_ai

FIXTURES = Path(__file__).parent / "fixtures" / "ai_eval"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_grounded_fixture_scores_above_loose_fixture():
    cases = _load("cases.json")
    good = evaluari_ai.evaluate_run(cases, _load("run_good.json"))
    bad = evaluari_ai.evaluate_run(cases, _load("run_bad.json"))

    assert good["engine_version"] == "ai-eval-deterministic-v1"
    assert good["criteria"] == list(evaluari_ai.CRITERIA)
    assert good["comparison"][0]["provider"] == "fixture"
    assert good["comparison"][0]["model"] == "grounded"
    assert good["comparison"][0]["overall"] >= 0.72
    assert bad["comparison"][0]["overall"] < good["comparison"][0]["overall"]
    assert bad["comparison"][0]["overall"] <= 0.45


def test_scores_cover_required_dimensions_and_notes():
    result = evaluari_ai.evaluate_run(_load("cases.json"), _load("run_bad.json"))
    first = result["results"][0]

    assert set(first["scores"]) == set(evaluari_ai.CRITERIA)
    assert first["scores"]["citation_correctness"] == 0.0
    assert first["scores"]["romanian_drafting_quality"] < 0.5
    assert first["scores"]["hallucinated_legal_claims"] < 0.8
    assert "Citari necunoscute" in " ".join(first["notes"]["citation_correctness"])
    assert any("nu apeleaza modele" in limit for limit in first["limits"])


def test_unknown_case_and_invalid_schema_are_rejected():
    cases = _load("cases.json")
    run = {
        "schema_version": 1,
        "run_id": "bad",
        "candidates": [{"case_id": "missing", "provider": "x", "model": "y", "output": "text"}],
    }
    with pytest.raises(ValueError, match="caz necunoscut"):
        evaluari_ai.evaluate_run(cases, run)

    with pytest.raises(ValueError, match="schema"):
        evaluari_ai.evaluate_run({"schema_version": 2, "cases": []}, run)


def test_cli_outputs_json_comparison():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.evaluari_ai",
            "--cases",
            str(FIXTURES / "cases.json"),
            "--run",
            str(FIXTURES / "run_good.json"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == 1
    assert payload["run_id"] == "fixture-good"
    assert len(payload["results"]) == 4
    assert payload["comparison"][0]["cases"] == 4


def test_schema_accepts_case_and_run_fixtures():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path("docs") / "ai_eval_schema1.json").read_text(encoding="utf-8"))

    jsonschema.validate(_load("cases.json"), schema)
    jsonschema.validate(_load("run_good.json"), schema)
