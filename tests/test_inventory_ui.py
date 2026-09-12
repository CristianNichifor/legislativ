"""Exercise the actual inline renderer without requiring a browser or network."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_inventory_renderer_states_and_escaping():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    renderer = html.split("const SOURCE_LABELS=", 1)[1].split("let SOURCE_REPORT=", 1)[0]
    program = (
        """
const assert=require('node:assert/strict');
const nf=n=>String(n);
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
"""
        + "const SOURCE_LABELS="
        + renderer
        + """
assert.equal(sourceValue({stare:'masurat',valoare:0}),'0');
assert.equal(sourceValue({stare:'necunoscut',valoare:null}),'Necunoscut');
assert.equal(sourceValue(undefined),'Indisponibil');
assert.equal(sourceValue({stare:'masurat',valoare:'2026-09-09 12:30:00'}),'09.09.2026 12:30:00');
const h=sourceInventoryHtml({mod:'local_readonly',surse:{
 corpus:{stare:'partial',metrici:{acte:{stare:'masurat',valoare:0},
 surse_esuate:{stare:'masurat',valoare:3}}},
 importuri:{stare:'disponibil',metrici:{ocr_necesar:{stare:'masurat',valoare:2}}}
},limitari:['<img src=x onerror=alert(1)>']});
assert.ok(h.includes('Date parțial disponibile'));
assert.ok(h.includes('source-dashboard'));
assert.ok(h.includes('Necesită atenție'));
assert.ok(h.includes('Următorul pas: Actualizează corpusul local'));
assert.ok(h.includes('Surse HTML eșuate: 3'));
assert.ok(h.includes('Necesită OCR / verificare: 2'));
assert.ok(h.includes('Stare necunoscută'));
assert.ok(h.includes('Actualitate locală necunoscută'));
assert.ok(h.includes('&lt;img'));
assert.ok(!h.includes('<img'));
const fresh=sourceInventoryHtml({mod:'local_readonly',surse:{ue:{stare:'disponibil',
 metrici:{acte:{stare:'masurat',valoare:4},
 ultima_inregistrare_stocata:{stare:'masurat',valoare:'2026-09-09 12:30:00'}}}}});
assert.ok(fresh.includes('Utilizabilă local'));
assert.ok(fresh.includes('Ultima înregistrare stocată (UTC): 09.09.2026 12:30:00'));
const s=sourceInventoryHtml({mod:'static'});
assert.ok(s.includes('nu este disponibil'));
assert.ok(!s.includes('Acte stocate'));
const warnings=sourceFreshnessWarnings({mod:'local_readonly',surse:{
 corpus:{stare:'partial',metrici:{acte:{stare:'masurat',valoare:3},
 surse_esuate:{stare:'masurat',valoare:1}}},
 ue:{stare:'lipsa',metrici:{acte:{stare:'indisponibil',valoare:null}}},
 importuri:{stare:'disponibil',metrici:{versiuni:{stare:'masurat',valoare:2}}}
},limitari:[]});
assert.equal(warnings.length,3);
assert.ok(warnings[0].includes('Legislație română'));
assert.ok(warnings[0].includes('Surse HTML eșuate: 1'));
const items=sourceFreshnessWarningItems({mod:'local_readonly',
 surse:{ue:{stare:'lipsa',metrici:{acte:{stare:'indisponibil',valoare:null}}}},
 limitari:[]});
assert.equal(items[0].key,'corpus');
assert.ok(items.some(item=>item.key==='ue'&&item.action.includes('CELEX')));
const panel=sourceFreshnessPanelHtml({mod:'local_readonly',surse:{corpus:{stare:'disponibil',
 metrici:{acte:{stare:'masurat',valoare:1}}},
 initiative:{stare:'disponibil',metrici:{initiative:{stare:'masurat',valoare:1}}},
 ue:{stare:'disponibil',metrici:{acte:{stare:'masurat',valoare:1}}},
 importuri:{stare:'disponibil',metrici:{versiuni:{stare:'masurat',valoare:1}}}}});
