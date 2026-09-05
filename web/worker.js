
importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js");
let raspunde, cautaJson;
async function boot(){
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("sqlite3");  // unvendored in Pyodide; the corpus is SQLite
  const zip = await fetch("bundle.zip").then(r=>r.arrayBuffer());
  pyodide.unpackArchive(zip, "zip");
  for (const name of ["corpus.db","initiative.db","graf.db"]) {
    const buf = new Uint8Array(await fetch("data/"+name).then(r=>r.arrayBuffer()));
    pyodide.FS.writeFile(name, buf);
  }
  raspunde = pyodide.runPython(`
import sys, json
if '.' not in sys.path: sys.path.insert(0, '.')
from urllib.parse import parse_qs
from scripts.servicii import (Stare, rezumat, _lint, _cauta, _vecini,
                              _redacteaza, _sugereaza, _consolidat)
_stare = Stare('corpus.db', 'initiative.db', 'graf.db')
def _raspunde(path, query, body):
    qs = parse_qs(query or '')
    if path == '/api/rezumat': out = rezumat(_stare)
    elif path == '/api/cauta': out = _cauta(qs.get('q',[''])[0], _stare)
    elif path == '/api/vecini':
        a = qs.get('act',[''])[0]; out = _vecini(a, _stare) if a else {'error':'act lipsă'}
    elif path == '/api/redacteaza': out = _redacteaza(qs)
    elif path == '/api/sugereaza': out = _sugereaza(qs)
    elif path == '/api/consolidat': out = _consolidat(qs)
    elif path == '/api/lint':
        draft = (json.loads(body or '{}').get('draft') or '').strip()
        out = _lint(draft, _stare) if draft else {'error':'draft gol'}
    else: out = {'error':'not found'}
    return json.dumps(out, ensure_ascii=False)
_raspunde
  `);
  // Search is async (it fetches index/act shards on demand), so it is a separate coroutine.
  cautaJson = pyodide.runPython(`
import json as _json
from scripts.cauta_web import cauta as _cauta_shard
async def _cauta_json(q):
    return _json.dumps(await _cauta_shard(q, 'data'), ensure_ascii=False)
_cauta_json
  `);
}
const gata = boot().then(()=>postMessage({type:"ready"}))
                   .catch(e=>{ postMessage({type:"error", error:String(e)}); throw e; });
onmessage = async (e) => {
  const {id, path, query, body} = e.data;
  try {
    await gata;
    const res = (path === "/api/cauta")
      ? await cautaJson(new URLSearchParams(query).get("q") || "")
      : raspunde(path, query, body);
    postMessage({id, ok:true, result:res});
  } catch(err){
    postMessage({id, ok:false, error:String(err)});
  }
};
