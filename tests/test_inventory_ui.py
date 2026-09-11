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
