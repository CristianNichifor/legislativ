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
assert.ok(h.includes('Surse HTML eșuate: 3'));
assert.ok(h.includes('Necesită OCR / verificare: 2'));
assert.ok(h.includes('Stare necunoscută'));
assert.ok(h.includes('Actualitate necunoscută'));
assert.ok(h.includes('&lt;img'));
assert.ok(!h.includes('<img'));
const s=sourceInventoryHtml({mod:'static'});
assert.ok(s.includes('nu este disponibil'));
assert.ok(!s.includes('Acte stocate'));
"""
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, timeout=10)