assert.ok(panel.includes('id="dossier-source-warning"'));
assert.ok(panel.includes('source-freshness-ok'));
assert.ok(panel.includes('Sursele locale par utilizabile'));
const warningPanel=sourceFreshnessPanelHtml({mod:'local_readonly',surse:{corpus:{stare:'partial',
 metrici:{acte:{stare:'masurat',valoare:1},surse_esuate:{stare:'masurat',valoare:1}}}}});
assert.ok(warningPanel.includes('data-source-note="0"'));
const note=manualNoteFromSourceWarning({key:'ue',label:'Drept UE',
 message:'UE lipsă',action:'Importă CELEX'});
assert.equal(note.type,'risc_ue');
assert.equal(note.status,'needs_evidence');
assert.ok(note.reasoning.includes('CELEX'));
assert.ok(sourceFreshnessPanelHtml({mod:'static'}).includes('versiunea statică'));
"""
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_acquisition_renderers_distinguish_states_and_escape_sources():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("const IMPORT_STATES=", 1)[1].split("function acquisitionBusy", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const urlSigur=s=>String(s||'').startsWith('https://')?s:null;"
        "const dossierTime=s=>s,ACQUISITION={selected:'plx-1'};const IMPORT_STATES="
        + source
        + "const row={plx_id:'plx-1',titlu:'<script>',stare:'metadate'};"
        "let h=acquisitionRowHtml(row);assert.ok(h.includes('Doar metadate'));"
        "assert.ok(h.includes('aria-current=\"true\"')&&!h.includes('<script>'));"
        "assert.ok(acquisitionState({...row,stare:'indisponibil'}).includes('indisponibile'));"
        "assert.ok(acquisitionState({...row,ultima_incercare:{stare:'eroare'}}).includes('eșuată'));"
        "h=acquisitionVersionHtml({label:'<img>',status:'ocr_necesar',url:'javascript:alert(1)',"
        "preluat_la:'date',sha256:'<svg>'});"
        "assert.ok(h.includes('OCR')&&h.includes('Limbă: necunoscută'));"
        "assert.ok(!h.includes('<img>')&&!h.includes('<svg>')&&!h.includes('href='));"
        "h=acquisitionAttemptsHtml([{operatie:'importa',stare:'eroare',incercat_la:'date',"
        "reusit_la:null,url:'https://www.cdep.ro/a.pdf',eroare:'<script>'}]);"
        "assert.ok(h.includes('Reîncearcă')&&h.includes('Necunoscută'));"
        "assert.ok(!h.includes('<script>'));"
        "assert.ok(acquisitionAttemptsHtml([]).includes('Nicio încercare'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_lifecycle_renderer_filters_and_opens_project_sources():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("const PROJECT_WATCH_KEY=", 1)[1].split("const ACQUISITION=", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const urlSigur=s=>String(s||'').startsWith('https://')?s:null;"
        "const SOURCE_STATE_LABELS={changed:'Schimbată',needs_review:'Necesită revizie'};"
        "let store={};const localStorage={getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v;}};"
        "const dossierTime=s=>s;const PROJECT_WATCH_KEY="
        + source
        + "const base={project_id:'PL-x 1',title:'<script>',source_name:'Camera',"
        "source_state:'ok',needs_attention:false,last_seen:'2026-09-10',"
        "last_updated:'2026-09-10',url:'https://www.cdep.ro/p',stage:{label:'Raport depus'}};"
        "assert.ok(lifecycleListHtml({projects:[base]},'watched')"
        ".includes('Niciun proiect urmărit'));"
        "projectWatchToggle('PL-x 1');"
        "assert.ok(projectWatched('PL-x 1'));"
        "assert.ok(lifecycleListHtml({projects:[base]},'watched').includes('Nu mai urmări'));"
        "let h=lifecycleListHtml({projects:[base,{...base,project_id:'PL-x 2',"
        "source_state:'stale',needs_attention:true,registry_source_state:'changed',"
        "registry_needs_attention:true,registry_can_sync:true,registry_source_id:'src_1',"
        "registry_source:{last_attempt_at:'now'}}]},'attention');"
        "assert.ok(h.includes('PL-x 2')&&!h.includes('PL-x 1'));"
        "assert.ok(h.includes('Sursă urmărită: Schimbată'));"
        "assert.ok(h.includes('Sincronizează sursa urmărită'));"
        "assert.ok(h.includes('Revizuiește sursa'));"
        "assert.ok(h.includes('Urmărește'));"
        "assert.ok(h.includes('data-lifecycle-open=\"0\"'));"
        "assert.ok(h.includes('data-lifecycle-sync-source=\"0\"'));"
        "assert.ok(h.includes('data-lifecycle-review-source=\"0\"'));"
        "const review=lifecycleSourceReviewHtml({...base,project_id:'PL-x 2',"
        "registry_source_state:'changed',registry_can_sync:true,registry_source_id:'src_1',"
        "registry_source:{identifier:'PL-x 2',url:'https://www.cdep.ro/p2',"
        "label:'Fișă proiect',last_attempt_at:'now',last_hash:'a'.repeat(64),"
        "parser_version:'v1'}});"
        "assert.ok(review.includes('Revizie sursă · PL-x 2'));"
        "assert.ok(review.includes('amprentă diferită'));"
        "assert.ok(review.includes('Deschide sursa oficială'));"
        "assert.ok(review.includes('Notează în dosar'));"
        "assert.ok(review.includes('Marchează revizuită'));"
        "assert.ok(review.includes('data-source-affected-runs'));"
        "const affected=lifecycleAffectedRunsHtml({total:1,rulari:[{dosar_titlu:'Dosar <x>',"
        "dosar_id:'d1',rulare_id:'r1',rulare_creata_la:'2026-09-12',"
        "engine_version:'matrice-proiecte-v1',pot_recalcula:true,potriviri:[{"
        "motiv:'dependență capturată în dovezi',versiune_id:'b'.repeat(64)}]}]});"
        "assert.ok(affected.includes('Dosar &lt;x&gt;'));"
        "assert.ok(affected.includes('data-affected-open=\"0\"'));"
        "assert.ok(affected.includes('data-affected-rerun=\"0\"'));"
        "assert.ok(lifecycleAffectedRunsHtml({total:0,rulari:[]}).includes('Niciun dosar salvat'));"
        "assert.equal(lifecycleSourceNote({project_id:'PL-x 2',title:'Titlu',"
        "status:'În lucru',registry_source_state:'changed',registry_source:{"
        "url:'https://www.cdep.ro/p2',last_hash:'a'.repeat(64)}}).type,'necorelare');"
        "assert.ok(!h.includes('<script>'));"
        "h=lifecycleListHtml({projects:[{...base,source_state:'unknown',"
        "needs_attention:true,stage:{key:'unknown',label:'Etapă nouă'}}]},'unknown');"
        "assert.ok(h.includes('Etapă necunoscută'));"
        "assert.deepEqual(lifecycleCounts({projects:[base,{...base,project_id:'PL-x 2',"
        "source_state:'stale',needs_attention:true,stale:true,registry_needs_attention:true}]}),"
        "{watched:1,attention:1,stale:1,unknown:0,registry:1});"
        "assert.ok(lifecycleListHtml({projects:[base]},'stale').includes('Niciun proiect'));"
        "fetch=async url=>({ok:true,json:async()=>({projects:String(url).includes('PL-x+2')?"
        "[{...base,project_id:'PL-x 2'}]:[]})});"
        "projectWatchSave(['PL-x 2','PL-x 3']);"
        "lifecycleWatchedData().then(d=>{assert.equal(d.projects.length,2);"
        "assert.equal(d.projects[1].source_state,'unavailable');}).catch(e=>{throw e;});"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_registry_renderer_escapes_and_labels_states():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("const SOURCE_REGISTRY=", 1)[1].split("const PROJECT_WATCH_KEY=", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');const dossierTime=s=>s;"
        "const select={innerHTML:''};const node={innerHTML:'',querySelector:()=>select,"
        "querySelectorAll:()=>[],reset:()=>{},value:''};"
        "const $=()=>node;const SOURCE_REGISTRY="
        + source
        + "const h=sourceRegistryRowHtml({id:'src_1',family:'ue_cellar',"
        "identifier:'32014L0024',url:'https://example.test/?q=<x>',label:'<script>',"
        "state:'changed',last_attempt_at:'now',last_hash:'a'.repeat(64),last_error:'<img>',"
        "attempts:[{attempted_at:'later',state:'failed',error_category:'fetch_failed',"
        "note:'<bad>'}]},"
        "{ue_cellar:'Drept UE'});"
        "assert.ok(h.includes('Schimbată'));"
        "assert.ok(h.includes('Drept UE'));"
        "assert.ok(h.includes('data-source-queue=\"src_1\"'));"
        "assert.ok(h.includes('data-source-sync=\"src_1\"'));"
        "assert.ok(h.includes('data-source-open-eu=\"32014L0024\"'));"
        "assert.ok(h.includes('data-source-review=\"src_1\"'));"
        "assert.ok(h.includes('Ultimele încercări')&&h.includes('fetch_failed'));"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>')&&!h.includes('<x>'));"
        "assert.ok(!h.includes('<bad>'));"
        "const p=sourceRegistryRowHtml({id:'src_3',family:'parlament',identifier:'PL-x 1/2024',"
        "url:'',label:'Proiect',state:'queued'},{});"
        "assert.ok(p.includes('data-source-sync=\"src_3\"'));"
        "assert.ok(p.includes('data-source-open-project=\"PL-x 1/2024\"'));"
        "assert.ok(p.includes('Sincronizează sursa'));"
        "sourceRegistryConfigure({families:{parlament:'Proiecte'},states:['changed']});"
        "assert.ok(node.innerHTML.includes('value=\"_attention\"'));"
        "assert.ok(!sourceRegistryRowHtml({id:'src_2',family:'ccr',identifier:'d1',"
        "url:'',label:'CCR',state:'queued'},{}).includes('data-source-sync'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


def test_static_worker_explicitly_rejects_source_acquisition():
    source = (Path(__file__).parents[1] / "scripts/construieste_web.py").read_text()
    branch = source.split("elif path == '/api/surse-proiecte':", 1)[1].split("elif path", 1)[0]
    assert "'mod': 'static'" in branch and "'error':" in branch
    eu = source.split("elif path == '/api/ue/surse':", 1)[1].split("elif path", 1)[0]
    assert "'mod': 'static'" in eu and "'error':" in eu


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_source_language_status_and_provenance_renderer():
    source = (Path(__file__).parents[1] / "app/index.html").read_text()
    renderer = source.split("function euSourceLanguage", 1)[1].split(
        "async function euSourceApi", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const acquisitionLink=(u,t)=>esc(t),dossierTime=s=>s;function euSourceLanguage"
        + renderer
        + "assert.equal(euSourceLanguage('RON'),'Română oficială');"
        "assert.ok(euSourceLanguage('ENG').includes('alternativă'));"
        "assert.ok(euSourceStatus({stare:'metadate'}).includes('fără text'));"
        "assert.ok(euSourceStatus({stare:'integritate_invalida'}).includes('neverificabil'));"
        "const h=euSourceMeta({titlu:'<script>',limba:'ENG',citit_la:'now',text_sha256:'<img>'});"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>'));"
        "assert.ok(h.includes('SHA-256 text extras')&&h.includes('alternativă'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)
