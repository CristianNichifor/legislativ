import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_analysis_retry_survives_navigation_and_late_result_preserves_selection():
    source = (
        (Path(__file__).parents[1] / "app/index.html")
        .read_text()
        .split("function bindProposalAnalysis", 1)[1]
        .split("function bindStructuredProposal", 1)[0]
    )
    code = (
        r"""
const assert=require('node:assert/strict');
const esc=String,dossierTime=String,proposalAnalysisHtml=data=>data.selectata?.id||'unchecked';
const panel={},identity={dosar_id:'dossier',rulare_id:'run',constatare_id:'finding'};
const saved={revizie:1},tick=()=>new Promise(r=>setImmediate(r));
let mounted,post=[],release,fail=true,stored=[];
const document={createElement:()=>({isConnected:true,dataset:{},append(){},
  controls:new Map(),
  querySelector(s){if(!this.controls.has(s))this.controls.set(s,{value:'',textContent:'',append(){},after(){}});
    return this.controls.get(s);}})};
async function dossierApi(url,payload){
  if(payload){post.push(payload);await new Promise(r=>release=r);
    if(!stored.some(a=>a.id===payload.id))stored.push({id:payload.id,baza:{revizie:payload.revizie}});
    if(fail)throw Error('Lost response');return stored.at(-1);}
  const qs=new URL(url,'http://local').searchParams,rev=Number(qs.get('revizie'));
  const result=stored.find(a=>a.id===qs.get('analiza_id'))||
    stored.findLast(a=>a.baza.revizie===rev);
  return {selectata:result||null,revizie_selectata:rev,analize:stored.map(a=>({id:a.id,
    revizie:a.baza.revizie,creat_la:'time'})),total:stored.length};
}
function mount(){
  const host={closest:()=>({after(section){mounted=section;}})};
  bindProposalAnalysis(host,panel,saved,identity,()=>true);
  const section=mounted;section.open=true;section.ontoggle();return section;
}
const control=(section,name)=>section.querySelector('[data-analysis-'+name+']');
"""
        + "function bindProposalAnalysis"
        + source
        + r"""
(async()=>{
  let ui=mount();await tick();assert.equal(control(ui,'result').innerHTML,'unchecked');
  control(ui,'run').onclick();assert.equal(control(ui,'run').disabled,true);
  const firstID=post[0].id;ui.isConnected=false;ui=mount();await tick();
  assert.equal(control(ui,'run').disabled,true);release();await tick();await tick();
  assert.equal(control(ui,'run').textContent,'Reîncearcă verificarea');
  assert.equal(control(ui,'status').textContent,'Lost response');
  assert.equal(control(ui,'result').innerHTML,firstID);
  fail=false;control(ui,'run').onclick();release();await tick();await tick();
  assert.equal(post[1].id,firstID);assert.equal(stored.length,1);
  assert.equal(control(ui,'run').disabled,false);
  // A successful explicit recheck gets a new identity, but cannot replace a
  // historical check the user selected while that request was pending.
  control(ui,'run').onclick();assert.notEqual(post[2].id,firstID);
  const history=control(ui,'history');history.value=firstID;
  history.selectedOptions=[{dataset:{revision:1}}];history.onchange();await tick();
  release();await tick();await tick();assert.equal(stored.length,2);
  assert.equal(control(ui,'result').innerHTML,firstID);
  // Changing revision while a check runs cannot import that result into the new view.
  control(ui,'run').onclick();control(ui,'revision').value=2;
  control(ui,'revision').oninput();control(ui,'revision').onchange();await tick();
  release();await tick();await tick();assert.equal(control(ui,'result').innerHTML,'unchecked');
  assert.equal(control(ui,'export').disabled,true);
})().catch(e=>{console.error(e);process.exit(1)});
"""
    )
    result = subprocess.run(["node", "-e", code], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
