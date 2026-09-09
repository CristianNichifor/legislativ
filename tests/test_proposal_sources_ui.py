import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_comparison_renderer_preserves_limits_and_escapes_source_text():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function proposalSourcesHtml", 1)[1]
        .split("function proposalAnalysisHtml", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const dossierTime=String;function proposalSourcesHtml"
        + source
        + r"""
const data={stare:'schimbat',revizie:1,verificat_la:'<script>',salvata:false,
  comparatie_incompleta:true,limitari:['<img>'],dependente:[{act_id:'<svg>',locator:'art1',
    tip:'analiza',stare:'schimbat',motiv:'<iframe>',inainte:'<script>',dupa:'<img>',
    diferente:['<svg>'],text_trunchiat:true,diferente_trunchiate:true,
    metadate_retinute:{url:'<script>'},metadate_schimbate:true}]};
const html=proposalSourcesHtml(data);
assert.ok(!/<(script|img|svg|iframe)>/.test(html));
for(const s of ['Surse schimbate','nesalvată','incompletă','fragment','trunchiate','Metadate'])
  assert.ok(html.includes(s));
data.stare='indisponibil';assert.ok(proposalSourcesHtml(data).includes('Comparație indisponibilă'));
data.stare='nesuportat';assert.ok(proposalSourcesHtml(data).includes('Comparație nesuportată'));
"""
    )
    result = subprocess.run(["node", "-e", code], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
