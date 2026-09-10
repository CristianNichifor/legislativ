"""Everyday dossier storage, recovery and schema-8 upgrade contracts."""

import shutil
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_dosare import ID, OTHER, create, request

from scripts import dosare


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def test_rename_archive_restore_and_creation_retry(state):
    path = dosare.cale(state)
    create(state)
    change = {"id": ID, "titlu": "Renamed", "arhivat": True, "revizie": 0}
    archived = dosare.modifica(path, change)
    assert archived["arhivat"] and archived["revizie"] == 1
    assert dosare.modifica(path, change) == archived
    assert create(state)["titlu"] == "Renamed"
    assert dosare.lista(path)["total"] == 0
    assert dosare.lista(path, stare="arhivate")["dosare"][0]["id"] == ID
    assert dosare.lista(path, stare="toate")["total"] == 1
    with pytest.raises(ValueError, match="modificat"):
        dosare.modifica(path, {**change, "titlu": "Stale"})
    restored = dosare.modifica(path, {**change, "arhivat": False, "revizie": 1})
    assert not restored["arhivat"] and restored["revizie"] == 2
    assert dosare.lista(path)["total"] == 1
    assert dosare.lista(path, stare="arhivate")["total"] == 0


def editor(text="unfinished", revision=0):
    return {
        "id": "editor",
        "dosar_id": None,
        "revizie": revision,
        "continut": {"versiune": 1, "text": text},
    }


def test_recovery_durable_retry_conflicts_delete_and_backup(state, tmp_path):
    path = dosare.cale(state)
    assert dosare.citeste_ciorna(path, "editor")["continut"] is None
    assert not path.exists()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dosare.salveaza_ciorna(path, editor()), range(2)))
    assert results[0] == results[1]
    assert results[0]["revizie"] == 1
    with pytest.raises(ValueError, match="modificată"):
        dosare.salveaza_ciorna(path, editor("stale"))
    copy = tmp_path / "backup.db"
    dosare.backup(path, copy)
    deleted = dosare.salveaza_ciorna(path, {**editor(revision=1), "continut": None})
    assert deleted["revizie"] == 2
    assert dosare.lista_ciorne(path)["total"] == 0
    with pytest.raises(ValueError):
        dosare.salveaza_ciorna(path, editor("resurrect", 1))
    assert dosare.citeste_ciorna(copy, "editor")["continut"]["text"] == "unfinished"


def test_run_recovery_ownership_and_metadata_backup(state, tmp_path):
    path = dosare.cale(state)
    create(state)
    create(state, OTHER)
    run = "c" * 32
    with dosare._open(path, write=True) as con:
        con.execute(
            "INSERT INTO rulari VALUES (?,?,?,?,?,?,?,?)",
            (run, ID, "now", "test", "hash", "{}", "{}", "{}"),
        )
    content = {
        "versiune": 1,
        "drafts": [
            ["proposal:f", {"revision": 3, "values": {"text": "draft"}, "retry": {"id": "d" * 32}}]
        ],
        "transactions": [],
    }
    body = {"id": run, "dosar_id": OTHER, "revizie": 0, "continut": content}
    with pytest.raises(ValueError, match="acest dosar"):
        dosare.salveaza_ciorna(path, body)
    dosare.salveaza_ciorna(path, {**body, "dosar_id": ID})
    assert dosare.citeste_ciorna(path, run)["continut"] == content
    dosare.modifica(path, {"id": ID, "titlu": "Archived", "arhivat": True, "revizie": 0})
    copy = tmp_path / "copy.db"
    dosare.backup(path, copy)
    assert dosare.metadata(copy, ID)["arhivat"]
    assert dosare.lista_ciorne(copy)["ciorne"][0]["titlu"] == "Archived"


