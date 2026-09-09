"""Exercise the production context functions without browser or package dependencies."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_context_provenance_filters_and_comparison():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = (
        "const CONTEXT_FIELDS="
        + html.split("const CONTEXT_FIELDS=", 1)[1].split("function legalContextEventHtml", 1)[0]
    )
    code = (
        source
        + r"""
const assert=require('node:assert/strict');
const event=(value,citation='Act A art. 1')=>({id:'event',revizie:2,evaluator:'Author',
  creat_la:'2026-09-10',context:{teritoriu:{valoare:value,citare:citation}}});
const a=event('Romania'),b=event('Romania','Act B art. 2');
const f={dovada:{domeniu:{cheie:'mediu',eticheta:'Mediu',dovezi:['titlu: ape']}}};
const before=JSON.stringify([f,a,b]);
const rows=legalContextRows(f,a,b);
assert.equal(rows.find(r=>r.key==='teritoriu').comparison,'equal');
assert.equal(rows.find(r=>r.key==='teritoriu').b.citation,'Act B art. 2');
assert.equal(rows.find(r=>r.key==='clasificare').comparison,'unknown');
assert.equal(rows.find(r=>r.key==='exceptii').a.kind,'unknown');
assert.equal(rows.find(r=>r.key==='domeniu').a.kind,'heuristic');
assert.equal(legalContextFilter(rows,{kind:'known'}).length,1);
assert.equal(legalContextFilter(rows,{kind:'heuristic'}).length,1);
assert.equal(legalContextFilter(rows,{kind:'unknown'}).length,6);
assert.equal(legalContextFilter(rows,{query:'ACT B art. 2'})[0].key,'teritoriu');
assert.equal(legalContextFilter(rows,{field:'clasificare',kind:'known'}).length,0);
assert.equal(legalContextFilter(rows,{comparison:'equal'}).length,1);
assert.equal(legalContextCompare(legalContextValue(a,'teritoriu'),legalContextValue(event('EU'),'teritoriu')),'different');
for(const missing of [null,event(''),event('Romania',''),event('Romania',' ')]){
  assert.equal(legalContextValue(missing,'teritoriu').kind,'unknown');
  assert.equal(legalContextRows(f,a,missing)[2].comparison,'unknown');
}
assert.equal(legalContextValue(a,'teritoriu').author,'Author');
assert.equal(legalContextValue(a,'teritoriu').event,'event');
const labelOnly={dovada:{domeniu:{eticheta:'Label only'}}};
assert.equal(legalContextRows(labelOnly,a,b).at(-1).a.kind,'unknown');
assert.equal(legalContextRows({dovada:{}},a,b).at(-1).a.kind,'unknown');
const dated={context:{aplicabil_de_la:{valoare:'2026-01-01',citare:'A art. 3'}}};
assert.equal(legalContextRows(f,dated,dated)[0].comparison,'equal');
assert.equal(legalContextRows(f,dated,dated)[1].comparison,'unknown');
assert.equal(JSON.stringify([f,a,b]),before);
// Rendering escapes author labels, citations and values through the existing esc helper.
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const controls=new Map();
const host={dataset:{},querySelector(s){
  const filter=['kind','field','comparison'].some(k=>s.includes(k));
  if(!controls.has(s))controls.set(s,{value:filter?'all':s.includes('left')?'0':'',innerHTML:''});
  return controls.get(s);
}};
const hostile=event('<img src=x onerror=alert(1)>','<script>');
bindLegalContextWorkflow(host,{dovada:{},context_juridic:{a:{curent:hostile,istoric:[hostile]},b:{curent:null,istoric:[]}}});
const output=host.querySelector('[data-context-results]').innerHTML;
assert.ok(output.includes('&lt;img'));
assert.ok(!output.includes('<img'));
assert.ok(!output.includes('<script>'));
assert.ok(host.querySelector('[data-context-right]').innerHTML.includes('B'));
assert.ok(!host.querySelector('[data-context-right]').innerHTML.includes('value="2"'));
"""
    )
    result = subprocess.run(["node", "-e", code], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
