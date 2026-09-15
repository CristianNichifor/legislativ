import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

APP = Path(__file__).parents[1] / "app/index.html"


def run_node(code: str):
    return subprocess.run(
        ["node"], input=code, text=True, check=True, capture_output=True, timeout=10
    )


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_refresh_waits_for_pending_review_or_context_save():
    source = (
        APP.read_text()
        .split("async function loadFindingReviews(panel,dossierId,runId,token,checkId=null){", 1)[1]
        .split("const viewKey=", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const status={};const panel={querySelector:()=>status};"
        "function refresh(){" + source + "throw Error('Unexpected reload');}"
        "panel.reviewTransactions=new Map([['a',{saving:true}]]);refresh();"
        "assert.ok(status.textContent.includes('Salvare în curs'));"
        "panel.reviewTransactions.clear();"
        "panel.reviewDrafts=new Map([['context:a:a',{saving:true}]]);refresh();"
        "panel.reviewDrafts=new Map([['proposal:a',{saving:true}]]);refresh();"
        "panel.reviewDrafts.clear();assert.throws(refresh,/Unexpected reload/);"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_cleared_review_draft_does_not_block_recalculation():
    handler = (
        APP.read_text()
        .split("async function loadFindingReviews", 1)[1]
        .split("form.oninput=()=>{", 1)[1]
        .split("let retry=null;", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict'), drafts=new Map(), transactions=new Map();"
        "const form={querySelector:()=>({})},panel={querySelector:()=>({})},render=()=>{};"
        "const f={id:'a',stare:'unreviewed'};"
        "let values={evaluator:'',motiv:'',stare:'unreviewed'};"
        "class FormData{constructor(){return Object.entries(values)}}"
        "const handle=()=>{" + handler + "handle();assert.equal(drafts.size,0);"
        "values.motiv='note';handle();assert.equal(drafts.size,1);"
        "values.motiv='';handle();assert.equal(drafts.size,0);"
        "values.stare='needs_evidence';handle();assert.equal(drafts.size,1);"
    )
    run_node(code)


def test_saved_finding_review_exposes_manual_note_action():
    source = APP.read_text()
    assert "data-note-from-finding" in source
    assert "data-note-draft-from-finding" in source
    assert "Creează notă" in source
    assert "Notă + draft" in source


def test_mcp_runtime_surface_is_visible_in_ai_panel():
    source = APP.read_text()
    assert "function mcpRuntimePanelHtml" in source
    assert "data-mcp-runtime-surface" in source
    assert "data-mcp-discover" in source
    assert "data-mcp-test" in source
    assert "api('/api/mcp/runtime')" in source
    assert "dossierApi('/api/mcp/test'" in source
    assert "data-mcp-execute" in source
    assert "data-mcp-export" in source
    assert "/api/dosare/mcp-export-preview" in source
    assert "/api/dosare/mcp-export-execute" in source
    assert "payload preview obligatoriu" in source
    assert "aplicația rămâne utilizabilă fără MCP" in source
    assert "Nu există transfer ascuns" in source


def test_provision_detail_panels_expose_identity_metadata():
    source = APP.read_text()
    assert "function provisionIdentityMeta" in source
    assert "provision-identity-v1" in source
    assert "provision-id-meta" in source
    assert "provisionIdentityMeta(d)" in source


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


def test_matrix_tab_exposes_daily_legislative_workflow():
    source = APP.read_text()
    assert 'id="legislative-workflow"' in source
    assert "Flux zilnic pentru lacune și contradicții" in source
    assert 'class="daily-workflow-status"' in source
    assert 'data-workflow-step="source"' in source
    assert 'data-workflow-step="evidence"' in source
    assert "ieșire: URL + identificator" in source
    assert "ieșire: Markdown/JSON" in source
    assert "data-workflow-open-search" in source
    assert "data-workflow-open-note" in source
    assert "data-workflow-open-draft" in source
    assert "data-workflow-open-export" in source
    assert "dosar + note" in source
    assert "dovezi și semnale" in source
    assert 'id="m-workspace"' in source
    assert 'id="m-review-state"' in source
    assert 'id="m-source-family"' in source
    assert 'id="m-lifecycle-state"' in source
    assert "Spațiu de lucru matrice" in source
    assert "candidați, nu verdict juridic" in source


def test_matrix_is_default_product_workspace():
    source = APP.read_text()
    assert 'id="tab-start" role="tab" aria-selected="false"' in source
    assert 'id="tab-matrice" role="tab" aria-selected="true"' in source
    assert 'data-main-nav="start" aria-current="false"' in source
    assert 'data-main-nav="matrix" aria-current="true"' in source
    assert 'id="pane-start" role="tabpanel" aria-labelledby="tab-start" hidden' in source
    assert 'id="pane-matrice" role="tabpanel" aria-labelledby="tab-matrice">' in source
    assert '$(".app").dataset.pane = "matrice";' in source
    assert 'selectTab("matrice");' in source


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_daily_workflow_buttons_open_existing_panels():
    source = APP.read_text().split("function bindDailyWorkflow", 1)[1].split("// ---- theme:", 1)[0]
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "const buttons=new Map();"
        "const steps=['source','note','evidence','draft','export'].map(step=>({"
        "dataset:{workflowStep:step},"
        "classList:{active:false,toggle(cls,on){if(cls==='current')this.active=on;}}}));"
        "const root={querySelector:s=>buttons.get(s),"
        "querySelectorAll:s=>s==='[data-workflow-step]'?steps:[]};"
        "for(const key of ['search','matrix','dossier','note','draft','export'])"
        "{buttons.set('[data-workflow-open-'+key+']',{onclick:null});}"
        "const status={},q={focus:()=>calls.push(['focus','q'])},"
        "m={focus:()=>calls.push(['focus','m'])};"
        "const dossier={open:false,scrollIntoView:o=>calls.push(['scroll','dossier',o.block])};"
        "const saved={textContent:'saved',"
        "scrollIntoView:o=>calls.push(['scroll','saved',o.block])};"
        "const proposals={scrollIntoView:o=>calls.push(['scroll','proposals',o.block])};"
        "const notes={scrollIntoView:o=>calls.push(['scroll','notes',o.block])};"
        "const dossierStatus={textContent:''};"
        "const nodes={'#legislative-workflow':root,'#legislative-workflow-status':status,"
        "'#q':q,'#m-q':m,'#dossier-library':dossier,'#dossier-saved':saved,"
        "'#dossier-proposals':proposals,'#dossier-notes':notes,'#dossier-status':dossierStatus};"
        "function $(sel){return nodes[sel]||null;}"
        "function selectTab(tab){calls.push(['tab',tab]);}"
        "let DOSARE_UI={selected:null};"
        "const MANUAL_NOTES_UI={editing:'kept'};"
        "function loadManualNotes(){calls.push(['notes-loaded']);}"
        "function bindDailyWorkflow"
        + source
        + "assert.equal(steps.find(s=>s.dataset.workflowStep==='source').classList.active,true);"
        + "buttons.get('[data-workflow-open-search]').onclick();"
        "assert.deepEqual(calls.slice(-2),[['tab','cauta'],['focus','q']]);"
        "assert.ok(status.textContent.includes('sursa oficială'));"
        "buttons.get('[data-workflow-open-matrix]').onclick();"
        "assert.deepEqual(calls.slice(-2),[['tab','matrice'],['focus','m']]);"
        "buttons.get('[data-workflow-open-note]').onclick();"
        "assert.equal(dossier.open,true);"
        "assert.equal(steps.find(s=>s.dataset.workflowStep==='note').classList.active,true);"
        "assert.ok(dossierStatus.textContent.includes('Alege sau creează'));"
        "DOSARE_UI={selected:{id:'d1'}};buttons.get('[data-workflow-open-note]').onclick();"
        "assert.equal(MANUAL_NOTES_UI.editing,null);"
        "assert.ok(calls.some(c=>c[0]==='notes-loaded'));"
        "buttons.get('[data-workflow-open-draft]').onclick();"
        "assert.equal(steps.find(s=>s.dataset.workflowStep==='draft').classList.active,true);"
        "buttons.get('[data-workflow-open-export]').onclick();"
        "assert.equal(steps.find(s=>s.dataset.workflowStep==='export').classList.active,true);"
        "assert.deepEqual(calls.slice(-1),[['scroll','saved','start']]);"
    )
    run_node(code)


def test_first_run_navigation_is_top_level_and_stateful():
    source = APP.read_text()
    assert 'id="tab-start"' in source
    assert 'id="pane-start"' in source
    assert 'data-main-nav="track"' in source
    assert 'data-main-nav="dossiers"' in source
    assert 'data-main-nav="ai"' in source
    assert 'data-main-nav="rules"' in source
    assert 'data-main-nav="status"' in source
    assert "Navigare spații de lucru" in source
    assert "Surse<small>lege, proiect, consultare, CELEX</small>" in source
    assert "Urmărire<small>stadii, comisii, avize, voturi</small>" in source
    assert "Dovezi exacte" in source
    assert "Revizie umană" in source
    assert "Pornește o analiză legislativă" in source
    assert "Aplicația nu dă verdict juridic" in source
    assert "Datele publice și dosarele private sunt separate" in source
    assert "function openWorkflowTarget" in source
    assert 'id="ai-product-flow"' in source
    assert "data-ai-product-flow" in source
    assert "Fără chei salvate/exportate" in source
    assert "Cost server zero" in source
    assert "ciornă nerevizuită, nu verdict juridic" in source
    assert "data-ai-open-matrix-evidence" in source
    assert "data-ai-open-dossier-writing" in source
    assert "data-ai-open-mcp-runtime" in source
    assert "function bindAiProductFlow" in source
    assert "function explainDisabledControls" in source
    assert 'id="main-flow-strip"' in source
    assert "Flux principal" in source
    assert 'data-flow-target="matrix"' in source
    assert 'data-flow-target="evidence"' in source
    assert 'data-flow-target="dossier"' in source
    assert 'data-flow-target="writing"' in source
    assert 'data-flow-target="proposal"' in source
    assert 'data-flow-target="export"' in source
    assert "Matrice -> dovezi -> dosar -> redactare -> propunere -> export" in source


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_main_flow_strip_routes_existing_workspaces_and_context():
    source = (
        APP.read_text()
        .split("const MAIN_FLOW_LABELS", 1)[1]
        .split("document.querySelectorAll('[data-main-nav]')", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "const buttons=['matrix','evidence','dossier','writing','proposal','export'].map(target=>({"
        "dataset:{flowTarget:target},onclick:null,state:'',current:'',"
        "setAttribute(k,v){if(k==='aria-current')this.current=v;}}));"
        "const root={querySelectorAll:s=>s==='[data-flow-target]'?buttons:[]};"
        "const status={textContent:''};"
        "const panels={'#main-flow-context':status,'#m-q':{focus:()=>calls.push(['focus','m-q'])},"
        "'#m-detalii':{scrollIntoView:o=>calls.push(['scroll','m-detalii',o.block])},"
        "'#dossier-writing':{scrollIntoView:o=>calls.push(['scroll','writing',o.block])},"
        "'#dossier-saved':{textContent:'',scrollIntoView:o=>calls.push(['scroll','saved',o.block])},"
        "'#dossier-proposals':{scrollIntoView:o=>calls.push(['scroll','proposals',o.block])}};"
        "function $(sel){return panels[sel]||null;}"
        "const document={getElementById:id=>id==='main-flow-strip'?root:null};"
        "let DOSARE_UI={selected:null,runId:''};"
        "function currentProposalFindingId(){return DOSARE_UI.finding||'';}"
        "function selectTab(tab){calls.push(['tab',tab]);}"
        "function openWorkflowTarget(target){calls.push(['workflow',target]);}"
        "const MAIN_FLOW_LABELS" + source + "bindMainFlowStrip();"
        "assert.equal(buttons.find(b=>b.dataset.flowTarget==='matrix').current,'true');"
        "assert.equal(buttons.find(b=>b.dataset.flowTarget==='writing').dataset.state,'pending');"
        "buttons.find(b=>b.dataset.flowTarget==='evidence').onclick();"
        "assert.deepEqual(calls.slice(-2),[['tab','matrice'],['scroll','m-detalii','start']]);"
        "buttons.find(b=>b.dataset.flowTarget==='writing').onclick();"
        "assert.ok(status.textContent.includes('Alege sau creează'));"
        "DOSARE_UI={selected:{id:'d1',titlu:'Dosar X'},runId:'r1',finding:'f1'};"
        "panels['#dossier-saved'].textContent='saved';"
        "buttons.find(b=>b.dataset.flowTarget==='proposal').onclick();"
        "assert.deepEqual(calls.slice(-2),[['workflow','dossiers'],['scroll','saved','start']]);"
        "assert.ok(status.textContent.includes('Editorul de propuneri'));"
        "buttons.find(b=>b.dataset.flowTarget==='export').onclick();"
        "assert.deepEqual(calls.slice(-2),[['workflow','dossiers'],['scroll','saved','start']]);"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_first_run_shortcuts_reuse_existing_panels_without_duplicate_forms():
    source = (
        APP.read_text()
        .split("function setFirstRunStatus", 1)[1]
        .split("function realWorkflowUrl", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "const navTargets=['start','search','track','matrix','dossiers','ai','rules','status'];"
        "const navs=navTargets.map(target=>({dataset:{mainNav:target},current:'',onclick:null,"
        "setAttribute(k,v){if(k==='aria-current')this.current=v;}}));"
        "const startTargets=['source','dossier','matrix','draft'];"
        "const startActions=startTargets.map(action=>({dataset:{startAction:action},"
        "onclick:null}));"
        "const panels={};"
        "const panelIds=['lifecycle-tracker','dossier-library','source-registry',"
        "'source-coverage','ai-product-flow'];"
        "for(const id of panelIds)"
        "panels['#'+id]={open:false,scrollIntoView:o=>calls.push(['scroll',id,o.block])};"
        "panels['#lifecycle-search']={scrollIntoView:o=>calls.push(['scroll','lifecycle-search',o.block])};"
        "panels['#source-title']={scrollIntoView:o=>calls.push(['scroll','source-title',o.block])};"
        "panels['#m-q']={focus:()=>calls.push(['focus','m-q'])};"
        "panels['#ai-mode']={focus:()=>calls.push(['focus','ai-mode'])};"
        "panels['#first-run-status']={textContent:''};"
        "function $(sel){return panels[sel]||{setAttribute(){},"
        "focus(){calls.push(['focus',sel]);}};}"
        "function selectTab(tab){calls.push(['tab',tab]);}"
        "const document={querySelectorAll(sel){if(sel==='[data-main-nav]')return navs;"
        "if(sel==='[data-start-action]')return startActions;"
        "if(sel==='button:disabled')return [];return [];}};"
        "function setFirstRunStatus" + source + "openWorkflowTarget('track');"
        "assert.equal(panels['#lifecycle-tracker'].open,true);"
        "assert.deepEqual(calls.slice(0,2),[['tab','matrice'],['scroll','lifecycle-search','start']]);"
        "assert.equal(navs.find(n=>n.dataset.mainNav==='track').current,'true');"
        "openWorkflowTarget('dossiers');assert.equal(panels['#dossier-library'].open,true);"
        "openWorkflowTarget('rules');assert.equal(panels['#dossier-library'].open,true);"
        "assert.ok(panels['#first-run-status'].textContent.includes('law-as-code'));"
        "openWorkflowTarget('status');assert.equal(panels['#source-registry'].open,true);"
        "assert.equal(panels['#source-coverage'].open,true);"
        "openWorkflowTarget('ai');assert.deepEqual(calls.slice(-3),[['tab','matrice'],['scroll','ai-product-flow','start'],['focus','m-q']]);"
        "assert.ok(panels['#first-run-status'].textContent.includes('ciorne nerevizuite'));"
        "startActions.find(b=>b.dataset.startAction==='source').onclick();"
        "assert.deepEqual(calls.slice(-1),[['tab','cauta']]);"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_product_flow_routes_to_existing_matrix_dossier_and_mcp_surfaces():
    source = APP.read_text().split("function bindAiProductFlow", 1)[1].split("// ---- theme:", 1)[0]
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "let DOSARE_UI={selected:null};"
        "const buttons=new Map();"
        "const root={querySelector(sel){return buttons.get(sel);}};"
        "['[data-ai-open-matrix-evidence]','[data-ai-open-dossier-writing]',"
        "'[data-ai-open-mcp-runtime]'].forEach(sel=>buttons.set(sel,{onclick:null}));"
        "const mcp={scrollIntoView:o=>calls.push(['scroll','mcp',o.block])};"
        "const dossier={open:false,scrollIntoView:o=>calls.push(['scroll','dossier',o.block]),"
        "querySelector:sel=>sel==='[data-mcp-runtime-surface]'?mcp:null};"
        "const panels={'#ai-product-flow':root,'#ai-product-flow-status':{textContent:''},"
        "'#m-q':{focus:()=>calls.push(['focus','m-q'])},'#dossier-library':dossier,"
        "'#dossier-status':{textContent:''},'#dossier-writing':{scrollIntoView:o=>calls.push(['scroll','writing',o.block])}};"
        "function $(sel){return panels[sel]||null;}"
        "function selectTab(tab){calls.push(['tab',tab]);}"
        "function bindAiProductFlow"
        + source
        + "buttons.get('[data-ai-open-matrix-evidence]').onclick();"
        "assert.deepEqual(calls.slice(-2),[['tab','matrice'],['focus','m-q']]);"
        "assert.ok(panels['#ai-product-flow-status'].textContent.includes('AI din dovadă'));"
        "buttons.get('[data-ai-open-dossier-writing]').onclick();"
        "assert.equal(dossier.open,true);"
        "assert.ok(panels['#dossier-status'].textContent.includes('Alege sau creează'));"
        "DOSARE_UI={selected:{id:'d1'}};buttons.get('[data-ai-open-dossier-writing]').onclick();"
        "assert.deepEqual(calls.slice(-1),[['scroll','writing','start']]);"
        "buttons.get('[data-ai-open-mcp-runtime]').onclick();"
        "assert.deepEqual(calls.slice(-1),[['scroll','mcp','start']]);"
        "assert.ok(panels['#ai-product-flow-status'].textContent.includes('aprobare explicită'));"
    )
    run_node(code)


def test_disabled_controls_explain_why_actions_are_unavailable():
    source = APP.read_text()
    assert (
        'data-disabled-reason="Exportul devine disponibil după încărcarea inventarului de surse."'
        in source
    )
    assert 'data-disabled-reason="Încarcă stadiile înainte de paginare."' in source
    assert 'data-disabled-reason="Nu există pagină anterioară de dosare."' in source


def test_dossier_creation_surfaces_source_freshness_warning():
    source = APP.read_text()
    assert 'id="dossier-source-warning"' in source
    assert "renderDossierSourceFreshness" in source
    assert "sourceFreshnessStatus" in source


def test_workflow_empty_states_point_to_next_action():
    source = APP.read_text()
    assert "function workflowEmptyState" in source
    assert "data-workflow-empty-state" in source
    assert "Niciun rând în matrice" in source
    assert "Șterge căutarea, schimbă aria/rangul" in source
    assert "Nicio analiză salvată" in source
    assert "Rulează analiza pe dosar" in source
    assert "Pachet de dovezi neîncărcat" in source
    assert "Încarcă context proiect" in source
    assert "Nicio sursă urmărită" in source
    assert "Adaugă sursele oficiale de bază" in source
    assert "Nicio inițiativă locală" in source


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
        "sha256:'abc123',raport:{markdown:'saved report',limitari:['limit <x>']},"
        "dovezi:{surse_ue:{instantanee:[{stare:'capturat',celex:'32014L0024',sursa:{limba:'RON',titlu:'T',citit_la:'now',data_document:'2026',text_sha256:'h',text:'text'}}]}}});"
        "assert.ok(h.includes('SHA-256 raport: abc123'));"
        "assert.ok(h.includes('Raport istoric, nu recalculare'));"
        "assert.ok(h.includes('data-saved-run-export-readiness'));"
        "assert.ok(h.includes('Pregătire export raport · gata'));"
        "assert.ok(h.includes('Surse UE<br><b>1</b>'));"
        "assert.ok(h.includes('Limitări<br><b>1</b>'));"
        "assert.ok(h.includes('Poți copia sau tipări raportul salvat.'));"
        "assert.ok(h.includes('sursa actuală'));"
        "assert.ok(h.includes('saved report'));"
        "assert.ok(!h.includes('<img>')&&!h.includes('<script>'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_law_workbench_shows_eu_availability_and_import_action():
    source = (
        APP.read_text()
        .split("function fisaActHtml", 1)[1]
        .split("async function comutaFisaAct", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const nf=n=>String(n);const mActiuni=()=>'';function fisaActHtml"
        + source
        + "const html=fisaActHtml({gasit:true,act_id:'lege-98-2016',titlu:'Lege',"
        "viduri:[],neconstitutionale:[],initiative:[],pasi:[],limitari:[],"
        "referinte_ue:[{celex:'32014L0024',importat:false,mentionari:2,"
        "comanda_import:'python -m scripts.achizitii_ue 32014L0024'},"
        "{celex:'32018R1805',importat:true,mentionari:1}]});"
        "assert.ok(html.includes('<b>2</b> referințe UE'));"
        "assert.ok(html.includes('<b>1</b> cu text local'));"
        "assert.ok(html.includes('<b>1</b> de importat'));"
        "assert.ok(html.includes('referințe UE fără text local'));"
        "assert.ok(html.includes('lipsește din eu.db'));"
        "assert.ok(html.includes('text local disponibil'));"
        "assert.ok(html.includes('python -m scripts.achizitii_ue 32014L0024'));"
    )
    result = run_node(code)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_manual_note_renderer_and_payload_escape_user_content():
    source = (
        APP.read_text()
        .split("const MANUAL_NOTE_TYPES=", 1)[1]
        .split("async function loadProposalList", 1)[0]
    )
    code = (
        r"""
const assert=require('node:assert/strict');
const escapes={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc=s=>(s==null?'':String(s)).replace(/[&<>"']/g,c=>escapes[c]);
const dossierTime=s=>s;
const crypto={randomUUID:()=>"11111111-2222-4333-8444-555555555555"};
function aiUnifiedDraftPanelHtml(label){
  return '<details data-unified-ai-draft>'+label+'</details>';
}
const MANUAL_NOTE_TYPES="""
        + source
        + r"""
const note={id:'abc',title:'<script>',type:'contradictie',status:'ready_for_review',
  revizie:2,modificat_la:'now',act_id:'Lege <img>',locator:'art. 1',
  source_url:'https://example.test/?q=<svg>',source_hash:'a'.repeat(64),
  evidence_quote:'quote <b>',reasoning:'reason <i>'};
const h=manualNoteHtml(note,0);
assert.ok(h.includes('Contradicție')&&h.includes('Gata pentru auto-revizie'));
assert.ok(h.includes('SHA-256 sursă')&&h.includes('Citat dovadă'));
assert.ok(h.includes('data-copy-note-export')&&h.includes('data-download-note-export'));
assert.ok(!/<(script|img|svg|b|i)>/.test(h));
const euNote={...note,type:'risc_ue',
  export_markdown:'# Conflict posibil\n\n> citat exact\n\nNu este verdict juridic.\n'};
assert.equal(manualNoteExportMarkdown(euNote),euNote.export_markdown);
assert.ok(manualNoteHtml(euNote,1).includes('Exportă nota UE'));
assert.equal(manualNoteFilename({title:'Notă UE / Art. 1'}),'nota-ue-art.-1.md');
const formHtml=manualNoteFormHtml(note);
assert.ok(formHtml.includes('Editezi nota')&&!formHtml.includes('<script>'));
const prefill=manualNoteFromFinding({tip:'contradictie',dovada:{
  a:{act_id:'A',locator:'art. 1',text:'A text'},
  b:{act_id:'B',locator:'art. 2',definitie:'B text'},
  motiv:'conflict'}});
assert.equal(prefill.type,'contradictie');
assert.equal(prefill.act_id,'A');
assert.equal(prefill.locator,'art. 1');
assert.equal(prefill.status,'ready_for_review');
assert.ok(prefill.evidence_quote.includes('A text'));
assert.ok(prefill.evidence_quote.includes('B text'));
assert.ok(manualNoteFormHtml(prefill).includes('Notă precompletată din constatare'));
assert.ok(manualNoteFormHtml(prefill).includes('Checklist auto-revizie'));
const summary=manualNoteSummaryHtml({
  pe_stare:{draft:1,ready_for_review:2},
  pe_tip:{lacuna:1,contradictie:2},
  recente:[note]});
assert.ok(summary.includes('Total')&&summary.includes('data-note-summary-status="ready_for_review"'));
assert.ok(summary.includes('Lacună: 1')&&summary.includes('Ultimele note modificate'));
const matrix=manualNoteFromMatrix('ue',{
  celex:'32014L0024',importat:false,
  exemple:[{id:'A',locator:'art. 1',fragment:'frag'}]});
assert.equal(matrix.type,'risc_ue');
assert.equal(matrix.status,'needs_evidence');
assert.ok(matrix.evidence_quote.includes('frag'));
const lacuna=manualNoteFromMatrix('lacuna',{
  act_id:'lege-1',locator:'art. 2',text:'missing',instrument:'hotărâre',
  sursa_url:'https://source.test/lege-1',sha256:'c'.repeat(64)});
assert.equal(lacuna.type,'lacuna');
assert.ok(lacuna.reasoning.includes('hotărâre'));
const contextual=manualNoteFromMatrix('lacuna',{
  act_id:'lege-2',locator:'art. 5',text:'missing rule',instrument:'ordin'},{
  drilldown:{
    workspace:{contract:'law-matrix-workspace-row-v1',stage:'gata de lucru juridic',
      primary_problem:{eticheta:'Lacună normativă'},source_state:{eticheta:'sursă verificată'},
      evidence_counts:{prevederi:2,surse:1,proiecte:1,referinte_ue:1},
      next_actions:['Confirmă citatul exact','Pornește draftul'],not_legal_verdict:true},
    readiness:{drilldown_pointers:{sources:[{act_id:'lege-2',
      url:'https://source.test/lege-2',content_hash:'d'.repeat(64)}]}}}});
assert.equal(contextual.source_url,'https://source.test/lege-2');
assert.equal(contextual.source_hash,'d'.repeat(64));
assert.ok(contextual.reasoning.includes('law-matrix-workspace-row-v1'));
assert.ok(contextual.reasoning.includes('Confirmă citatul exact'));
assert.ok(contextual.reasoning.includes('Nu este verdict juridic'));
const values={title:'Titlu',type:'lacuna',act_id:'A',locator:'art1',
  evidence_quote:'citat',source_url:'https://x.test',source_hash:'b'.repeat(64),
  reasoning:'motiv',status:'draft'};
class FormData{constructor(){return Object.entries(values)}}
assert.deepEqual(manualNotePayload({},'dossier',null),{
  id:'11111111222243338444555555555555',dosar_id:'dossier',revizie:0,title:'Titlu',
  type:'lacuna',act_id:'A',locator:'art1',evidence_quote:'citat',
  source_url:'https://x.test',source_hash:'b'.repeat(64),reasoning:'motiv',status:'draft'});
assert.deepEqual(manualNoteAiEvidence({}),{
  task:'issue_note',title:'Titlu',type:'lacuna',context:'motiv',
  evidence:[{label:'Titlu',act_id:'A',locator:'art1',source_url:'https://x.test',
    source_hash:'b'.repeat(64),quote:'citat',language:'RON'}]});
assert.equal(manualNoteDraftReady(manualNotePayload({},'dossier',null)),true);
const selected=manualNoteAiEvidence({}).evidence[0];
assert.equal(selected.quote,'citat');
assert.equal(selected.source_url,'https://x.test');
assert.equal(selected.source_hash,'b'.repeat(64));
values.status='reviewed';
assert.deepEqual(manualNoteSelfReviewMissing({}),[]);
values.evidence_quote='';
values.source_url='';
values.source_hash='';
values.reasoning='';
assert.deepEqual(
  manualNoteSelfReviewMissing({}),
  ['citat dovadă','sursă sau SHA-256','raționament']);
assert.equal(manualNoteDraftReady(manualNotePayload({},'dossier',null)),false);
"""
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_gap_workflow_summarizes_next_action_and_shortcuts():
    source = (
        APP.read_text()
        .split("const MANUAL_NOTE_TYPES=", 1)[1]
        .split("function manualNoteText", 1)[0]
    )
    code = (
        r"""
const assert=require('node:assert/strict');
const escapes={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc=s=>(s==null?'':String(s)).replace(/[&<>"']/g,c=>escapes[c]);
const dossierTime=s=>s;
const MANUAL_NOTE_TYPES="""
        + source
        + r"""
const empty=gapWorkflowSummary({pe_stare:{},pe_tip:{},total:0});
assert.equal(empty.next,'Scrie prima notă cu citat și sursă.');
const needs=gapWorkflowSummary({
  total:3,
  pe_stare:{needs_evidence:1,draft:1,ready_for_review:1},
  pe_tip:{risc_ue:1}
});
assert.equal(needs.evidence,2);
assert.ok(needs.next.includes('dovezile lipsă'));
const ready=gapWorkflowSummary({total:2,pe_stare:{ready_for_review:2},pe_tip:{}});
assert.ok(ready.next.includes('Revizuiește'));
const html=gapWorkflowHtml({total:2,pe_stare:{ready_for_review:1,reviewed:1},pe_tip:{risc_ue:1}});
assert.ok(html.includes('Dosar de lucru · constatare → propunere'));
assert.ok(html.includes('data-gap-step="source"'));
assert.ok(html.includes('data-gap-step="evidence"'));
assert.ok(html.includes('5. Export'));
assert.ok(html.includes('data-gap-flow-new-note'));
assert.ok(html.includes('data-gap-flow-eu-note'));
assert.ok(html.includes('data-gap-flow-ai-note'));
assert.ok(html.includes('data-gap-flow-proposals'));
assert.ok(html.includes('data-gap-flow-runs'));
assert.ok(html.includes('1. Sursă deschisă'));
assert.ok(!html.includes('<script>'));
"""
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_watchlist_feed_renderer_escapes_alerts_and_actions():
    source = (
        APP.read_text()
        .split("const WATCHLIST_KINDS=", 1)[1]
        .split("function proposalVersionHtml", 1)[0]
    )
    code = (
        r"""
const assert=require('node:assert/strict');
const escapes={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc=s=>(s==null?'':String(s)).replace(/[&<>"']/g,c=>escapes[c]);
const dossierTime=s=>s;
const acquisitionLink=(url,label)=>'<a href="'+esc(url)+'">'+esc(label)+'</a>';
const DOSARE_UI={runId:'run-1'};
const WATCHLIST_KINDS="""
        + source
        + r"""
const item={id:'a',tip:'celex',valoare:'<CELEX>',eticheta:'<script>',
  source_state:'changed',creat_la:'now',nota_revizie:'<b>',
  needs_attention:true,
  actiuni:{mark_reviewed:true},
  source:{url:'https://example.test/?q=<x>',last_hash:'c'.repeat(64),last_error:'<img>',updated_at:'later'}};
const html=watchlistItemHtml(item,0);
assert.ok(html.includes('attention'));
assert.ok(html.includes('data-watch-note'));
assert.ok(html.includes('data-watch-rerun'));
assert.ok(html.includes('data-watch-review'));
assert.ok(html.includes('data-watch-delete'));
assert.ok(!/<(script|img|x|b)>/.test(html));
const prefill=watchlistPrefill(item);
assert.equal(prefill.type,'risc_ue');
assert.equal(prefill.source_hash,'c'.repeat(64));
assert.ok(prefill.evidence_quote.includes('changed'));
"""
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_mcp_ai_draft_handoff_renderer_and_insert_metadata():
    source = (
        APP.read_text()
        .split("function mcpDraftInsertText", 1)[1]
        .split("function euIssueNoteBuilderHtml", 1)[0]
    )
    html = (
        APP.read_text()
        .split("function manualNoteFormHtml", 1)[1]
        .split("function manualNotePayload", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');function mcpDraftInsertText"
        + source
        + "const plan={insert_header:'[Ciornă MCP AI · server/tool · abc]',"
        "mcp:{audit_event:{created_at:'2026-09-12T00:00:00Z'},approval:{data_sha256:'abc'}}};"
        "const text=mcpDraftInsertText(plan,' rezultat ');"
        "assert.ok(text.includes('MCP audit: 2026-09-12T00:00:00Z · abc'));"
        "assert.ok(text.endsWith('rezultat'));"
        "const executed={insert_header:'[Ciornă MCP]',output_status:'draft_unreviewed',"
        "draft_text:'text local',audit_event:{created_at:'2026-09-12',payload_hash:'def'}};"
        "assert.ok(mcpExecutedDraftInsertText(executed).includes('status=draft_unreviewed'));"
        "const MANUAL_NOTE_TYPES={lacuna:'Lacună'};"
        "const MANUAL_NOTE_STATUS={draft:'Ciornă'};"
        "function ruleCandidateControlsHtml(){return '<details data-rule-candidate></details>';}"
        "function aiUnifiedDraftPanelHtml(label){return "
        "'<details data-unified-ai-draft>'+label+'</details>';}"
        "const esc=s=>String(s);function manualNoteFormHtml"
        + html
        + "const form=manualNoteFormHtml();"
        "assert.ok(form.includes('data-rule-candidate'));"
        "assert.ok(form.includes('data-unified-ai-draft'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_note_settings_persist_only_safe_defaults():
    source = (
        APP.read_text().split("const AI_NOTE_SETTINGS_KEY=", 1)[1].split("let _onlineOk=", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const store=new Map();"
        "const localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,String(v))};"
        "const sessionStorage={getItem:k=>k.includes('key')?'SECRET':null};"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiProvider(){return 'openai';}"
        "function aiModelOnline(){return 'gpt-test';}"
        "function aiEndpoint(){return 'https://api.test';}"
        "function aiSettings(){return {online_byok:{provider:'openai',model:'gpt-test',"
        "endpoint:'https://api.test'},platform_paid_default:false,app_paid_provider:false,"
        "key_storage:'sessionStorage_only',cost_warning:{server_cost:'none'},"
        "drafting_guardrail:{output_notice:'ciornă nerevizuită'},stores_api_key:false};}"
        "const AI_NOTE_SETTINGS_KEY="
        + source
        + "const form={elements:{ai_boundary:{value:'mcp_handoff'},"
        "ai_task:{value:'draft_amendment'},"
        "mcp_server:{value:'desktop-claude'},mcp_tool:{value:'claude.chat'}}};"
        "const saved=aiNoteSettingsSave(form);"
        "assert.equal(saved.contract,'ai-note-settings-v1');"
        "assert.equal(saved.boundary,'mcp_handoff');"
        "assert.equal(saved.stores_api_key,false);"
        "assert.ok(!store.get(AI_NOTE_SETTINGS_KEY).includes('SECRET'));"
        "form.elements.ai_boundary.value='local_ai';form.elements.ai_task.value='issue_note';"
        "aiNoteSettingsApply(form);"
        "assert.equal(form.elements.ai_boundary.value,'mcp_handoff');"
        "const html=aiNoteSettingsSummaryHtml(saved);"
        "assert.ok(html.includes('MCP aprobat'));"
        "assert.ok(html.includes('cheia API: nepăstrată'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_unified_ai_panel_exposes_all_tasks_and_manifest_actions():
    source = (
        APP.read_text().split("const AI_NOTE_SETTINGS_KEY=", 1)[1].split("let _onlineOk=", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiSettings(){return {online_byok:{provider:'openai',model:'gpt-test',"
        "endpoint:'https://api.test'},platform_paid_default:false,app_paid_provider:false,"
        "key_storage:'sessionStorage_only',cost_warning:{server_cost:'none'},"
        "drafting_guardrail:{output_notice:'ciornă nerevizuită'},stores_api_key:false};}"
        "const AI_NOTE_SETTINGS_KEY="
        + source
        + "const html=aiUnifiedDraftPanelHtml('matrice <x>');"
        "assert.ok(html.includes('data-unified-ai-draft'));"
        "assert.ok(html.includes('explică problema'));"
        "assert.ok(html.includes('notă de constatare'));"
        "assert.ok(html.includes('ciornă amendament'));"
        "assert.ok(html.includes('listă de verificare reviewer'));"
        "assert.ok(html.includes('rezumă schimbare sursă'));"
        "assert.ok(html.includes('compară două prevederi'));"
        "assert.ok(html.includes('extrage candidat law-as-code'));"
        "assert.ok(html.includes('data-ai-boundary-summary'));"
        "assert.ok(html.includes('data-ai-guardrail-output'));"
        "assert.ok(html.includes('data-ai-send-note'));"
        "assert.ok(html.includes('data-ai-copy-prompt'));"
        "assert.ok(html.includes('data-mcp-ai-draft'));"
        "assert.ok(html.includes('Nu verdict juridic'));"
        "assert.ok(!html.includes('<x>'));"
    )
    run_node(code)


def test_unified_ai_panel_is_mounted_on_dossier_proposal_and_matrix_surfaces():
    html = APP.read_text()

    assert "aiUnifiedDraftPanelHtml('pachetul dosarului')" in html
    assert "aiUnifiedDraftPanelHtml('dovada propunerii')" in html
    assert "data-matrix-ai-evidence" in html
    assert "startManualNote({" in html
    assert "data-unified-ai-draft" in html
    assert "data-ai-guardrail-output" in html


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_guardrail_summary_renders_ok_review_blocked_and_failure_states():
    source = (
        APP.read_text()
        .split("function aiGuardrailSummaryHtml", 1)[1]
        .split("async function aiRunEvidenceDraft", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiGuardrailSummaryHtml"
        + source
        + "const ok=aiGuardrailSummaryHtml({insert_allowed:true,"
        "guardrail_summary:{status:'ok',selected_evidence_only:true},"
        "claim_support:{unsupported_claims:0,claims:[]}});"
        "assert.ok(ok.includes('data-ai-guardrail-status=\"ok\"'));"
        "assert.ok(ok.includes('Guardrails OK'));"
        "const review=aiGuardrailSummaryHtml({insert_allowed:true,"
        "guardrail_summary:{status:'needs_review',selected_evidence_only:true},"
        "claim_support:{unsupported_claims:1,claims:[{status:'unsupported_labeled',"
        "reason:'missing_citation',text:'Text <unsafe>'}]}});"
        "assert.ok(review.includes('data-ai-guardrail-status=\"needs_review\"'));"
        "assert.ok(review.includes('Necesită revizie'));"
        "assert.ok(review.includes('&lt;unsafe&gt;'));"
        "const blocked=aiGuardrailSummaryHtml({insert_allowed:false,"
        "guardrail_summary:{status:'blocked',selected_evidence_only:true},"
        "claim_support:{unsupported_claims:1,claims:[{status:'unsupported_blocked',"
        "reason:'citation_outside_selected_evidence'}]}});"
        "assert.ok(blocked.includes('data-ai-guardrail-status=\"blocked\"'));"
        "assert.ok(blocked.includes('Inserare: nu'));"
        "assert.ok(blocked.includes('<details open>'));"
        "const failed=aiGuardrailSummaryHtml({status:'failed',failure:{label:'timeout',"
        "user_message:'Furnizorul nu a răspuns. Nu s-a creat nicio ciornă.',"
        "retryable:true,creates_draft:false,result_imported:false}});"
        "assert.ok(failed.includes('data-ai-guardrail-status=\"failed\"'));"
        "assert.ok(failed.includes('AI oprit'));"
        "assert.ok(failed.includes('ciornă creată: nu'));"
        "assert.ok(failed.includes('Cheia API nu este trimisă'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_draft_boundary_summary_shows_cost_approval_and_manifest():
    source = (
        APP.read_text()
        .split("function aiDraftBoundaryHtml", 1)[1]
        .split("function ruleCandidateOptions", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiDraftBoundaryHtml"
        + source
        + "const html=aiDraftBoundaryHtml({evidence_count:1,input_sha256:'i'.repeat(64),"
        "evidence_sha256:'e'.repeat(64),status:'draft_unreviewed',prompt:'PROMPT',"
        "estimated_tokens:100,cost_estimate:{estimated_total_tokens:1000,server_cost:'none',cost_owner:'user_if_byok_or_mcp'},"
        "external_approval_payload:{contract:'ai-external-send-approval-v1'},"
        "approval:{required_for_external_ai:true,server_calls_model:false,output_status:'draft_unreviewed'},"
        "evidence_manifest:[{index:1,label:'<Act>',act_id:'lege',locator:'art1',source_hash:'h'.repeat(64)}]},'online_byok');"
        "assert.ok(html.includes('online BYOK'));"
        "assert.ok(html.includes('cost server: none'));"
        "assert.ok(html.includes('ai-external-send-approval-v1'));"
        "assert.ok(html.includes('Aprobare externă: obligatorie'));"
        "assert.ok(html.includes('serverul cheamă model: nu'));"
        "assert.ok(html.includes('&lt;Act&gt;'));"
        "assert.ok(html.includes('PROMPT'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_external_approval_packet_has_cost_provider_and_no_key():
    source = (
        APP.read_text()
        .split("function aiDraftBoundaryHtml", 1)[1]
        .split("function ruleCandidateOptions", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "let confirmMessage='';"
        "function confirm(message){confirmMessage=message;return true;}"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiSettings(){return {online_byok:{provider:'openai',provider_label:'OpenAI',"
        "model:'gpt-test',endpoint:'https://api.openai.test/v1/chat/completions'},"
        "key_storage:'sessionStorage_only'};}"
        "function aiDraftBoundaryHtml"
        + source
        + "const plan={evidence_count:2,input_sha256:'i'.repeat(64),evidence_sha256:'e'.repeat(64),"
        "status:'draft_unreviewed',estimated_tokens:50,cost_estimate:{estimated_total_tokens:950,"
        "server_cost:'none',cost_owner:'user_if_byok_or_mcp'},approval:{output_status:'draft_unreviewed'},"
        "external_approval_payload:{contract:'ai-external-send-approval-v1'}};"
        "const packet=aiExternalApproval(plan,'online_byok');"
        "assert.equal(packet.contract,'ai-external-send-approval-v1');"
        "assert.equal(packet.provider,'openai');"
        "assert.equal(packet.model,'gpt-test');"
        "assert.equal(packet.estimated_total_tokens,950);"
        "assert.equal(packet.server_cost,'none');"
        "assert.equal(packet.stores_api_key,false);"
        "assert.equal(packet.key_storage,'sessionStorage_only');"
        "assert.equal(packet.output_status,'draft_unreviewed');"
        "assert.equal(packet.may_invent_sources,false);"
        "assert.equal(confirmAiExternalApproval(packet),true);"
        "assert.ok(confirmMessage.includes('Tokeni estimați: 950'));"
        "assert.ok(confirmMessage.includes('Cost server: none'));"
        "assert.ok(confirmMessage.includes('Cheia API: sesiunea browserului'));"
        "assert.ok(!JSON.stringify(packet).includes('SECRET'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_evidence_draft_execution_wrapper_is_mockable_and_secret_free():
    source = (
        APP.read_text()
        .split("function aiDraftBoundaryHtml", 1)[1]
        .split("function ruleCandidateOptions", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "let confirmed=false, sentPrompt='', sentSystem='', sentOpt=null;"
        "function confirm(message){confirmed=message.includes('Aprobi trimiterea');return true;}"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiMode(){return 'online';}"
        "function aiSettings(){return {online_byok:{provider:'openai',provider_label:'OpenAI',"
        "model:'gpt-test',endpoint:'https://api.openai.test/v1/chat/completions'},"
        "local_provider:{model:'Qwen-test'},key_storage:'sessionStorage_only'};}"
        "const AI_BYOK_TIMEOUT_MS=45000;"
        "const DOSARE_UI={selected:{id:'a'.repeat(32)}};"
        "const crypto={randomUUID:()=>'dddddddd-dddd-dddd-dddd-dddddddddddd'};"
        "async function dossierApi(path,payload){assert.equal(path,'/api/dosare/ai-workflow');"
        "assert.equal(payload.dosar_id,'a'.repeat(32));assert.equal(payload.boundary,'online_byok');"
        "assert.equal(payload.result_text,'Ciornă limitată la dovezi [1].');"
        "return {contract:'ai-draft-storage-audit-v1',boundary:'online_byok',"
        "approved_external_send:true,server_calls_model:false,stores_api_key:false,"
        "output_status:'draft_unreviewed',insert_allowed:true,"
        "claim_support:{unsupported_claims:0},draft_text:payload.result_text,"
        "insert_header:'[Ciornă AI · online_byok · OpenAI · hash]'};}"
        "async function aiComplete(prompt,system,opt){sentPrompt=prompt;sentSystem=system;"
        "sentOpt=opt;"
        "if(opt&&opt.prog)opt.prog({text:'mock send'});"
        "return {text:'Ciornă limitată la dovezi [1].',nota:'online BYOK · OpenAI'};}"
        "function aiDraftBoundaryHtml"
        + source
        + "const plan={contract:'ai-evidence-draft-v1',prompt:'PROMPT EVIDENCE ONLY',"
        "system:'SYSTEM EVIDENCE ONLY',input_sha256:'i'.repeat(64),"
        "evidence_sha256:'e'.repeat(64),evidence_count:1,estimated_tokens:100,"
        "cost_estimate:{estimated_total_tokens:1000,server_cost:'none',"
        "cost_owner:'user_if_byok_or_mcp'},approval:{output_status:'draft_unreviewed'},"
        "external_approval_payload:{contract:'ai-external-send-approval-v1'},"
        "draft_request:{task:'issue_note',type:'lacuna',evidence:[{quote:'q',source_hash:'c'.repeat(64)}]}};"
        "(async()=>{const out=await aiRunEvidenceDraft(plan,'online_byok',()=>{});"
        "assert.equal(confirmed,true);"
        "assert.equal(sentPrompt,'PROMPT EVIDENCE ONLY');"
        "assert.equal(sentSystem,'SYSTEM EVIDENCE ONLY');"
        "assert.equal(sentOpt.privat,false);"
        "assert.equal(sentOpt.timeout_ms,45000);"
        "assert.equal(out.contract,'ai-byok-execution-result-v1');"
        "assert.equal(out.request.contract,'ai-byok-execution-request-v1');"
        "assert.equal(out.request.runtime,'browser_direct_byok');"
        "assert.equal(out.request.server_calls_model,false);"
        "assert.equal(out.request.app_paid_provider,false);"
        "assert.equal(out.request.stores_api_key,false);"
        "assert.equal(out.request.prompt_scope,'selected_evidence_only');"
        "assert.equal(out.request.timeout_ms,45000);"
        "assert.equal(out.request.retry_policy.contract,'ai-byok-retry-policy-v1');"
        "assert.deepEqual(out.request.retry_policy.retryable_failures,"
        "['timeout','quota','provider_unavailable']);"
        "assert.equal(out.request.retry_policy.creates_draft_on_failure,false);"
        "assert.equal(out.request.retry_policy.result_imported_on_failure,false);"
        "assert.equal(out.request.provider_failure_contract,'ai-byok-provider-failure-v1');"
        "assert.equal(out.status,'draft_unreviewed');"
        "assert.equal(out.audit.contract,'ai-draft-storage-audit-v1');"
        "assert.equal(out.audit.approved_external_send,true);"
        "assert.equal(out.audit.server_calls_model,false);"
        "assert.equal(out.audit.stores_api_key,false);"
        "assert.ok(out.insert_header.includes('Ciornă AI'));"
        "assert.ok(!JSON.stringify(out).includes('SECRET'));})().catch(e=>{console.error(e);process.exit(1);});"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_ai_evidence_draft_execution_failure_states_are_mocked_and_secret_free():
    source = (
        APP.read_text()
        .split("function aiDraftBoundaryHtml", 1)[1]
        .split("function ruleCandidateOptions", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "function confirm(){return true;}"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "function aiMode(){return 'online';}"
        "function aiSettings(){return {online_byok:{provider:'openai',provider_label:'OpenAI',"
        "model:'gpt-test',endpoint:'https://api.openai.test/v1/chat/completions'},"
        "local_provider:{model:'Qwen-test'},key_storage:'sessionStorage_only'};}"
        "const AI_BYOK_TIMEOUT_MS=45000;"
        "const DOSARE_UI={selected:{id:'a'.repeat(32)}};"
        "const crypto={randomUUID:()=>'dddddddd-dddd-dddd-dddd-dddddddddddd'};"
        "async function dossierApi(){throw new Error('store should not run on provider failure');}"
        "let next='';"
        "async function aiComplete(){"
        "if(next==='timeout')throw Object.assign(new Error('timeout SECRET'),{code:'ETIMEDOUT'});"
        "if(next==='bad_key')throw Object.assign(new Error('401 invalid key SECRET'),{status:401});"
        "if(next==='quota')throw Object.assign(new Error('429 quota SECRET'),{status:429});"
        "if(next==='refusal')return {refusal:true,text:'SECRET'};"
        "if(next==='malformed_response')return {choices:[]};"
        "if(next==='provider_unavailable')throw Object.assign("
        "new Error('fetch failed SECRET'),{name:'TypeError'});"
        "return {text:'ok'};}"
        "function aiDraftBoundaryHtml"
        + source
        + "const plan={contract:'ai-evidence-draft-v1',prompt:'PROMPT EVIDENCE ONLY',"
        "system:'SYSTEM EVIDENCE ONLY',input_sha256:'i'.repeat(64),"
        "evidence_sha256:'e'.repeat(64),evidence_count:1,estimated_tokens:100,"
        "cost_estimate:{estimated_total_tokens:1000,server_cost:'none',"
        "cost_owner:'user_if_byok_or_mcp'},approval:{output_status:'draft_unreviewed'},"
        "external_approval_payload:{contract:'ai-external-send-approval-v1'},"
        "draft_request:{task:'issue_note',type:'lacuna',evidence:[{quote:'q',source_hash:'c'.repeat(64)}]}};"
        "(async()=>{"
        "const codes=['timeout','bad_key','quota','refusal','malformed_response',"
        "'provider_unavailable'];for(const code of codes){"
        "next=code;const out=await aiRunEvidenceDraft(plan,'online_byok',()=>{});"
        "assert.equal(out.contract,'ai-byok-execution-result-v1');"
        "assert.equal(out.status,'failed');"
        "assert.equal(out.failure.contract,'ai-byok-provider-failure-v1');"
        "assert.equal(out.failure.failure_code,code);"
        "assert.equal(out.failure.output_status,'no_draft_created');"
        "assert.equal(out.failure.creates_draft,false);"
        "assert.equal(out.failure.result_imported,false);"
        "assert.equal(out.audit.event,'ai_draft_execution_failed_in_browser');"
        "assert.equal(out.audit.failure_code,code);"
        "assert.equal(out.audit.stores_api_key,false);"
        "assert.equal(out.audit.server_calls_model,false);"
        "assert.equal(out.audit.creates_draft,false);"
        "assert.equal(out.audit.result_imported,false);"
        "assert.equal(out.text,'');"
        "assert.ok(!JSON.stringify(out).includes('SECRET'));}"
        "})().catch(e=>{console.error(e);process.exit(1);});"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_rule_candidate_controls_build_preview_payload():
    source = (
        APP.read_text()
        .split("const RULE_CANDIDATE_MODALITIES=", 1)[1]
        .split("function bindManualNoteAiDraft", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const RULE_CANDIDATE_MODALITIES="
        + source
        + 'const root={querySelector:(q)=>fields[q.match(/name="([^"]+)"/)?.[1]||q]};'
        "const fields={rule_provision_id:{value:'ro:lege-98-2016#art7'},"
        "rule_act_id:{value:'lege-98-2016'},rule_locator:{value:'art7'},"
        "rule_source_url:{value:'https://legislatie.just.ro/Public/DetaliiDocument/178667'},"
        "rule_source_hash:{value:'a'.repeat(64)},rule_text:{value:'Text <legal>'},"
        "rule_modality:{value:'obligation'},rule_review_state:{value:'machine_detected'},"
        "rule_actor:{value:'autoritatea'},rule_condition:{value:'dacă există cerere'},"
        "rule_action:{value:'publică'},rule_deadline:{value:'10 zile'},"
        "rule_exceptions:{value:'urgență\\nsecret'},rule_effect:{value:'nulitate'},"
        "rule_applicability_scope:{value:'autorități contractante'},"
        "rule_confidence:{value:'medium'},rule_extraction_method:{value:'manual_note'},"
        "rule_origin_kind:{value:'manual_note'},rule_origin_id:{value:'n1'},"
        "rule_reviewer:{value:'jurist'}};"
        "const payload=ruleCandidatePayload(root,{});"
        "assert.equal(payload.modality,'obligation');"
        "assert.equal(payload.source_url,'https://legislatie.just.ro/Public/DetaliiDocument/178667');"
        "assert.deepEqual(payload.exceptions,['urgență','secret']);"
        "assert.equal(payload.applicability_scope,'autorități contractante');"
        "assert.equal(payload.confidence,'medium');"
        "assert.equal(payload.extraction_method,'manual_note');"
        "assert.equal(payload.origin_kind,'manual_note');"
        "const html=ruleCandidateControlsHtml({text:'<script>',source_hash:'b'.repeat(64),"
        "source_url:'https://example.test/source',actor:'Autoritatea',condition:'cerere',"
        "action:'publică',deadline:'10 zile',applicability_scope:'local',"
        "confidence:'high',extraction_method:'matrix',origin_kind:'matrix_evidence',origin_id:'row-1'});"
        "assert.ok(html.includes('data-rule-candidate'));"
        "assert.ok(html.includes('data-rule-preview'));"
        "assert.ok(html.includes('data-rule-save'));"
        "assert.ok(html.includes('rule_source_url'));"
        "assert.ok(html.includes('rule_applicability_scope'));"
        "assert.ok(html.includes('rule_confidence'));"
        "assert.ok(html.includes('rule_extraction_method'));"
        "assert.ok(html.includes('matrix_evidence'));"
        "assert.ok(!html.includes('<script>'));"
    )
    run_node(code)


def test_rule_candidate_authoring_paths_are_visible():
    source = APP.read_text()

    assert "data-matrix-rule-evidence" in source
    assert "data-matrix-write-evidence" in source
    assert "extraction_method:'matrix'" in source
    assert "form.elements.rule_extraction_method.value='ai_draft'" in source
    assert "form.elements.rule_extraction_method.value='mcp_draft'" in source
    assert "origin_kind:'rule_candidate_queue'" in source
    assert "data-rule-edit-host" in source


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_matrix_evidence_opens_dossier_writing_workspace():
    source = (
        APP.read_text()
        .split("function matrixEvidenceWritingText", 1)[1]
        .split("function projectWritingSourceContext", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "class Event{constructor(type,opts={}){this.type=type;this.opts=opts;}}"
        "const esc=s=>String(s??'').replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const locRo=s=>'Loc '+s,manualNoteText=s=>String(s??'');"
        "function matrixWorkspaceNoteContext(workspace){return 'Context: '+workspace.stage;}"
        "const notesBox={value:'',dispatchEvent:e=>calls.push(['input',e.type])};"
        "const writingStatus={textContent:''};"
        "const writing={querySelector:sel=>({'[data-writing-notes]':notesBox,"
        "'[data-writing-status]':writingStatus}[sel]||null),"
        "closest:()=>({open:false}),scrollIntoView:o=>calls.push(['scroll',o.block])};"
        "const library={open:false};"
        "const dossierStatus={textContent:''};"
        "const nodes={'#dossier-library':library,'#dossier-status':dossierStatus,"
        "'#dossier-writing':writing};"
        "function $(sel){return nodes[sel]||null;}"
        "function selectTab(tab){calls.push(['tab',tab]);}"
        "function bindWritingWorkspace(){calls.push(['bind-writing']);}"
        "let DOSARE_UI={selected:null};"
        "function matrixEvidenceWritingText"
        + source
        + "const row={id:'ev-1',label:'Lacună <x>',kind:'lacuna',act_id:'lege-1',"
        "locator:'art1',source_url:'https://legislatie.just.ro/x',source_hash:'a'.repeat(64),"
        "uncertainty:'revizie manuală',quote:'Text <b>'};"
        "const context={drilldown:{workspace:{stage:'gata de lucru'}}};"
        "openMatrixEvidenceWritingWorkspace(row,context);"
        "assert.equal(library.open,true);"
        "assert.ok(dossierStatus.textContent.includes('Alege sau creează'));"
        "assert.deepEqual(calls,[['tab','dosare']]);"
        "calls.length=0;DOSARE_UI={selected:{id:'d1',titlu:'Dosar'}};"
        "openMatrixEvidenceWritingWorkspace(row,context);"
        "assert.ok(notesBox.value.includes('Redactare din matrice: Lacună <x>'));"
        "assert.ok(notesBox.value.includes('Act: lege-1 · Loc art1'));"
        "assert.ok(notesBox.value.includes('SHA-256: '+ 'a'.repeat(64)));"
        "assert.ok(notesBox.value.includes('> Text <b>'));"
        "assert.ok(notesBox.value.includes('Context: gata de lucru'));"
        "assert.ok(notesBox.value.includes('Nu este verdict juridic.'));"
        "assert.equal(writingStatus.textContent,"
        "'Dovada din matrice a fost adăugată în spațiul de redactare al dosarului.');"
        "assert.deepEqual(calls,[['tab','dosare'],['input','input'],['scroll','start']]);"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_proposal_list_export_readiness_summarizes_final_handoff():
    source = (
        APP.read_text()
        .split("function proposalListExportReadinessHtml", 1)[1]
        .split("const WATCHLIST_KINDS=", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s??'').replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;')"
        ".replaceAll('\"','&quot;');"
        "function proposalListExportReadinessHtml"
        + source
        + "const ready=proposalListExportReadinessHtml({total:2,propuneri:["
        "{titlu:'<script>',rulare_id:'run-1',constatare_id:'finding-1'}]},0);"
        "assert.ok(ready.includes('data-proposal-export-readiness'));"
        "assert.ok(ready.includes('Pregătire export propunere · gata'));"
        "assert.ok(ready.includes('Propuneri<br><b>2</b>'));"
        "assert.ok(ready.includes('Analiză<br><b>legată</b>'));"
        "assert.ok(ready.includes('Constatare<br><b>legată</b>'));"
        "assert.ok(ready.includes('Deschide o propunere ca să alegi revizia'));"
        "assert.ok(!ready.includes('<script>'));"
        "const empty=proposalListExportReadinessHtml({total:0,propuneri:[]},50);"
        "assert.ok(empty.includes('Pregătire export propunere · incompletă'));"
        "assert.ok(empty.includes('Salvează o propunere dintr-o constatare verificabilă'));"
        "assert.ok(empty.includes('Exportul nu include ciorne nesalvate'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_rule_drafts_panel_renders_queue_and_promoted_rules():
    source = (
        APP.read_text()
        .split("const RULE_CANDIDATE_MODALITIES=", 1)[1]
        .split("async function loadProposalList", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s??'').replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;')"
        ".replaceAll('\"','&quot;');"
        "const dossierTime=s=>s||'';"
        "const RULE_CANDIDATE_MODALITIES="
        + source
        + "const candidate={candidate_id:'c1',provision_id:'ro:lege#art1',"
        "act_id:'lege',locator:'art1',modality:'obligation',"
        "review_state:'human_reviewed',actor:'Autoritatea',condition:'cerere',"
        "action:'publică',deadline:'10 zile',exceptions:['secret'],"
        "effect:'nulitate',source_hash:'a'.repeat(64),"
        "source_url:'https://legislatie.just.ro/Public/DetaliiDocument/178667',"
        "applicability_scope:'proceduri',confidence:'medium',extraction_method:'manual_note'};"
        "const queue={total:1,counts:{human_reviewed:1},items:[{id:'q1',"
        "bucket:'human_reviewed',candidate,"
        "actiuni:{promote_to_rule:true}}]};"
        "const drafts={total:1,items:[{...candidate,"
        "status:'draft_rule_not_legal_verdict',accepted_by:'jurist',"
        "acceptance_note:'ok',creat_la:'2026-09-12T00:00:00Z'}]};"
        "const checks={contract:'law-rule-execution-v1',"
        "status:'deterministic_rule_draft_check_preview',"
        "check:'delegated_norm_not_found',eligible_rule_drafts:1,candidate_issues:1,returned:1,"
        "limitations:['nu este verdict juridic'],rows:[{contract:'law-rule-execution-row-v1',"
        "rule_draft_id:'d1',candidate_id:'c1',status:'candidate_issue_not_verdict',"
        "check:'delegated_norm_not_found',provision_id:'ro:lege#art1',act_id:'lege',"
        "locator:'art1',modality:'obligation',source_hash:'b'.repeat(64),"
        "matched_checks:[{severity:'medium',evidence:{expected_instrument:'hotărâre',"
        "quote:'Text <legal>'}}],limitations:['revizie umană']}]} ;"
        "const html=ruleDraftsPanelHtml(queue,drafts,checks,'all',"
        "{act:'lege',provision_id:'ro:lege#art1'});"
        "assert.ok(html.includes('law-rule-draft-v1'));"
        "assert.ok(html.includes('law-rule-execution-row-v1'));"
        "assert.ok(html.includes('data-rule-draft-text-form'));"
        "assert.ok(html.includes('data-rule-edit'));"
        "assert.ok(html.includes('data-rule-edit-host'));"
        "assert.ok(html.includes('metodă: Din notă'));"
        "assert.ok(html.includes('Domeniu aplicare'));"
        "assert.ok(html.includes('Rulează pe text'));"
        "assert.ok(html.includes('Verificări deterministe'));"
        "assert.ok(html.includes('Creează notă manuală'));"
        "assert.ok(html.includes('data-rule-promote'));"
        "assert.ok(html.includes('Ciorne promovate'));"
        "assert.ok(html.includes('Coada de candidați'));"
        "const draftText=ruleDraftTextExecutionHtml({status:'deterministic_draft_text_rule_check',"
        "candidate_issues:1,possible_matches:1,partial_matches:1,returned:2,"
        "limitations:['nu verdict juridic'],"
        "issue_candidates:[{code:'reference_missing_or_ambiguous_act',severity:'material',"
        "explanation:'Act lipsă',uncertainty:'intern posibil',"
        "source:{kind:'supplied_draft_text',quote:'art. 5'}}],"
        "rows:[{act_id:'lege',locator:'art1',"
        "status:'possible_match_not_verdict',matched_fields:['actor_found','action_found'],"
        "missing_fields:['deadline_found'],candidate_issues:1,checks:{actor_found:true},"
        "issue_candidates:[{code:'obligation_actor_missing',severity:'blocking',"
        "explanation:'Actor lipsă',uncertainty:'sinonim posibil',"
        "source:{kind:'law_rule_draft',quote:'sursa'}}]}]});"
        "assert.ok(draftText.includes('Probleme candidate'));"
        "assert.ok(draftText.includes('reference_missing_or_ambiguous_act'));"
        "assert.ok(draftText.includes('obligation_actor_missing'));"
        "assert.ok(draftText.includes('Incertitudine'));"
        "assert.ok(draftText.includes('Contract candidate issue'));"
        "assert.ok(draftText.includes('Potriviri posibile'));"
        "assert.ok(draftText.includes('Găsite: actor, acțiune'));"
        "assert.ok(draftText.includes('Lipsă: termen'));"
        "assert.ok(draftText.includes('Contract execuție text proiect'));"
        "assert.ok(!html.includes('<script>'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_legislative_writing_workspace_renders_context_and_actions():
    source = (
        APP.read_text()
        .split("function projectWorkbenchMarkdown", 1)[1]
        .split("function projectWorkbenchFilename", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s??'').replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;')"
        ".replaceAll('\"','&quot;');"
        "const dossierTime=s=>s||'';"
        "const MANUAL_NOTE_TYPES={lacuna:'Lacună',contradictie:'Contradicție',"
        "necorelare:'Necorelare',risc_ue:'Risc UE',constitutionalitate:'CCR'};"
        "const projectWorkbenchEventsHtml=events=>events.map(e=>"
        "'<p>'+esc(e.title)+'</p>').join('');"
        "const ruleDraftTextExecutionHtml=()=>'<p>rule draft placeholder</p>';"
        "function aiUnifiedDraftPanelHtml(label){return "
        "'<details data-unified-ai-draft>'+label+'</details>';}"
        "function workflowEmptyState(title,message,nextAction){return "
        "'<section data-workflow-empty-state><h4>'+esc(title)+'</h4><p>'+esc(message)+"
        "'</p><p>'+esc(nextAction)+'</p></section>';}"
        "function projectWorkbenchMarkdown"
        + source
        + "const pack={project_id:'PL-x-1',source_status:'current',"
        "summary:{events:2,notes:2},next_actions:['revizuire'],"
        "events:[{occurred_at:'2026-09-12',event_type:'vote',title:'Vot <bad>',"
        "display_label:'Vot'}],dossier_notes:[{type:'risc_ue',title:'Risc UE',"
        "status:'ready_for_review',export_markdown:'# Conflict posibil\\n\\n> citat exact UE"
        "\\n\\nNu este verdict juridic.'},"
        "{type:'lacuna',title:'Lipsă <script>',"
        "status:'ready_for_review',act_id:'lege',locator:'art1',"
        "reasoning:'Norma lipsește'},{type:'contradictie',title:'Conflict',"
        "status:'draft',reasoning:'Texte incompatibile'}],limitari:['nu verdict']};"
        "const markdown=projectWorkbenchMarkdown({project_id:'PL-x-1'},pack);"
        "assert.ok(markdown.includes('# Conflict posibil'));"
        "assert.ok(markdown.includes('citat exact UE'));"
        "assert.ok(markdown.includes('Nu este verdict juridic.'));"
        "const context=writingWorkspaceContextHtml(pack);"
        "assert.ok(context.includes('Contexte gap'));"
        "assert.ok(context.includes('Lacună'));"
        "assert.ok(context.includes('Contradicție'));"
        "assert.ok(context.includes('nu este verdict juridic'));"
        "assert.ok(!context.includes('<script>')&&!context.includes('<bad>'));"
        "const emptyContext=writingWorkspaceContextHtml(null);"
        "assert.ok(emptyContext.includes('data-workflow-empty-state'));"
        "assert.ok(emptyContext.includes('Pachet de dovezi neîncărcat'));"
        "assert.ok(emptyContext.includes('Încarcă context proiect'));"
        "const missing=writingReadinessHtml({id:'d1',titlu:'Dosar <x>'});"
        "assert.ok(missing.includes('Pregătire redactare · 1/6'));"
        "assert.ok(missing.includes('Pachet dovezi'));"
        "assert.ok(missing.includes('alege analiză salvată + constatare'));"
        "assert.ok(!missing.includes('<x>'));"
        "const ready=writingReadinessHtml({id:'d1',titlu:'Dosar',project_id:'PL-x-1'},"
        "{project_id:'PL-x-1',evidence:[{source_hash:'hash'}],dossier_notes:[{type:'lacuna'}]},"
        "'run-1','finding-1');"
        "assert.ok(ready.includes('Pregătire redactare · 6/6'));"
        "assert.ok(ready.includes('Poți salva propunerea verificabilă'));"
        "const html=writingWorkspaceHtml({id:'d1',titlu:'Dosar <x>',project_id:'PL-x-1'});"
        "assert.ok(html.includes('data-writing-readiness'));"
        "assert.ok(html.includes('data-writing-readiness-checklist'));"
        "assert.ok(html.includes('data-writing-project-form'));"
        "assert.ok(html.includes('data-writing-draft'));"
        "assert.ok(html.includes('data-writing-notes'));"
        "assert.ok(html.includes('data-writing-insert-evidence'));"
        "assert.ok(html.includes('data-writing-run-rules'));"
        "assert.ok(html.includes('data-writing-open-proposal'));"
        "assert.ok(html.includes('data-writing-ai-form'));"
        "assert.ok(html.includes('data-unified-ai-draft'));"
        "assert.ok(html.includes('Trimite în Verifică'));"
        "assert.ok(!html.includes('<x>'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_writing_workspace_routes_to_verified_proposal_editor():
    html = APP.read_text()
    assert "WRITING_PROPOSAL_HANDOFFS.get(key)" in html
    assert "WRITING_PROPOSAL_HANDOFFS.delete(key)" in html
    source = html.split("function currentProposalFindingId", 1)[1].split(
        "function aiEvidenceFromPack", 1
    )[0]
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "let DOSARE_UI={selected:{id:'d1',titlu:'Dosar X'},runId:'r1'};"
        "const DOSSIER_VIEWS=new Map([['d1:r1',{selected:'f1'}]]);"
        "const WRITING_PROPOSAL_HANDOFFS=new Map();"
        "const status={textContent:''};"
        "const saved={scrollIntoView:o=>calls.push(['scroll',o.block])};"
        "function $(sel){return {'#dossier-status':status,"
        "'#dossier-writing':{querySelector:()=>status},'#dossier-saved':saved}[sel]||null;}"
        "async function selectDossier(id,runId,checkId,findingId){"
        "calls.push(['select',id,runId,checkId,findingId]);}"
        "function currentProposalFindingId"
        + source
        + "assert.equal(currentProposalFindingId(),'f1');"
        "const payload=writingProposalHandoffPayload({titlu:'Dosar <x>'},"
        "{value:'Text propus'},{value:'Motivare'});"
        "assert.deepEqual(payload,{title:'Propunere · Dosar <x>',"
        "text:'Text propus',motiv:'Motivare'});"
        "(async()=>{await openWritingProposalEditor(payload);"
        "assert.deepEqual(calls,[['select','d1','r1',null,'f1'],['scroll','start']]);"
        "assert.deepEqual(WRITING_PROPOSAL_HANDOFFS.get('proposal:f1'),payload);"
        "assert.ok(status.textContent.includes('editorul propunerii verificate'));"
        "calls.length=0;DOSARE_UI={selected:{id:'d1'},runId:''};"
        "await openWritingProposalEditor(payload);"
        "assert.deepEqual(calls,[['scroll','start']]);"
        "assert.ok(status.textContent.includes('Alege o analiză salvată'));"
        "})().catch(err=>{console.error(err);process.exit(1);});"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_coverage_family_renders_parliamentary_evidence_counts():
    source = (
        APP.read_text()
        .split("function sourceCoverageFamilyHtml", 1)[1]
        .split("function sourceCoverageActionHtml", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s??'').replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;')"
        ".replaceAll('\"','&quot;');"
        "const dossierTime=s=>s||'';"
        "const SOURCE_STATE_LABELS={unchanged:'Neschimbată'};"
        "function sourceCoverageFamilyHtml"
        + source
        + "const row={family:'camera',label:'Camera Deputaților',status:'ok',required:true,"
        "support:{label:'Suportată',policy:'Incremental'},total:1,fetched:1,changed:0,"
        "failed:0,incomplete:0,last_checked:'2026-09-12',states:{unchanged:1},"
        "next_action:'Verifică',parliamentary_evidence_counts:{documents:2,reports:1,"
        "votes:1,avize:1,unavailable_documents:1}};"
        "const html=sourceCoverageFamilyHtml(row);"
        "assert.ok(html.includes('2 documente'));"
        "assert.ok(html.includes('1 rapoarte'));"
        "assert.ok(html.includes('1 voturi'));"
        "assert.ok(html.includes('1 avize'));"
        "assert.ok(html.includes('1 documente indisponibile'));"
        "const note=sourceCoverageFamilyNote(row);"
        "assert.ok(note.evidence_quote.includes('2 documente, 1 rapoarte, 1 voturi, 1 avize'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_project_cockpit_handoff_opens_writing_workspace():
    source = (
        APP.read_text()
        .split("function projectWritingSourceContext", 1)[1]
        .split("function projectWorkbenchFilename", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "class Event{constructor(type,opts={}){this.type=type;this.opts=opts;}}"
        "let DOSARE_UI={selected:{id:'d1'}};"
        "const draft={value:'',dispatchEvent:e=>calls.push(['draft-event',e.type])};"
        "const writingForm={elements:{project_id:{value:''}},"
        "dispatchEvent:e=>calls.push(['form-submit',writingForm.elements.project_id.value,e.type])};"
        "const draftBox={value:''},notesBox={value:''};"
        "const host={querySelector:sel=>({'[data-writing-project-form]':writingForm,"
        "'[data-writing-draft]':draftBox,'[data-writing-notes]':notesBox}[sel]||null),"
        "closest:()=>({setAttribute:(k,v)=>calls.push(['open-writing',k,v])}),"
        "scrollIntoView:opts=>calls.push(['scroll',opts.block])};"
        "const dossierLibrary={open:false},dossierStatus={},cockpitStatus={};"
        "function $(sel){return {'#project-cockpit-status':cockpitStatus,"
        "'#dossier-status':dossierStatus,'#draft':draft,"
        "'#dossier-writing':host,'#dossier-library':dossierLibrary}[sel]||null;}"
        "async function projectDraftSeed(projectId){calls.push(['seed',projectId]);"
        "return {text:'Draft factual <x>',summary:{events:2}};}"
        "async function selectDossier(id){calls.push(['select',id]);}"
        "function lifecyclePrefillDossier(project){calls.push(['prefill',project.project_id]);}"
        "function selectTab(tab){calls.push(['tab',tab]);}"
        "function projectWritingSourceContext" + source + "(async()=>{"
        "await openProjectWritingWorkspace({project_id:'PL <x>',dossier_id:'d1',"
        "title:'Titlu <x>',stage:{label:'Avizare'}},{project_id:'PL <x>',"
        "dossier_id:'d1',tracker:{total:3,latest_event:{event_label:'Vot <x>'}},"
        "source_attention:{registry_source_state:'changed'}});"
        "assert.deepEqual(calls.slice(0,2),[['select','d1'],['form-submit','PL <x>','submit']]);"
        "assert.equal(draftBox.value,'Draft factual <x>');"
        "assert.ok(notesBox.value.includes('Context proiect: PL <x>'));"
        "assert.ok(notesBox.value.includes('nu este verdict juridic'));"
        "assert.ok(dossierStatus.textContent.includes('Spațiu de redactare pregătit'));"
        "calls.length=0;DOSARE_UI={selected:null};draft.value='';"
        "await openProjectWritingWorkspace({project_id:'PL-2'},null);"
        "assert.deepEqual(calls.map(c=>c[0]),['prefill','seed','draft-event','tab']);"
        "assert.equal(draft.value,'Draft factual <x>');"
        "assert.equal(dossierLibrary.open,true);"
        "})().catch(err=>{console.error(err);process.exit(1);});"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_rule_check_candidate_prefills_manual_note():
    source = (
        APP.read_text()
        .split("function manualNoteText", 1)[1]
        .split("async function openManualNoteSource", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const MANUAL_NOTE_TYPES={lacuna:'Lacună',necorelare:'Necorelare'};"
        "function manualNoteText"
        + source
        + "const note=manualNoteFromRuleCheck({status:'candidate_issue_not_verdict',"
        "check:'delegated_norm_not_found',rule_draft_id:'d1',act_id:'lege-98-2016',"
        "locator:'art3',source_hash:'a'.repeat(64),matched_checks:[{evidence:{"
        "quote:'Ministerul emite norme',source_url:'https://example.test/sursa'}}],"
        "limitations:['nu este verdict juridic']});"
        "assert.equal(note.type,'lacuna');"
        "assert.equal(note.status,'ready_for_review');"
        "assert.equal(note.act_id,'lege-98-2016');"
        "assert.ok(note.title.includes('normă delegată negăsită'));"
        "assert.ok(note.evidence_quote.includes('Ministerul emite norme'));"
        "assert.ok(note.reasoning.includes('d1'));"
        "assert.ok(note.reasoning.includes('nu este verdict juridic'));"
        "const noSignal=manualNoteFromRuleCheck({status:'no_local_candidate_signal',"
        "check:'delegated_norm_not_found',rule_draft_id:'d2',matched_checks:[]});"
        "assert.equal(noSignal.type,'necorelare');"
        "assert.equal(noSignal.status,'needs_evidence');"
        "assert.ok(noSignal.reasoning.includes('nu înseamnă conformitate'));"
    )
    run_node(code)


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
    run_node(code)


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
    run_node(code)


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
    run_node(code)


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
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_context_renderer_escapes_values_and_citations_and_labels_unknown():
    source = (
        APP.read_text().split("const CONTEXT_FIELDS=", 1)[1].split("function euCheckHtml", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const CONTEXT_FIELDS="
        + source
        + "assert.ok(legalContextEventHtml(null).includes('Context necunoscut'));"
        "const event={revizie:1,evaluator:'<script>',motiv:'<img>',"
        "context:{teritoriu:{valoare:'<svg>',citare:'<iframe>'}}};"
        "const h=legalContextEventHtml(event);"
        "assert.ok(!/<(script|img|svg|iframe)>/.test(h));"
        "assert.ok(h.includes('Citare: &lt;iframe&gt;')&&h.includes('Necunoscut'));"
        "assert.ok(legalContextFormHtml().includes('Necunoscută'));"
        "const f={dovada:{a:{act_id:'A',locator:'art1'}},"
        "context_juridic:{a:{curent:null,istoric:[]}}};"
        "assert.ok(legalContextHtml(f).includes('Context juridic · A'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_workspace_filter_and_saved_evidence_rendering():
    source = (
        APP.read_text()
        .split("function findingSourcesHtml", 1)[1]
        .split("function reviewFindingHtml", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const fold=s=>s.toLowerCase(),locRo=s=>s,REVIEW_STATES={unreviewed:'Neanalizat'};"
        "function findingSourcesHtml"
        + source
        + "const a={id:'a',tip:'contradictie',stare:'unreviewed',dovada:{termen:'Deadline',"
        "a:{act_id:'A',locator:'art1',text:'<script>'},b:{act_id:'B',definitie:'<img>'}}};"
        "const b={id:'b',stare:'dismissed',dovada:{act_id:'C'},verificare:{stare:'schimbat'}};"
        "assert.deepEqual(workspaceFindings([a,b],'all','deadline'),[a]);"
        "assert.deepEqual(workspaceFindings([a,b],'unresolved',''),[a]);"
        "assert.deepEqual(workspaceFindings([a,b],'evidence_changed',''),[b]);"
        "assert.deepEqual(workspaceFindings([a,b],'all','absent'),[]);"
        "const h=findingSourcesHtml(a);assert.ok(!h.includes('<script>')&&!h.includes('<img>'));"
        "assert.ok(h.includes('Dovezi păstrate în rulare')&&h.includes('Text curent local'));"
        "assert.ok(h.includes('A · A')&&h.includes('B · B'));"
        "assert.ok(!findingSourcesHtml({...a,tip:'proiect'}).includes('data-current-source'));"
        "assert.ok(workspaceFindingHtml(a,'a',true).includes('aria-current=\"true\"'));"
        "assert.ok(workspaceFindingHtml(a,'a',true).includes('Note nesalvate'));"
    )
    run_node(code)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_workspace_navigation_guard_restores_selectors():
    source = (
        APP.read_text()
        .split("function dossierMayNavigate", 1)[1]
        .split("async function dossierApi", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');let dirty=true;"
        "const dossierHasDrafts=()=>dirty,DOSARE_UI={selected:{id:'original'},runId:'run'};"
        "const nodes={'#dossier-status':{},'#dossier-select':{value:'changed'},"
        "'#dossier-run-select':{value:'changed'}},$=id=>nodes[id];"
        "function dossierMayNavigate" + source + "assert.equal(dossierMayNavigate(),false);"
        "assert.equal(nodes['#dossier-select'].value,'original');"
        "assert.equal(nodes['#dossier-run-select'].value,'run');"
        "dirty=false;assert.equal(dossierMayNavigate(),true);"
    )
    run_node(code)
