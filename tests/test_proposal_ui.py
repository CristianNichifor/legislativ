import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_proposal_draft_retry_conflict_and_independent_cancel():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function bindFindingProposal", 1)[1]
        .split("async function loadFindingReviews", 1)[0]
    )
    code = (
        r"""
const assert=require('node:assert/strict');
const bindProposalHistory=()=>{};
const bindProposalAnalysis=()=>{};
const bindEuProposalLinks=()=>{};
const bindStructuredProposal=()=>{};
const proposalSeed=()=>null;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class FormData { constructor(form){return Object.entries(form.fields).map(([k,v])=>[k,v.value]);} }
const panel={reviewDrafts:new Map(),proposalOpen:new Set(['finding']),querySelector:()=>({})};
const saved={propunere:null,baza:{rulare_id:'run',constatare_id:'finding',raport_sha256:'hash'}};
let calls=[],fail=false,renders=0;
async function dossierApi(url,payload){
  if(!payload)return structuredClone(saved);
  calls.push(payload);
  if(fail)throw Error('Lost response');
  saved.propunere={...payload,revizie:payload.revizie+1};
}
function mount(){
  const fields=Object.fromEntries(['titlu','text','motiv'].map(k=>[k,{value:'',disabled:false}]));
  const cancel={},latest={},status={},basis={};
  const elements=Object.values(fields);elements.namedItem=k=>fields[k];
  const form={fields,elements,querySelector:s=>s.includes('cancel')?cancel:latest};
  const host={isConnected:true,querySelector:s=>s==='form'?form:s.includes('status')?status:basis};
  const section={querySelector:()=>host};
  bindFindingProposal(section,panel,{id:'finding'},'dossier','run',()=>true,()=>renders++);
  return {form,host,status,cancel};
}
"""
        + "function bindFindingProposal"
        + source
        + r"""
(async()=>{
  let ui=mount();await tick();
  ui.form.fields.titlu.value='First';ui.form.oninput();
  assert.equal(panel.reviewDrafts.get('proposal:finding').revision,0);
  ui.form.fields.titlu.value='';ui.form.oninput();assert.equal(panel.reviewDrafts.size,0);
  ui.form.fields.titlu.value='First';ui.form.oninput();
  fail=true;await ui.form.onsubmit({preventDefault(){}});
  assert.equal(renders,1);assert.equal(panel.reviewDrafts.get('proposal:finding').saving,false);
  const id=calls[0].id;
  saved.propunere={titlu:'Server version',text:'Concurrent text',motiv:'',revizie:7};
  ui.host.isConnected=false;ui=mount();await tick();
  assert.equal(ui.form.fields.titlu.value,'First');
  assert.equal(panel.reviewDrafts.get('proposal:finding').revision,0);
  assert.equal(ui.status.textContent,'Lost response');
  await ui.form.onsubmit({preventDefault(){}});
  assert.equal(calls[1].id,id);assert.equal(calls[1].revizie,0);
  ui=mount();await tick();ui.form.fields.text.value='Changed retry';ui.form.oninput();
  await ui.form.onsubmit({preventDefault(){}});
  assert.notEqual(calls[2].id,id);assert.equal(calls[2].revizie,0);
  panel.reviewDrafts.set('finding',{motiv:'Review notes'});
  ui=mount();await tick();ui.cancel.onclick();
  assert.equal(panel.reviewDrafts.has('proposal:finding'),false);
  assert.equal(panel.reviewDrafts.get('finding').motiv,'Review notes');
  ui=mount();await tick();assert.equal(ui.form.fields.titlu.value,'Server version');
  fail=false;await ui.form.onsubmit({preventDefault(){}});
  assert.equal(calls[3].revizie,7);assert.equal(saved.propunere.revizie,8);
  assert.equal(panel.reviewDrafts.has('proposal:finding'),false);
})().catch(e=>{console.error(e);process.exit(1)});
"""
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_law_workbench_finding_prefills_proposal_target_and_rationale():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function proposalSeed", 1)[1]
        .split("function workspaceFindings", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const locRo=id=>id==='art7'?'art. 7':id;"
        "function proposalSeed"
        + source
        + r"""
const finding={tip:'lacuna',dovada:{act_id:'lege-98-2016',locator:'art7',text:'Nu există termen.'}};
const seed=proposalSeed(finding);
assert.equal(seed.act_id,'lege-98-2016');
assert.equal(seed.locator,'art7');
assert.equal(seed.titlu,'Propunere pentru lege-98-2016 art. 7');
assert.ok(seed.motiv.includes('lacuna salvată'));
const html=proposalPrefillHtml(finding);
assert.ok(html.includes('Țintă propunere sugerată'));
assert.ok(html.includes('lege-98-2016 art. 7'));
assert.ok(html.includes('aplicația nu inventează soluția'));
assert.equal(proposalSeed({tip:'contradictie',dovada:{act_id:'lege',locator:'art1'}}),null);
"""
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_revision_comparison_renderer_escapes_all_author_text():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function proposalVersionHtml", 1)[1]
        .split("function bindProposalHistory", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const dossierTime=s=>s;function proposalVersionHtml"
        + source
        + "const h=proposalVersionHtml({revizie:2,creat_la:'<iframe>',titlu:'<script>',"
        "text:'<img>',motiv:'<svg>'});"
        "assert.ok(h.includes('Revizia 2')&&h.includes('Text propus')&&h.includes('Motivare'));"
        "assert.ok(!/<(script|img|svg|iframe)>/.test(h));"
        "assert.ok(h.includes('&lt;script&gt;')&&h.includes('&lt;img&gt;'));"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_rationale_edits_preserve_structure_but_manual_text_detachment_is_respected():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function bindFindingProposal", 1)[1]
        .split("form.oninput=()=>{", 1)[1]
        .split("form.querySelector('[data-proposal-cancel]')", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');const drafts=new Map(),key='p',revision=1;"
        "const initial={titlu:'Title',text:'Generated',motiv:''},message={},mark=()=>{};"
        "const saved={interventie:{cerere:{operatie:'modifica',sha256_tinta:'hash'}}};"
        "const values=()=>({...initial,motiv:'New rationale'});"
        "const edit=()=>{"
        + source
        + "edit();assert.deepEqual(drafts.get(key).interventie,saved.interventie.cerere);"
        "drafts.get(key).interventie=null;edit();assert.equal(drafts.get(key).interventie,null);"
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_analysis_renderer_escapes_sources_and_keeps_statuses_distinct():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function proposalAnalysisHtml", 1)[1]
        .split("function bindProposalAnalysis", 1)[0]
    )
    code = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const dossierTime=s=>s;function proposalAnalysisHtml"
        + source
        + r"""
const statuses=['verificat','partial','indisponibil','nesuportat'];
const a={baza:{revizie:1,text_sha256:'<img>'},creat_la:'<svg>',engine_version:'<script>',
  text_analizat:'<iframe>',surse:[{text:'<script>'}],surse_sha256:'hash',acoperire:{},
  limitari:['<img>'],controale:statuses.map(stare=>({stare,eticheta:'<svg>',limitare:'<script>',
    total:0,tip_rezultate:'inventar',rezultate:[{fragment:'<iframe>'}]}))};
const html=proposalAnalysisHtml({selectata:a,istorica:true});
assert.ok(!/<(script|img|svg|iframe)>/.test(html));
for(const s of ['istorică','Verificat','Parțial','Indisponibil','Nesuportat','inventariate'])
  assert.ok(html.includes(s));
const empty=proposalAnalysisHtml({selectata:null,revizie_selectata:2});
assert.ok(empty.includes('Revizia 2')&&empty.includes('fără analiză'));
assert.ok(!empty.includes('Verificat'));
"""
    )
    subprocess.run(["node", "-e", code], check=True, capture_output=True, timeout=10)
