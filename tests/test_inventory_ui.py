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
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_coverage_renderer_shows_blockers_and_escapes():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("function sourceCoverageFamilyHtml", 1)[1].split(
        "async function loadSourceCoverage", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');"
        "const SOURCE_STATE_LABELS={failed:'Eșuat',changed:'Schimbată'};"
        "function sourceCoverageFamilyHtml"
        + source
        + "let h=sourceCoverageHtml({status:'blocked',missing_required:1,"
        "attention_sources:2,projects:{total:3,stale:1,unknown:1,unavailable:0,"
        "stages:{unknown:{label:'Etapă <nouă>',total:1}}},families:[{family:'camera',"
        "label:'Camera <x>',required:true,total:2,attention:1,status:'attention',"
        "states:{failed:1,changed:1}}],blockers:[{kind:'x',message:'Lipsă <script>'}],"
        "limitari:['Doar local <img>']});"
        "assert.ok(h.includes('Acoperire incompletă'));"
        "assert.ok(h.includes('Camera &lt;x&gt;'));"
        "assert.ok(h.includes('Eșuat: 1'));"
        "assert.ok(h.includes('Lipsă &lt;script&gt;'));"
        "assert.ok(h.includes('Etapă &lt;nouă&gt;'));"
        "assert.ok(h.includes('Ce trebuie făcut pentru acoperire utilizabilă'));"
        "assert.ok(h.includes('Deschide registrul surselor'));"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>'));"
        "h=sourceCoverageHtml({status:'blocked',missing_required:1,attention_sources:1,"
        "projects:{total:2,stale:1,unknown:1,unavailable:1,stages:{}},families:[],"
        "portfolio:{monitorul_oficial_policy:{part_i:'ingest',part_ii:'metadata_or_selective',"
        "parts_iii_vii:'do_not_full_ingest_by_default',local:'registry_first_opt_in_packs'},"
        "storage_estimates:{v1:{gb_min:55,gb_max:310,r2_standard_usd_month_min:0.68,"
        "r2_standard_usd_month_max:4.5}},families:[{key:'consultare_econsultare',"
        "label:'E-Consultare <x>',priority:4,tier:'required',"
        "ingest_policy:'metadata_first_documents_on_demand',first_slice:'deadline <b>',"
        "rough_gb_min:5,rough_gb_max:40,coverage_status:'missing',tracked_sources:0,"
        "attention_sources:0},{key:'monitorul_oficial_local',label:'MO Local',priority:11,"
        "tier:'deferred',ingest_policy:'registry_then_opt_in_packs',first_slice:'UAT registry',"
        "rough_gb_min:100,rough_gb_max:2000,coverage_status:'missing',tracked_sources:0,"
        "attention_sources:0}]}});"
        "assert.ok(h.includes('Portofoliu surse pentru redactare legislativă'));"
        "assert.ok(h.includes('Necesar acum'));"
        "assert.ok(h.includes('Amânat / opt-in'));"
        "assert.ok(h.includes('E-Consultare &lt;x&gt;'));"
        "assert.ok(h.includes('Metadate întâi, documente la cerere'));"
        "assert.ok(h.includes('nu full-ingest implicit'));"
        "assert.ok(h.includes('55-310 GB'));"
        "assert.ok(!h.includes('<x>')&&!h.includes('<b>'));"
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_registry_renderer_shows_econsultare_snapshot_and_registration_copy():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    assert "URL e-consultare" in html
    assert "https://e-consultare.gov.ro/consultare/" in html
    assert "o singură pagină" in html
    source = html.split("const SOURCE_REGISTRY=", 1)[1].split(
        "async function inspectSourceRegistryRow", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const nf=n=>String(n);"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');"
        "const dossierTime=s=>s;"
        "const SOURCE_REGISTRY=" + source + "const row={id:'src_1',family:'consultare_econsultare',"
        "identifier:'https://e-consultare.gov.ro/consultare/123',"
        "url:'https://e-consultare.gov.ro/consultare/123',"
        "label:'Consultare <script>',state:'changed',last_hash:'a'.repeat(64),"
        "parser_version:'achizitii_econsultare.v1',sync_status:{can_sync:true,"
        "can_queue:true,can_review:true,severity:'attention',next_action:'Verifică pagina'},"
        "impact:{available:true,state:'changed',summary:{affected_dossiers:0,"
        "affected_runs:0,affected_notes:0,affected_rule_drafts:0,"
        "affected_proposals:0,affected_watchlist_items:0},limitari:[]},"
        "attempts:[{attempted_at:'2026-09-12',state:'changed',http_status:200,"
        "content_hash:'a'.repeat(64),parser_version:'achizitii_econsultare.v1',"
        "note:'citit <img>'}],snapshots:[{captured_at:'2026-09-12',"
        "content_hash:'a'.repeat(64),parser_version:'achizitii_econsultare.v1',"
        "summary:{title:'Proiect <b>',authority:'Ministerul Dezvoltării',"
        "deadline:'15.10.2026',status:'open',documents:2,truncated:false}}]};"
        "const families={consultare_econsultare:'Consultări publice · e-consultare'};"
        "let h=sourceRegistryRowHtml(row,families);"
        "assert.ok(h.includes('Consultări publice · e-consultare'));"
        "assert.ok(h.includes('E-Consultare parsată'));"
        "assert.ok(h.includes('Autoritate: Ministerul Dezvoltării'));"
        "assert.ok(h.includes('Termen: 15.10.2026'));"
        "assert.ok(h.includes('Stare: Deschisă'));"
        "assert.ok(h.includes('2 atașamente'));"
        "assert.ok(h.includes('Sincronizează sursa'));"
        "assert.ok(h.includes('Inspectează impactul și datele'));"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>'));"
        "h=sourceRegistryDetailHtml(row,families);"
        "assert.ok(h.includes('Date parsate E-Consultare'));"
        "assert.ok(h.includes('Atașamente detectate'));"
        "assert.ok(h.includes('Titlu pagină'));"
        "assert.ok(h.includes('Proiect &lt;b&gt;'));"
        "assert.ok(h.includes('HTTP 200'));"
        "assert.ok(!h.includes('<b>')&&!h.includes('<img>'));"
        "assert.equal(sourceRegistryConsultationStatus('closed'),'Închisă');"
        "assert.equal(sourceRegistryConsultationStatus('missing'),'missing');"
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_acceptance_dashboard_renderer_shows_finish_state():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("function acceptanceDashboardHtml", 1)[1].split(
        "function sourceCoverageHtml", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');"
        "function acceptanceDashboardHtml"
        + source
        + "const h=acceptanceDashboardHtml({sections:[{key:'eu',label:'Drept UE',"
        "status:'attention',summary:'not_imported_8_of_8 <x>',"
        "metrics:{referenced:8,imported_text:0}}],capability_summary:{ready:1,partial:7,missing:0},"
        "capabilities:[{label:'Law as code',state:'partial',evidence:'draft rule <x>'}],"
        "limitari:['Nu reconstruiește']});"
        "assert.ok(h.includes('Stadiu finalizare'));"
        "assert.ok(h.includes('Drept UE'));"
        "assert.ok(h.includes('Law as code'));"
        "assert.ok(h.includes('parțial'));"
        "assert.ok(h.includes('imported_text: 0'));"
        "assert.ok(!h.includes('<x>'));"
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_operational_tracker_renderers_show_actions_filters_and_public_feed():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    assert "tracker-event-type" in html
    assert "tracker-source-family" in html
    assert "econsultare-feed" in html
    assert "monitor-reconciliation-refresh" in html
    source = html.split("function monitorReconciliationHtml", 1)[1].split(
        "$('#source-coverage').ontoggle", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');"
        "const dossierTime=s=>s;"
        "const urlSigur=s=>String(s||'').startsWith('https://')?s:null;"
        "function sourceRegistryConsultationStatus(value){const labels={open:'Deschisă',"
        "closed:'Închisă',unknown:'Necunoscută'};return labels[value]||value||'Necunoscută';}"
        "async function sourceRegistryApi(){return {};}"
        "function inspectSourceRegistryRow(){}function openTrackerTimeline(){}"
        "function monitorReconciliationHtml"
        + source
        + "let h=monitorReconciliationHtml({needs_review:1,total:2,"
        "counts:{missing_monitor_number:1},"
        "items:[{act_id:'lege <x>',issues:['missing <b>'],metadata:{number:null,date:''},"
        "parsed:{number:10,date:'2026-02-02'},event_available:false}],limitari:['local <img>']});"
        "assert.ok(h.includes('Reconciliere Monitorul Oficial'));"
        "assert.ok(h.includes('lege &lt;x&gt;'));"
        "assert.ok(h.includes('missing &lt;b&gt;'));"
        "assert.ok(!h.includes('<x>')&&!h.includes('<img>'));"
        "h=econsultareFeedHtml({items:[{source_id:'src1',identifier:'PL-x 1/2026',"
        "title:'Consultare <b>',label:'Fallback',status:'open',authority:'MDLPA',"
        "deadline:'2026-10-01',documents:2,state:'changed',snapshot_at:'2026',"
        "url:'javascript:alert(1)',needs_attention:true}]});"
        "assert.ok(h.includes('Consultare &lt;b&gt;'));"
        "assert.ok(h.includes('Deschisă'));"
        "assert.ok(h.includes('Sincronizează sursa'));"
        "assert.ok(h.includes('Timeline'));"
        "assert.ok(!h.includes('href=')&&!h.includes('<b>'));"
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_tracker_timeline_renderer_exposes_review_and_note_actions():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("const TRACKER_TIMELINE=", 1)[1].split("const ACQUISITION=", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');"
        "const dossierTime=s=>s;"
        "const urlSigur=s=>String(s||'').startsWith('https://')?s:null;"
        "const TRACKER_TIMELINE="
        + source
        + "const h=trackerTimelineHtml({events:[{id:'ev1',event_type:'committee_assignment',"
        "event_label:'Aviz comisie',project_id:'PL-x 1/2026',dossier_id:'dosar1',"
        "source_family:'camera',source_url:'https://www.cdep.ro/',occurred_at:'2026-09-12',"
        "title:'Titlu <b>',payload:{committee:'Comisie <x>'},review:{reviewed:false}}],"
        "total:1,limitari:['local <img>']});"
        "assert.ok(h.includes('data-tracker-note-event=\"ev1\"'));"
        "assert.ok(h.includes('data-tracker-review-event=\"ev1\"'));"
        "assert.ok(h.includes('Nerevizuit'));"
        "assert.ok(h.includes('Comisie &lt;x&gt;'));"
        "assert.ok(!h.includes('<b>')&&!h.includes('<img>'));"
        "const params=trackerTimelineParams(10);"
        "assert.equal(params.limit,'50');"
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


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
        "last_updated:'2026-09-10',url:'https://www.cdep.ro/p',"
        "stage:{key:'report',label:'Raport depus'},"
        "stage_date:'2026-09-08',latest_event:{action:'Raport depus <img>',"
        "camera:'Camera Deputaților',date:'2026-09-08',source_name:'Camera'},"
        "uncertainty:{level:'low',reasons:[],message:'Stadiu citit din sursa locală.'}};"
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
        "assert.ok(h.includes('lifecycle-timeline'));"
        "assert.ok(h.includes('data-stage=\"report\"'));"
        "assert.ok(h.includes('Stadiu la: 2026-09-08'));"
        "assert.ok(h.includes('Ultimul eveniment: Raport depus &lt;img&gt;'));"
        "assert.ok(h.includes('Incertitudine scăzută'));"
        "assert.ok(h.includes('Sincronizează sursa urmărită'));"
        "assert.ok(h.includes('Revizuiește sursa'));"
        "assert.ok(h.includes('Urmărește'));"
        "assert.ok(h.includes('Pregătește dosar'));"
        "assert.ok(h.includes('data-lifecycle-dossier=\"0\"'));"
        "assert.ok(h.includes('data-lifecycle-open=\"0\"'));"
        "assert.ok(h.includes('data-lifecycle-sync-source=\"0\"'));"
        "assert.ok(h.includes('data-lifecycle-review-source=\"0\"'));"
        "h=lifecycleListHtml({projects:[base,{...base,project_id:'PL-x 3',"
        "affected_dossiers:2}]},'affected');"
        "assert.ok(h.includes('PL-x 3')&&!h.includes('PL-x 1'));"
        "assert.ok(h.includes('2 dosare afectate'));"
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
        "assert.ok(review.includes('data-review-source-note'));"
        "assert.ok(lifecycleReviewSummary({project_id:'PL-x 2'},{total:0})"
        ".includes('niciun dosar'));"
        "assert.ok(lifecycleReviewSummary({project_id:'PL-x 2'},{total:2}).includes('2 dosar'));"
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
        "h=lifecycleListHtml({projects:[{...base,source_state:'unavailable',"
        "needs_attention:true,unavailable:true,stage:{label:'Sursă indisponibilă'},"
        "url:''}]},'unavailable');"
        "assert.ok(h.includes('Sursă indisponibilă'));"
        "assert.deepEqual(lifecycleCounts({projects:[base,{...base,project_id:'PL-x 2',"
        "source_state:'stale',needs_attention:true,stale:true,registry_needs_attention:true,"
        "affected_dossiers:1},{...base,project_id:'PL-x 3',source_state:'unavailable',"
        "needs_attention:true,unavailable:true}]}),{watched:1,attention:2,stale:1,"
        "unknown:0,unavailable:1,registry:1,affected:1});"
        "const overview=lifecycleOverviewHtml({returned:3,total:9,projects:[base,{...base,"
        "project_id:'PL-x 2',source_state:'stale',needs_attention:true,stale:true,"
        "registry_needs_attention:true,registry_source_state:'changed',uncertainty:{level:'medium',"
        "reasons:['tracked_source_needs_review'],message:'Verifică sursa oficială.'}}]});"
        "assert.ok(overview.includes('Necesită atenție'));"
        "assert.ok(overview.includes('PL-x 2'));"
        "assert.ok(overview.includes('tracked_source_needs_review'));"
        "assert.ok(lifecycleListHtml({projects:[base]},'stale').includes('Niciun proiect'));"
        "fetch=async url=>({ok:true,json:async()=>({projects:String(url).includes('PL-x+2')?"
        "[{...base,project_id:'PL-x 2'}]:[]})});"
        "projectWatchSave(['PL-x 2','PL-x 3']);"
        "lifecycleWatchedData().then(d=>{assert.equal(d.projects.length,2);"
        "assert.equal(d.projects[1].source_state,'unavailable');}).catch(e=>{throw e;});"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_matrix_graph_renderer_labels_scaffold_edges_and_drilldowns():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("function mActiuni", 1)[1].split("async function mArataActe", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;')"
        ".replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const nf=n=>String(n);"
        "const locRo=s=>'Loc '+s;"
        "const urlSigur=s=>String(s||'').startsWith('https://')?s:null;"
        "function mActiuni"
        + source
        + "const data={acte_selectate:1,acte_total:3,graph_state:'indisponibil',"
        "trunchiat:true,limitari:['nu verdict <script>'],nodes:[{act_id:'lege-1',"
        "cheie_citare:'Legea 1/2024',titlu:'Titlu <bad>',emitent:'Parlamentul',"
        "an:2024,rang:{eticheta:'primar'},domeniu:{eticheta:'achiziții'},"
        "sursa_url:'javascript:alert(1)',source_quality:{eticheta:'Sursă indisponibilă'}}],"
        "edges:[{status:'relatie_candidata_neconfirmata',fel:'modifica',"
        "incredere:0.72,de_la:'2024-01-01',from:{act_id:'lege-1',locator:'art1',"
        "actiuni:[{fel:'prevedere',act_id:'lege-1',locator:'art1',eticheta:'Text sursă'}]},"
        "to:{act_id:'lege-2',locator:'art2',actiuni:[{fel:'prevedere',act_id:'lege-2',"
        "locator:'art2',eticheta:'Text țintă'}]}}]};"
        "const h=mGraphHtml(data);"
        "assert.ok(h.includes('Graf matrice · scaffold law-as-code'));"
        "assert.ok(h.includes('nu verdict juridic'));"
        "assert.ok(h.includes('Baza locală de graf este indisponibilă'));"
        "assert.ok(h.includes('Sursă indisponibilă'));"
        "assert.ok(h.includes('relatie_candidata_neconfirmata'));"
        "assert.ok(h.includes('încredere: 0.72'));"
        "assert.ok(h.includes('data-act=\"lege-1\"'));"
        "assert.ok(h.includes('data-act=\"lege-2\"'));"
        "assert.ok(h.includes('Rezultat parțial'));"
        "assert.ok(!h.includes('<script>')&&!h.includes('<bad>')&&!h.includes('javascript:'));"
        "assert.ok(mGraphHtml({acte_selectate:0,acte_total:0,nodes:[],edges:[]})"
        ".includes('Niciun act selectat'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_source_registry_renderer_escapes_and_labels_states():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("const SOURCE_REGISTRY=", 1)[1].split("const PROJECT_WATCH_KEY=", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')"
        ".replaceAll('>','&gt;');const dossierTime=s=>s;const nf=String;"
        "const select={innerHTML:''};const node={innerHTML:'',querySelector:()=>select,"
        "querySelectorAll:()=>[],reset:()=>{},value:''};"
        "const $=()=>node;const SOURCE_REGISTRY="
        + source
        + "const h=sourceRegistryRowHtml({id:'src_1',family:'ue_cellar',"
        "identifier:'32014L0024',url:'https://example.test/?q=<x>',label:'<script>',"
        "state:'changed',last_attempt_at:'now',last_hash:'a'.repeat(64),last_error:'<img>',"
        "sync_status:{can_sync:true,can_queue:true,can_review:true,severity:'attention',"
        "next_action:'Revizuiește impactul'},impact:{available:true,state:'changed',"
        "summary:{affected_dossiers:1,affected_runs:0,affected_notes:2,"
        "affected_rule_drafts:1,affected_proposals:0,affected_watchlist_items:1},"
        "samples:{},limitari:['local only']},"
        "attempts:[{attempted_at:'later',state:'failed',error_category:'fetch_failed',"
        "note:'<bad>'}]},"
        "{ue_cellar:'Drept UE'});"
        "assert.ok(h.includes('Schimbată'));"
        "assert.ok(h.includes('Drept UE'));"
        "assert.ok(h.includes('data-source-queue=\"src_1\"'));"
        "assert.ok(h.includes('data-source-sync=\"src_1\"'));"
        "assert.ok(h.includes('data-source-inspect=\"src_1\"'));"
        "assert.ok(h.includes('data-source-open-eu=\"32014L0024\"'));"
        "assert.ok(h.includes('data-source-review=\"src_1\"'));"
        "assert.ok(h.includes('Revizuiește impactul'));"
        "assert.ok(h.includes('Impact local: 1 dosare'));"
        "assert.ok(h.includes('2 note'));"
        "assert.ok(h.includes('Inspectează impactul'));"
        "assert.ok(h.includes('Ultimele încercări')&&h.includes('fetch_failed'));"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>')&&!h.includes('<x>'));"
        "assert.ok(!h.includes('<bad>'));"
        "const detail=sourceRegistryDetailHtml({id:'src_1',family:'ue_cellar',"
        "identifier:'32014L0024',url:'https://example.test',label:'Directiva',"
        "state:'changed',last_hash:'b'.repeat(64),parser_version:'achizitii_ue.v1',"
        "sync_status:{next_action:'Revizuiește dosarele'},attempts:[{"
        "attempted_at:'later',state:'changed',http_status:200,content_hash:'b'.repeat(64),"
        "note:'importat'}],impact:{available:true,state:'changed',summary:{affected_dossiers:1,"
        "affected_runs:1,affected_notes:1,affected_rule_drafts:1,affected_proposals:1,"
        "affected_watchlist_items:1},samples:{runs:[{dosar_titlu:'D',rulare_creata_la:'now',"
        "potriviri:[{motiv:'proiect selectat'}]}],notes:[{dosar_titlu:'D',titlu:'N',"
        "stare:'draft'}],"
        "rule_drafts:[{dosar_titlu:'D',act_id:'32014L0024',locator:'art1',id:'r'}],"
        "proposals:[{dosar_titlu:'D',titlu:'P',revizie:1}],watchlist:[{titlu:'D',tip:'celex',"
        "valoare:'32014L0024'}]},limitari:['nu reconsultă']}}"
        ",{ue_cellar:'Drept UE'});"
        "assert.ok(detail.includes('data-source-detail'));"
        "assert.ok(detail.includes('Impact local pentru revizie'));"
        "assert.ok(detail.includes('Ciorne de reguli afectate'));"
        "assert.ok(detail.includes('Istoric sync pentru această sursă'));"
        "assert.ok(detail.includes('achizitii_ue.v1'));"
        "assert.ok(sourceRegistryOutcome({state:'fetched',last_hash:'b'.repeat(64)})"
        ".includes('Sursa a fost citită'));"
        "assert.ok(sourceRegistryOutcome({state:'unchanged'}).includes('același'));"
        "assert.ok(sourceRegistryOutcome({state:'changed'}).includes('diferă'));"
        "assert.ok(sourceRegistryOutcome({state:'failed',last_error:'fetch_failed'})"
        ".includes('se poate reîncerca'));"
        "assert.ok(sourceRegistryOutcome({state:'unavailable'}).includes('lipsește'));"
        "assert.ok(sourceRegistryOutcome({state:'rate_limited'}).includes('mai târziu'));"
        "assert.ok(sourceRegistryOutcome({state:'needs_review'}).includes('nu poate actualiza'));"
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
    result = subprocess.run(["node", "-e", program], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


def test_static_worker_explicitly_rejects_source_acquisition():
    source = (Path(__file__).parents[1] / "scripts/construieste_web.py").read_text()
    branch = source.split("elif path == '/api/surse-proiecte':", 1)[1].split("elif path", 1)[0]
    assert "'mod': 'static'" in branch and "'error':" in branch
    eu = source.split("elif path == '/api/ue/surse':", 1)[1].split("elif path", 1)[0]
    assert "'mod': 'static'" in eu and "'error':" in eu
    mcp = source.split("elif path == '/api/mcp/preview':", 1)[1].split("elif path", 1)[0]
    assert "'mod': 'static'" in mcp and "'error':" in mcp


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_source_language_status_and_provenance_renderer():
    source = (Path(__file__).parents[1] / "app/index.html").read_text()
    renderer = source.split("function euSourceLanguage", 1)[1].split(
        "async function euSourceApi", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "const acquisitionLink=(u,t)=>esc(t),dossierTime=s=>s,nf=n=>String(n);"
        "function euSourceLanguage"
        + renderer
        + "assert.equal(euSourceLanguage('RON'),'Română oficială');"
        "assert.ok(euSourceLanguage('ENG').includes('alternativă'));"
        "assert.ok(euSourceStatus({stare:'metadate'}).includes('fără text'));"
        "assert.ok(euSourceStatus({stare:'integritate_invalida'}).includes('neverificabil'));"
        "const h=euSourceMeta({titlu:'<script>',limba:'ENG',citit_la:'now',text_sha256:'<img>'});"
        "assert.ok(!h.includes('<script>')&&!h.includes('<img>'));"
        "assert.ok(h.includes('Source hash')&&h.includes('SHA-256 text extras')"
        "&&h.includes('alternativă'));"
        "const a=euSourceArticleSummary({total:1,randuri:["
        "{locator:'art<script>',titlu:'T<img>',sha256:'abc'}]});"
        "assert.ok(a.includes('1 articole delimitate')&&!a.includes('<script>')"
        "&&!a.includes('<img>'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_source_import_ui_uses_identifier_url_and_import_endpoint():
    source = (Path(__file__).parents[1] / "app/index.html").read_text()
    renderer = source.split("function euSourceIdentifierCelex", 1)[1].split(
        "async function openEuSource", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        "let calls=[];fetch=async(url,opts)=>{calls.push({url,opts});"
        "return {ok:true,json:async()=>({ok:true})};};"
        "function euSourceIdentifierCelex" + renderer + "assert.equal(euSourceIdentifierCelex("
        "'https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024'),"
        "'32014L0024');"
        "assert.equal(euSourceIdentifierCelex('celex:32018R1805'),'32018R1805');"
        "assert.throws(()=>euSourceIdentifierCelex('not a celex'));"
        "(async()=>{await euSourceApi({celex:'32014L0024'});"
        "await euSourceApi(null,{identifier:'https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024',limbi:'ENG,RON'});"
        "assert.equal(calls[0].url,'/api/ue/surse?celex=32014L0024');"
        "assert.equal(calls[1].url,'/api/ue/import');"
        "assert.deepEqual(JSON.parse(calls[1].opts.body),{identifier:"
        "'https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024',"
        "limbi:'ENG,RON'});})();"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_eu_issue_note_builder_renderer_escapes_sources_and_blockers():
    source = (Path(__file__).parents[1] / "app/index.html").read_text()
    renderer = source.split("const EU_ISSUE_STATES", 1)[1].split(
        "function manualNoteSummaryHtml", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');"
        'const acquisitionLink=(u,t)=>`<a href="${esc(u)}">${esc(t)}</a>`;'
        "const ueLimitariHtml=lim=>lim.map(x=>esc(x)).join('|');"
        "const MANUAL_NOTE_STATUS={needs_evidence:'Necesită dovezi',"
        "ready_for_review:'Pregătită pentru revizie',reviewed:'Revizuită'};"
        "const EU_ISSUE_STATES" + renderer + "const form=euIssueNoteBuilderHtml();"
        "assert.ok(form.includes('data-eu-issue-form'));"
        "assert.ok(form.includes('data-eu-issue-import'));"
        "assert.ok(form.includes('CELEX sau URL oficial'));"
        "assert.ok(form.includes('name=\"limbi\"'));"
        "const html=euIssuePreviewHtml({issue_state:'possible_gap',base_sha256:'<hash>',"
        "blockers:[{side:'eu',code:'missing<img>'}],limitari:['lim<script>'],base:{"
        "legal_effect:'unknown',national_evidence:{kind:'prevedere',title:'<RO>',"
        "language:'RON',locator:'art1',text_sha256:'abc',quote:'text <b>'},"
        "eu_evidence:{kind:'eu_article',title:'<UE>',language:'RON',locator:'art2',"
        "text_sha256:'def',article_sha256:'ghi',source_url:'https://example.test',"
        "quote:'ue <i>'}}});"
        "assert.ok(html.includes('Lacună posibilă'));"
        "assert.ok(html.includes('UE · missing&lt;img&gt;'));"
        "assert.ok(!html.includes('<script>')&&!html.includes('<img>')&&!html.includes('<RO>'));"
        "const saved=euIssueSavedHtml({id:'n1',title:'Risc <b>',proposal_context:{"
        "contract:'ro-eu-proposal-context-v1',legal_effect:'unknown',issue_state:'possible_conflict',"
        "note_id:'n1',note_title:'Risc <b>'}});"
        "assert.ok(saved.includes('context pentru propunere'));"
        "assert.ok(saved.includes('ro-eu-proposal-context-v1'));"
        "assert.ok(saved.includes('data-eu-issue-copy-context'));"
        "assert.ok(!saved.includes('Risc <b>'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)
