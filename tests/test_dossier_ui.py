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
        "const handle=()=>{" + handler + "handle();assert.equal(drafts.size,0);"
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
        "const draft=reviewEvidenceHtml({verificare:{stare:'schimbat'},"
        "dependente_verificate:[{salvat:{sursa:'proiect_importat',plx_id:'<script>'},"
        "stare:'schimbat',octeti_schimbati:true,text_schimbat:false}]});"
        "assert.ok(draft.includes('Document: schimbat'));"
        "assert.ok(draft.includes('Text extras: neschimbat'));"
        "assert.ok(draft.includes('data-draft-versions')&&!draft.includes('<script>'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_snapshot_renderer_escapes_text_provenance_and_labels_unknown():
    source = (
        APP.read_text()
        .split("function dossierEuSnapshotsHtml", 1)[1]
        .split("function dossierTime", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "function dossierEuSnapshotsHtml" + source + "assert.equal(dossierEuSnapshotsHtml({}), '');"
        "assert.ok(dossierEuSnapshotsHtml({dovezi:{referinte_ue:[{}]}}).includes('necapturate'));"
        "const run={dovezi:{surse_ue:{instantanee:[{celex:'<img>',stare:'capturat',id:'<svg>',"
        "sursa:{text:'<script>',limba:'ENG',titlu:'<iframe>',text_sha256:'abc'}}]}}};"
        "const html=dossierEuSnapshotsHtml(run);"
        "assert.ok(html.includes('Engleză · text alternativ'));"
        "assert.ok(html.includes('abc')&&html.includes('&lt;script&gt;'));"
        "assert.ok(!/<(img|svg|script|iframe)>/.test(html));"
        "run.dovezi.surse_ue.instantanee[0]={stare:'limita_depasita'};"
        "assert.ok(dossierEuSnapshotsHtml(run).includes('Limită de captură depășită'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_check_renderer_keeps_unknown_and_language_change_distinct():
    source = (
        APP.read_text()
        .split("function euCheckHtml", 1)[1]
        .split("function reviewEvidenceHtml", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "function euCheckHtml" + source + "assert.equal(euCheckHtml(null,false),'');"
        "assert.ok(euCheckHtml({},true).includes('fără verificare'));"
        "const h=euCheckHtml({surse_ue:{manifest_disponibil:true,comparatie_incompleta:true,"
        "surse:[{celex:'<img>',stare:'schimbat',limba_schimbata:true,text_schimbat:null,"
        "metadate_schimbate:false,salvat:{id:'<script>'}}]}},true);"
        "assert.ok(h.includes('Text: necomparabil')&&h.includes('Limbă: schimbat'));"
        "assert.ok(h.includes('Metadate: neschimbat')&&h.includes('Comparație incompletă'));"
        "assert.ok(!h.includes('<img>')&&!h.includes('<script>'));"
        "assert.ok(h.includes('nu este o comparație a sensului'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_queue_renderer_escapes_titles_and_separates_unchecked():
    source = (
        APP.read_text()
        .split("function euQueueRowHtml", 1)[1]
        .split("async function loadEuQueue", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const dossierTime=s=>s;function euQueueRowHtml"
        + source
        + "let row={titlu:'<script>',creat_la:'now',verificat:0};"
        "let h=euQueueRowHtml(row,0);assert.ok(h.includes('Fără verificare UE'));"
        "assert.ok(!h.includes('<script>')&&!h.includes('Texte schimbate: 0'));"
        "row={...row,verificat:1,texte:1,limbi:2,metadate:3,incomplet:1};"
        "h=euQueueRowHtml(row,0);assert.ok(h.includes('Texte schimbate: 1'));"
        "assert.ok(h.includes('Limbi schimbate: 2')&&h.includes('Doar metadate: 3'));"
        "assert.ok(h.includes('Comparație incompletă'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)
