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


def test_dossier_creation_surfaces_source_freshness_warning():
    source = APP.read_text()
    assert 'id="dossier-source-warning"' in source
    assert "renderDossierSourceFreshness" in source
    assert "sourceFreshnessStatus" in source


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
        "const MANUAL_NOTE_TYPES={lacuna:'Lacună'};"
        "const MANUAL_NOTE_STATUS={draft:'Ciornă'};"
        "function ruleCandidateControlsHtml(){return '<details data-rule-candidate></details>';}"
        "const esc=s=>String(s);function manualNoteFormHtml"
        + html
        + "const form=manualNoteFormHtml();"
        "assert.ok(form.includes('data-rule-candidate'));"
        "assert.ok(form.includes('data-ai-boundary-summary'));"
        "assert.ok(form.includes('data-ai-note-settings'));"
        "assert.ok(form.includes('data-ai-settings-save'));"
        "assert.ok(form.includes('data-ai-send-note'));"
        "assert.ok(form.includes('data-ai-copy-prompt'));"
        "assert.ok(form.includes('explică problema'));"
        "assert.ok(form.includes('ciornă amendament'));"
        "assert.ok(form.includes('online BYOK'));"
        "assert.ok(form.includes('costă în contul tău'));"
        "assert.ok(form.includes('data-mcp-ai-draft'));"
        "assert.ok(form.includes('data-mcp-preview'));"
        "assert.ok(form.includes('data-mcp-copy'));"
        "assert.ok(form.includes('data-mcp-insert'));"
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
        "assert.equal(out.contract,'ai-byok-execution-result-v1');"
        "assert.equal(out.request.contract,'ai-byok-execution-request-v1');"
        "assert.equal(out.request.runtime,'browser_direct_byok');"
        "assert.equal(out.request.server_calls_model,false);"
        "assert.equal(out.request.app_paid_provider,false);"
        "assert.equal(out.request.stores_api_key,false);"
        "assert.equal(out.request.prompt_scope,'selected_evidence_only');"
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
        "assert.equal(out.audit.event,'ai_draft_execution_failed_in_browser');"
        "assert.equal(out.audit.failure_code,code);"
        "assert.equal(out.audit.stores_api_key,false);"
        "assert.equal(out.audit.server_calls_model,false);"
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
        "rule_source_hash:{value:'a'.repeat(64)},rule_text:{value:'Text <legal>'},"
        "rule_modality:{value:'obligation'},rule_review_state:{value:'machine_detected'},"
        "rule_actor:{value:'autoritatea'},rule_condition:{value:'dacă există cerere'},"
        "rule_action:{value:'publică'},rule_deadline:{value:'10 zile'},"
        "rule_exceptions:{value:'urgență\\nsecret'},rule_effect:{value:'nulitate'},"
        "rule_reviewer:{value:'jurist'}};"
        "const payload=ruleCandidatePayload(root,{});"
        "assert.equal(payload.modality,'obligation');"
        "assert.deepEqual(payload.exceptions,['urgență','secret']);"
        "const html=ruleCandidateControlsHtml({text:'<script>',source_hash:'b'.repeat(64)});"
        "assert.ok(html.includes('data-rule-candidate'));"
        "assert.ok(html.includes('data-rule-preview'));"
        "assert.ok(html.includes('data-rule-save'));"
        "assert.ok(!html.includes('<script>'));"
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
        "effect:'nulitate',source_hash:'a'.repeat(64)};"
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
        "assert.ok(html.includes('Rulează pe text'));"
        "assert.ok(html.includes('Verificări deterministe'));"
        "assert.ok(html.includes('Creează notă manuală'));"
        "assert.ok(html.includes('data-rule-promote'));"
        "assert.ok(html.includes('Ciorne promovate'));"
        "assert.ok(html.includes('Coada de candidați'));"
        "const draftText=ruleDraftTextExecutionHtml({status:'deterministic_draft_text_rule_check',"
        "possible_matches:1,partial_matches:1,returned:2,rows:[{act_id:'lege',locator:'art1',"
        "status:'possible_match_not_verdict',matched_fields:['actor_found','action_found'],"
        "missing_fields:['deadline_found'],checks:{actor_found:true}}]});"
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
        "const html=writingWorkspaceHtml({id:'d1',titlu:'Dosar <x>',project_id:'PL-x-1'});"
        "assert.ok(html.includes('data-writing-project-form'));"
        "assert.ok(html.includes('data-writing-draft'));"
        "assert.ok(html.includes('data-writing-notes'));"
        "assert.ok(html.includes('data-writing-insert-evidence'));"
        "assert.ok(html.includes('data-writing-run-rules'));"
        "assert.ok(html.includes('Trimite în Verifică'));"
        "assert.ok(!html.includes('<x>'));"
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
