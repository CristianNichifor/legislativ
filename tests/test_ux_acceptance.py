from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import ux_acceptance


def write_fixture(root: Path, html: str, adapter: str | None = None) -> None:
    app = root / "app"
    app.mkdir()
    (app / "index.html").write_text(html, encoding="utf-8")
    if adapter is not None:
        (app / "civic-ui-adapter.css").write_text(adapter, encoding="utf-8")


def minimal_html(extra: str = "") -> str:
    return f"""<!doctype html>
<html lang="ro">
<head>
<link rel="stylesheet" href="vendor/civic-ui/styles.css">
<link rel="stylesheet" href="civic-ui-adapter.css">
</head>
<body class="civic-scope civic-legislativ">
<input id="q" class="civic-input">
<select id="f-tip" class="civic-select"></select>
<section id="legislative-workflow">
  <ol>
    <li data-workflow-step="source">Sursă</li>
    <li data-workflow-step="note">Notă</li>
    <li data-workflow-step="evidence">Dovezi</li>
    <li data-workflow-step="draft">Ciornă</li>
    <li data-workflow-step="export">Export</li>
  </ol>
  <button data-workflow-open-search>Caută sursă</button>
  <button data-workflow-open-matrix>Filtrează matricea</button>
  <button data-workflow-open-dossier>Dosar local</button>
  <button data-workflow-open-note>Notă gap/UE</button>
  <button data-workflow-open-draft>Ciornă amendament</button>
  <button data-workflow-open-export>Export</button>
</section>
<section>
  <h3>Acoperirea surselor</h3>
  <p>surse lipsă · surse parțiale · revizuibile · Calitate sursă · sursă necunoscută</p>
  <p>Ultima verificare salvată pentru fiecare rulare.</p>
</section>
<section>
  <p>AI/MCP este explicit: BYOK sau handoff aprobat.</p>
  <p>Cheile API rămân doar în sesiunea browserului. confirmare explicită necesară</p>
</section>
<section>
  <p>candidați, nu verdict juridic. Aplicabilitatea cere revizie umană și necesită jurist.</p>
</section>
{extra}
</body>
</html>"""


ADAPTER = """.civic-legislativ {
  --civic-bg: var(--paper);
  --civic-surface: var(--surface);
  --civic-text: var(--ink);
  --civic-action: var(--accent);
}"""


def kinds(data: dict) -> set[str]:
    return {item["kind"] for item in data["blockers"]}


def test_current_ui_reports_the_actual_checked_in_status():
    out = ux_acceptance.report()

    assert out["contract"] == "ux-acceptance-gate-v1"
    assert out["acceptance_allowed"] is True
    assert out["blockers"] == []
    assert out["status"] == "ready"
    assert out["warnings"] == []
    assert out["visible_in"]["inputs"] == ["app/index.html", "app/civic-ui-adapter.css"]


def test_missing_civic_adapter_blocks(tmp_path):
    write_fixture(tmp_path, minimal_html(), adapter=None)

    out = ux_acceptance.report(tmp_path)

    assert "missing_civic_ui_adapter" in kinds(out)
    assert out["acceptance_allowed"] is False


def test_internal_visible_wording_blocks(tmp_path):
    write_fixture(tmp_path, minimal_html("<p>Reload the cache after rebuild.</p>"), ADAPTER)

    out = ux_acceptance.report(tmp_path)

    blocker = next(item for item in out["blockers"] if item["kind"] == "internal_wording_visible")
    assert any("reload" in evidence.lower() for evidence in blocker["evidence"])
    assert any("cache" in evidence.lower() for evidence in blocker["evidence"])


def test_missing_source_and_ai_copy_block(tmp_path):
    html = minimal_html().replace("Acoperirea surselor", "Surse").replace("handoff aprobat", "")
    write_fixture(tmp_path, html, ADAPTER)

    out = ux_acceptance.report(tmp_path)

    assert "missing_source_status_explanations" in kinds(out)
    assert "missing_ai_mcp_approval_copy" in kinds(out)


def test_missing_no_verdict_and_workflow_anchors_block(tmp_path):
    html = (
        minimal_html()
        .replace("candidați, nu verdict juridic", "rezultate")
        .replace("data-workflow-open-export", "data-export")
    )
    write_fixture(tmp_path, html, ADAPTER)

    out = ux_acceptance.report(tmp_path)

    assert "missing_no_verdict_candidate_review_wording" in kinds(out)
    assert "missing_workflow_anchors" in kinds(out)


def test_require_complete_cli_exits_nonzero_for_blockers(tmp_path):
    write_fixture(tmp_path, minimal_html("<p>manifest shard index</p>"), ADAPTER)
    result = subprocess.run(
        ["python", "-m", "scripts.ux_acceptance", "--root", str(tmp_path), "--require-complete"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    out = json.loads(result.stdout)

    assert result.returncode == 2
    assert out["status"] == "blocked"
    assert "internal_wording_visible" in kinds(out)


def test_assert_complete_raises_with_blockers(tmp_path):
    write_fixture(tmp_path, minimal_html("<p>index rebuild</p>"), ADAPTER)
    out = ux_acceptance.report(tmp_path)

    with pytest.raises(ux_acceptance.UXAcceptanceError, match="internal_wording"):
        ux_acceptance.assert_complete(out)