@pytest.mark.parametrize("version", range(1, 9))
def test_old_schema_readonly_upgrade_and_rollback(state, version):
    path = dosare.cale(state)
    create(state)
    introduced = {
        9: ["legaturi_ue"],
        8: ["ciorne", "dosare_stare"],
        7: ["analize_propuneri"],
        6: ["interventii_propuneri"],
        5: ["propuneri"],
        4: ["contexte_juridice"],
        3: ["verificari_dovezi", "recalculari"],
        2: ["revizuiri"],
    }
    with sqlite3.connect(path) as con:
        for schema, tables in introduced.items():
            if schema > version:
                for table in tables:
                    con.execute(f"DROP TABLE {table}")
        con.execute(f"PRAGMA user_version={version}")
    before = path.read_bytes()
    assert dosare.metadata(path, ID)["revizie"] == 0
    assert dosare.lista(path, stare="arhivate")["total"] == 0
    assert dosare.citeste_ciorna(path, "editor")["continut"] is None
    assert dosare.lista_ciorne(path)["total"] == 0
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        dosare.modifica(path, {"id": OTHER, "titlu": "Missing", "arhivat": True, "revizie": 0})
    assert path.read_bytes() == before
    dosare.salveaza_ciorna(path, editor())
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == dosare.SCHEMA_VERSION
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert dosare.citeste(path, ID)["titlu"] == "Cercetare"


@pytest.mark.parametrize("route", ["metadate", "ciorne"])
def test_http_local_protections_and_static(state, route):
    url = "/api/dosare/" + route
    for method in ("GET", "POST"):
        assert request(state, method, url, {}, host="evil.test")[0] == 403
        assert request(state, method, url, {}, origin="https://evil.test")[0] == 403
    limit = 210000 if route == "ciorne" else 16000
    assert request(state, "POST", url, {}, length=limit + 1)[0] == 413
    state.date_dir = "static"
    assert request(state, "GET", url)[0] == 400
    assert request(state, "POST", url, editor())[0] == 400


def test_http_recovery_and_bounds(state):
    url = "/api/dosare/ciorne"
    assert request(state, "POST", url, editor())[0] == 200
    assert request(state, "GET", url + "?id=editor")[1]["continut"]["text"] == "unfinished"
    assert request(state, "GET", url)[1]["total"] == 1
    for change in (
        {"revizie": True},
        {"continut": []},
        {"continut": {"versiune": True}},
        {"continut": {"versiune": 1.0}},
        {"id": "../x"},
        {"continut": {"versiune": 1, "text": "x" * 200001}},
    ):
        with pytest.raises(ValueError):
            dosare.salveaza_ciorna(dosare.cale(state), {**editor(), **change})


def test_archived_dossier_rejects_new_runs_until_restored(state, monkeypatch):
    create(state)
    path = dosare.cale(state)
    change = {"id": ID, "titlu": "Cercetare", "arhivat": True, "revizie": 0}
    dosare.modifica(path, change)
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda *args: {"gasit": True})
    body = {"dosar_id": ID, "filtre": {"emitent": "Parlamentul"}}
    with pytest.raises(ValueError, match="arhivat"):
        dosare.salveaza_rulare(state, body)
    assert dosare.rulari(path, ID)["total"] == 0
    dosare.modifica(path, {**change, "arhivat": False, "revizie": 1})
    dosare.salveaza_rulare(state, body)
    assert dosare.rulari(path, ID)["total"] == 1


