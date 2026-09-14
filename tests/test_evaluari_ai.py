import json
import shutil
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
    assert good["comparison"][0]["overall"] >= 0.70
    assert good["comparison"][0]["accepted_cases"] >= 4
    assert bad["comparison"][0]["overall"] < good["comparison"][0]["overall"]
    assert bad["comparison"][0]["overall"] <= 0.45
    assert good["live_provider_calls"] is False
    assert good["server_calls_model"] is False
    assert good["stores_api_key"] is False


def test_scores_cover_required_dimensions_and_notes():
    result = evaluari_ai.evaluate_run(_load("cases.json"), _load("run_bad.json"))
    first = result["results"][0]

    assert set(first["scores"]) == set(evaluari_ai.CRITERIA)
    assert first["scores"]["citation_correctness"] == 0.0
    assert first["scores"]["structured_output_parseable"] < 0.75
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
    assert len(payload["results"]) == 5
    assert payload["comparison"][0]["cases"] == 5
    assert len(payload["task_summary"]) == 5
    assert {row["task_type"] for row in payload["task_summary"]} == {
        "issue_explanation",
        "amendment_drafting",
        "source_change_summary",
        "eu_risk_note",
        "rule_extraction",
    }


def test_rule_extraction_requires_parseable_json():
    result = evaluari_ai.evaluate_run(_load("cases.json"), _load("run_bad.json"))
    rule = next(row for row in result["results"] if row["task_type"] == "rule_extraction")

    assert rule["scores"]["structured_output_parseable"] == 0.0
    assert "JSON parsabil" in " ".join(rule["notes"]["structured_output_parseable"])
    assert not any(row["task_type"] == "rule_extraction" for row in result["acceptable_tasks"])


def test_byok_template_command_writes_secret_free_run(tmp_path):
    output = tmp_path / "byok-run.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.evaluari_ai",
            "--cases",
            str(FIXTURES / "cases.json"),
            "--write-byok-template",
            str(output),
            "--pretty",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert payload == written
    assert written["stores_api_key"] is False
    assert len(written["candidates"]) == 5
    assert "API" in written["candidates"][0]["output"]
    assert "SECRET" not in output.read_text(encoding="utf-8")


def test_schema_accepts_case_and_run_fixtures():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path("docs") / "ai_eval_schema1.json").read_text(encoding="utf-8"))

    jsonschema.validate(_load("cases.json"), schema)
    jsonschema.validate(_load("run_good.json"), schema)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_browser_ai_eval_report_summary_renders_safe_status():
    html = (Path("app") / "index.html").read_text(encoding="utf-8")
    source = html.split("function aiEvalReportSummaryHtml", 1)[1].split(
        "async function aiRescrieOnline", 1
    )[0]
    code = (
        "const assert=require('node:assert/strict');"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiEvalReportSummaryHtml"
        + source
        + "const html=aiEvalReportSummaryHtml({schema_version:1,stores_api_key:false,"
        "server_calls_model:false,live_provider_calls:false,"
        "comparison:[{provider:'<P>',model:'m',cases:5,overall:0.8,accepted_cases:4}],"
        "task_summary:[{task_type:'rule_extraction',provider:'p',model:'m',overall:0.82,"
        "acceptable:true}]});"
        "assert.ok(html.includes('data-ai-eval-report'));"
        "assert.ok(html.includes('rule_extraction'));"
        "assert.ok(html.includes('acceptabil'));"
        "assert.ok(html.includes('Chei API salvate: nu'));"
        "assert.ok(!html.includes('<P>'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True, timeout=10)
