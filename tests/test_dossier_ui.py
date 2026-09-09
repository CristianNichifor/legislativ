import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

APP = Path(__file__).parents[1] / "app/index.html"


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_cleared_review_draft_does_not_block_recalculation():
    handler = APP.read_text().split("form.oninput=()=>{", 1)[1].split("let retry=null;", 1)[0]
    code = (
        "const assert=require('node:assert/strict'), drafts=new Map(), form={};"
        "const f={id:'a',stare:'unreviewed'};"
        "let values={evaluator:'',motiv:'',stare:'unreviewed'};"
        "class FormData{constructor(){return Object.entries(values)}}"
        "const handle=()=>{"
        + handler
        + "handle();assert.equal(drafts.size,0);"
        "values.motiv='note';handle();assert.equal(drafts.size,1);"
        "values.motiv='';handle();assert.equal(drafts.size,0);"
        "values.stare='needs_evidence';handle();assert.equal(drafts.size,1);"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


def test_library_is_in_matrix_tab():
    class Placement(HTMLParser):
        def __init__(self):
            super().__init__()
            self.divs = []
            self.found = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "div":
                self.divs.append(attrs.get("id"))
            if attrs.get("id") == "dossier-library":
                assert "pane-matrice" in self.divs
                self.found = True

        def handle_endtag(self, tag):
            if tag == "div":
                self.divs.pop()

    parser = Placement()
    parser.feed(APP.read_text())
    assert parser.found


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_saved_run_provenance_is_escaped_and_labeled_historical():
    source = (
        APP.read_text()
        .split("function dossierSnapshotHtml", 1)[1]
        .split("async function openDossierRun", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const mDosarHtml=d=>d.markdown;function dossierSnapshotHtml"
        + source
        + "const h=dossierSnapshotHtml({creat_la:'<img>',engine_version:'<script>',"
        "sha256:'abc123',raport:{markdown:'saved report'}});"
        "assert.ok(h.includes('SHA-256 raport: abc123'));"
        "assert.ok(h.includes('Raport istoric, nu recalculare'));"
        "assert.ok(h.includes('sursa actuală'));"
        "assert.ok(h.includes('saved report'));"
        "assert.ok(!h.includes('<img>')&&!h.includes('<script>'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_review_form_escapes_evidence_and_history():
    source = (
        APP.read_text()
        .split("const REVIEW_STATES=", 1)[1]
        .split("async function loadFindingReviews", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const locRo=s=>s;const REVIEW_STATES="
        + source
        + "const h=reviewFindingHtml({id:'abc',tip:'lacuna',stare:'needs_evidence',revizie:1,"
        "dovada:{text:'<script>',act_id:'A',locator:'art1'},istoric_trunchiat:true,"
        "istoric:[{stare:'needs_evidence',revizie:1,evaluator:'<img>',motiv:'<svg>',creat_la:'now'}]});"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>')&&!h.includes('<svg>'));"
        "assert.ok(h.includes('Evenimente mai vechi'));"
        "assert.ok(h.includes('type=\"text\"'));"
        "assert.ok(h.includes('Confirmat de evaluator'));"
        "const evidence=reviewEvidenceHtml({verificare:{stare:'schimbat',"
        "comparatie_incompleta:true},dependente_verificate:[{salvat:'<script>',curent:'<img>'}]});"
        "assert.ok(evidence.includes('de reevaluat')&&evidence.includes('Comparație incompletă'));"
        "assert.ok(!evidence.includes('<script>')&&!evidence.includes('<img>'));"
        "assert.equal(reviewEvidenceHtml({}),'');"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)
