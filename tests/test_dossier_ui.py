import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

APP = Path(__file__).parents[1] / "app/index.html"


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


def test_saved_finding_review_exposes_manual_note_action():
    source = APP.read_text()
    assert "data-note-from-finding" in source
    assert "Creează notă" in source


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    result = subprocess.run(["node", "-e", code], capture_output=True, timeout=10)
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
assert.ok(!/<(script|img|svg|b|i)>/.test(h));
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
  act_id:'lege-1',locator:'art. 2',text:'missing',instrument:'hotărâre'});
assert.equal(lacuna.type,'lacuna');
assert.ok(lacuna.reasoning.includes('hotărâre'));
const values={title:'Titlu',type:'lacuna',act_id:'A',locator:'art1',
  evidence_quote:'citat',source_url:'https://x.test',source_hash:'b'.repeat(64),
  reasoning:'motiv',status:'draft'};
class FormData{constructor(){return Object.entries(values)}}
assert.deepEqual(manualNotePayload({},'dossier',null),{
  id:'11111111222243338444555555555555',dosar_id:'dossier',revizie:0,title:'Titlu',
  type:'lacuna',act_id:'A',locator:'art1',evidence_quote:'citat',
  source_url:'https://x.test',source_hash:'b'.repeat(64),reasoning:'motiv',status:'draft'});
values.status='reviewed';
assert.deepEqual(manualNoteSelfReviewMissing({}),[]);
values.evidence_quote='';
values.source_url='';
values.source_hash='';
values.reasoning='';
assert.deepEqual(
  manualNoteSelfReviewMissing({}),
  ['citat dovadă','sursă sau SHA-256','raționament']);
"""
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
assert.ok(html.includes('data-gap-flow-new-note'));
assert.ok(html.includes('data-gap-flow-eu-note'));
assert.ok(html.includes('data-gap-flow-ai-note'));
assert.ok(html.includes('data-gap-flow-proposals'));
assert.ok(html.includes('data-gap-flow-runs'));
assert.ok(html.includes('✓ 1. Constatare')||html.includes('1. Constatare'));
assert.ok(!html.includes('<script>'));
"""
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
        "approval:{required_for_external_ai:true,server_calls_model:false,output_status:'draft_unreviewed'},"
        "evidence_manifest:[{index:1,label:'<Act>',act_id:'lege',locator:'art1',source_hash:'h'.repeat(64)}]},'online_byok');"
        "assert.ok(html.includes('online BYOK'));"
        "assert.ok(html.includes('cost server: none'));"
        "assert.ok(html.includes('Aprobare externă: obligatorie'));"
        "assert.ok(html.includes('serverul cheamă model: nu'));"
        "assert.ok(html.includes('&lt;Act&gt;'));"
        "assert.ok(html.includes('PROMPT'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
        "assert.ok(html.includes('Verificări deterministe'));"
        "assert.ok(html.includes('Creează notă manuală'));"
        "assert.ok(html.includes('data-rule-promote'));"
        "assert.ok(html.includes('Ciorne promovate'));"
        "assert.ok(html.includes('Coada de candidați'));"
        "assert.ok(!html.includes('<script>'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


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
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)
