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