def test_recovery_library_paginates_without_loading_private_content(state):
    path = dosare.cale(state)
    create(state)
    with dosare._open(path, write=True) as con:
        for number in range(52):
            ident = f"{number:032x}"
            con.execute(
                "INSERT INTO rulari VALUES (?,?,?,?,?,?,?,?)",
                (ident, ID, "now", "test", ident, "{}", "{}", "{}"),
            )
            con.execute(
                "INSERT INTO ciorne VALUES (?,?,?,?,?,?)",
                (ident, ID, ident, '{"versiune":1,"private":"text"}', 1, "now"),
            )
    first, second = dosare.lista_ciorne(path), dosare.lista_ciorne(path, 50)
    assert first["total"] == second["total"] == 52
    assert len(first["ciorne"]) == 50 and len(second["ciorne"]) == 2
    assert not {row["id"] for row in first["ciorne"]} & {row["id"] for row in second["ciorne"]}
    assert "continut" not in first["ciorne"][0]
    assert request(state, "GET", "/api/dosare/ciorne?offset=50")[1] == second
    with pytest.raises(ValueError):
        dosare.lista_ciorne(path, -1)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_recovery_navigation_guard_tracks_edits_and_pending_saves():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("function dossierHasDrafts(){", 1)[1].split(
        "function bindDraftRecovery", 1
    )[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const panel={reviewDrafts:new Map(),reviewTransactions:new Map()},$=()=>panel;"
        "function dossierHasDrafts(){"
        + source
        + """
        assert.equal(dossierHasDrafts(),false);
        panel.reviewDrafts.set('proposal:a',{revision:2,values:{text:'unfinished'}});
        assert.equal(dossierHasDrafts(),true);
        panel.recoveryFingerprint=draftFingerprint(findingDraftSnapshot(panel));
        assert.equal(dossierHasDrafts(),false);
        panel.reviewDrafts.get('proposal:a').values.text='newer';
        assert.equal(dossierHasDrafts(),true);
        panel.recoveryFingerprint=draftFingerprint(findingDraftSnapshot(panel));
        assert.equal(dossierHasDrafts(),false);
        panel.reviewTransactions.set('a',{saving:true});
        panel.recoveryFingerprint=draftFingerprint(findingDraftSnapshot(panel));
        assert.equal(dossierHasDrafts(),true);
        panel.reviewTransactions.clear();panel.reviewDrafts.clear();
        assert.equal(dossierHasDrafts(),false);
        """
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.parametrize("route", ["metadate", "ciorne"])
def test_static_worker_routes_recovery_and_metadata_to_private_workspace(state, route):
    from scripts.browser_workspace import route as browser_route

    state.dosare_db = state.initiative.with_name("browser-private.db")
    state.date_dir = "public-slices"
    create(state)
    body = {"id": ID, "titlu": "Browser dossier", "arhivat": False, "revizie": 0}
    if route == "ciorne":
        body = editor()
    result = browser_route(state, "/api/dosare/" + route, {}, body, "POST")
    assert result["revizie"] == 1
    loaded = browser_route(state, "/api/dosare/" + route, {"id": [body["id"]]}, {}, "GET")
    assert loaded == result
    assert not state.initiative.with_suffix(".dosare.db").exists()


@pytest.mark.parametrize("version", [True, False, 1.0, "1"])
def test_recovery_version_requires_exact_integer_before_storage(state, version):
    with pytest.raises(ValueError, match="Format"):
        dosare.salveaza_ciorna(
            dosare.cale(state),
            {
                **editor(),
                "continut": {"versiune": version, "text": "Draft"},
            },
        )
    assert not dosare.cale(state).exists()


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_restore_rejects_malformed_entries_before_replacing_either_map():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("function restoreFindingDrafts(panel,content){", 1)[1].split(
        "function bindDraftRecovery", 1
    )[0]
    program = (
        r"""
const assert=require('node:assert/strict'),CONTEXT_FIELDS={teritoriu:'Territory'};
const id='a'.repeat(32),key='proposal:'+id;
const valid={versiune:1,drafts:[[key,{revision:2,values:{titlu:'Title',text:'Text',motiv:''},
    interventie:{act_id:'lege-1-2020',sha256_tinta:'hash'},
    retry:{id:'retry',fingerprint:'original'},saving:true}]],
    transactions:[[id,{revision:3,id:'review-retry',fingerprint:'review',saving:true}]]};
"""
        + "function restoreFindingDrafts(panel,content){"
        + source
        + r"""
const bad=[null,{},[],{...valid,versiune:true},
  ...[null,{},[null],[[key]],[[key,null]],[[key,[]]],[[2,{}]],
     [[key,{revision:2,values:{unknown:'breaks namedItem'}}]],
     [[key,{revision:false,values:{}}]],[[key,{revision:2,values:[]}]],
     [[key,{revision:2,values:{},retry:[]}]],
     [[id,{stare:'unreviewed',unknown:'bad field'}]],
     [valid.drafts[0],valid.drafts[0]]].map(drafts=>({...valid,drafts})),
  ...[[null],[[id,null]],[[id,[]]],[[id,{revision:'3'}]],
     [[key,{revision:3}]]].map(transactions=>({...valid,transactions}))];
for(const content of bad){
  const panel={reviewDrafts:new Map([['existing',{motiv:'Keep'}]]),reviewTransactions:new Map()};
  const drafts=panel.reviewDrafts,transactions=panel.reviewTransactions;
  assert.throws(()=>restoreFindingDrafts(panel,content));
  assert.equal(panel.reviewDrafts,drafts);assert.equal(panel.reviewTransactions,transactions);
}
const panel={reviewDrafts:new Map(),reviewTransactions:new Map()};
restoreFindingDrafts(panel,valid);
assert.equal(panel.reviewDrafts.get(key).values.text,'Text');
assert.equal(panel.reviewDrafts.get(key).retry.fingerprint,'original');
assert.equal(panel.reviewTransactions.get(id).revision,3);
assert.equal(panel.reviewDrafts.get(key).saving,undefined);
assert.equal(panel.reviewTransactions.get(id).saving,undefined);
assert.equal(valid.drafts[0][1].saving,true,'validation/restore must not mutate stored copy');
"""
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="Node unavailable")
def test_inflight_recovery_save_does_not_acknowledge_later_mutations():
    html = (Path(__file__).parents[1] / "app/index.html").read_text()
    source = html.split("function dossierHasDrafts(){", 1)[1].split(
        "let editorRecoveryFingerprint=", 1
    )[0]
    program = (
        r"""
const assert=require('node:assert/strict');
const record={revision:0,values:{titlu:'Draft',text:'Before',motiv:''},
              structura:{text_nou:'Before'}};
const panel={reviewDrafts:new Map([['proposal:a',record]]),reviewTransactions:new Map()};
const $=()=>panel,dossierTime=x=>x;
const controls=new Map();
const host={isConnected:true,querySelector:s=>{
  if(!controls.has(s))controls.set(s,{});return controls.get(s);
},querySelectorAll:()=>[]};
let complete,committed;
async function dossierApi(path,body){
  if(!body)return {revizie:0,continut:null};
  committed=JSON.parse(JSON.stringify(body.continut,(_key,value)=>
    value&&typeof value==='object'&&!Array.isArray(value)
      ?Object.fromEntries(Object.keys(value).sort().map(key=>[key,value[key]])):value));
  await new Promise(resolve=>complete=resolve);
  return {revizie:1,continut:committed,modificat_la:'now'};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
"""
        + "function dossierHasDrafts(){"
        + source
        + r"""
(async()=>{
  bindDraftRecovery(host,'run','dossier',()=>findingDraftSnapshot(panel),()=>{},
                    value=>panel.recoveryFingerprint=value);
  await tick();controls.get('[data-draft-save]').onclick();
  record.structura.text_nou='After';record.values.text='After';
  complete();await tick();
  assert.equal(committed.drafts[0][1].structura.text_nou,'Before');
  assert.equal(dossierHasDrafts(),true,'newer edits must remain unpreserved');
  record.structura.text_nou='Before';record.values.text='Before';
  assert.equal(dossierHasDrafts(),false,'exact committed content permits navigation');
  controls.get('[data-draft-save]').onclick();
  committed.drafts[0][1].values.text='Returned committed content';
  complete();await tick();
  assert.equal(dossierHasDrafts(),true,'acknowledge returned content, not the request');
})().catch(error=>{console.error(error);process.exit(1)});
"""
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, timeout=10)
