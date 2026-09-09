import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import (
    dependente_dovezi,
    dependente_proiecte,
    depozit,
    documente_proiecte,
    dosare,
    revizuiri,
    verificari_dovezi,
)

ID = "a" * 32
URL = "https://www.cdep.ro/proiecte/2026/a.pdf"
HEADER = "Legea nr. 98/2016 se modifică și se completează după cum urmează:\n"
A = HEADER + "1. Articolul 7 se abrogă."
B = HEADER + '1. Articolul 7 se modifică și va avea următorul cuprins: "Text nou."'


def add(state, plx, text, date="2026-01-01", url=URL, data=None, status="extras"):
    data = data if data is not None else b"%PDF-fixture-" + text.encode()
    sha = hashlib.sha256(data).hexdigest()
    ident = hashlib.sha256(json.dumps([plx, url, sha]).encode()).hexdigest()
    with sqlite3.connect(documente_proiecte.cale_store(state)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS documente (id TEXT PRIMARY KEY, plx_id TEXT, "
            "url TEXT, label TEXT, sha256 TEXT, preluat_la TEXT, status TEXT, "
            "text TEXT, octeti BLOB)"
        )
        con.execute(
            "INSERT INTO documente VALUES (?,?,?,?,?,?,?,?,?)",
            (ident, plx, url, "Fixture", sha, date, status, text, data),
        )
    return {"plx_id": plx, "versiune_id": ident}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    state = SimpleNamespace(
        corpus=tmp_path / "corpus.db", initiative=tmp_path / "initiative?#.db", date_dir=None
    )
    with depozit.deschide(state.corpus) as con:
        con.execute(
            "INSERT INTO acte(id,tip,titlu,citit_la) VALUES ('lege-98-2016','lege','A','now')"
        )
        con.execute(
            "INSERT INTO provizii(act_id,locator,ord,text) VALUES ('lege-98-2016','art7',0,'Law')"
        )
        con.commit()
    projects = {"a": add(state, "plx-1", A), "b": add(state, "plx-2", B)}
    base = {"gasit": True, "rand": {"exemple": {}}, "acte": {}, "markdown": "Base"}
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: copy.deepcopy(base))
    monkeypatch.setattr(
        "scripts.servicii._matrice_proiecte",
        lambda qs, s: {
            "initiative": [
                {"plx_id": p, "stadiu": "Pending", "citit_la": "now", "sursa_url": URL}
                for p in ("plx-1", "plx-2")
            ],
            "tinte": ["lege-98-2016"],
            "trunchiat": False,
        },
    )
    monkeypatch.setattr("scripts.servicii._markdown_dosar_matrice", lambda d: "Draft report")
    monkeypatch.setattr(
        documente_proiecte, "descarca", lambda *a: pytest.fail("Unexpected network")
    )
    dosare.creeaza(dosare.cale(state), {"id": ID, "titlu": "Draft research"})
    request = {"dosar_id": ID, "filtre": {"emitent": "Parlament"}, "proiecte": projects}
    run = dosare.salveaza_rulare(state, request)
    return state, run, request


def test_save_server_generated_draft_findings_and_retry(saved):
    state, run, request = saved
    assert run["engine_version"] == "matrice-proiecte-v1"
    assert run["raport"]["selectie_proiecte"] == request["proiecte"]
    findings = revizuiri.constatari(run)
    assert len(findings) == 1 and findings[0]["tip"] == "proiect"
    manifest = run["dovezi"]["manifest"]
    assert manifest["schema_version"] == 2
    assert len(manifest["constatari"][0]["dependente"]) == 3
    assert [d["sursa"] for d in manifest["dependente"]].count("proiect_importat") == 2
    assert all(d["stare"] == "capturat" for d in manifest["dependente"])
    assert dosare.salveaza_rulare(state, request) == run
    assert dependente_dovezi.verifica(state, ID, run["id"])["totaluri"]["neschimbat"] == 1


@pytest.mark.parametrize("text", [A, A + "\nArticolul II. Text nou."])
def test_bytes_and_text_are_distinguished_and_url_is_bound(saved, text):
    state, run, _ = saved
    new = add(state, "plx-1", text, "2026-02-01", data=b"%PDF-different-bytes")
    add(state, "plx-1", "Unrelated", "2026-03-01", url=URL + "?other=1")
    add(state, "other-plx", "Other initiative", "2026-04-01")
    out = dependente_dovezi.verifica(state, ID, run["id"])
    dep = next(d for d in out["dependente"] if d["salvat"].get("plx_id") == "plx-1")
    assert dep["curent"]["versiune_id"] == new["versiune_id"]
    assert dep["stare"] == "schimbat" and dep["octeti_schimbati"]
    assert dep["text_schimbat"] == (text != A)
    assert out["totaluri"]["schimbat"] == 1


def test_unavailable_extraction_does_not_mean_unchanged(saved):
    state, run, _ = saved
    add(state, "plx-1", "", "2026-02-01", data=b"%PDF-scan", status="ocr_necesar")
    out = verificari_dovezi.salveaza(
        state, {"id": "b" * 32, "dosar_id": ID, "rulare_id": run["id"]}
    )
    assert out["totaluri"]["indisponibil"] == 1
    dep = next(d for d in out["dependente"] if d["salvat"].get("plx_id") == "plx-1")
    assert dep["octeti_schimbati"] is True and dep["text_schimbat"] is None
    assert verificari_dovezi.coada(dosare.cale(state), status="indisponibil")["total"] == 1
    with pytest.raises(ValueError):
        dosare.salveaza_rulare(
            state, {"dosar_id": ID, "filtre": run["filtre"], "sursa_rulare_id": run["id"]}
        )


@pytest.mark.parametrize("change", ["missing", "tampered_bytes", "tampered_text", "ambiguous"])
def test_missing_tampered_or_ambiguous_versions_are_unknown(saved, change):
    state, run, request = saved
    ident = request["proiecte"]["a"]["versiune_id"]
    if change == "ambiguous":
        add(state, "plx-1", "Another", "2026-01-01")
    else:
        with sqlite3.connect(documente_proiecte.cale_store(state)) as con:
            query = {
                "missing": "DELETE FROM documente WHERE id=?",
                "tampered_bytes": "UPDATE documente SET octeti=x'00' WHERE id=?",
                "tampered_text": "UPDATE documente SET text='Tampered' WHERE id=?",
            }[change]
            con.execute(query, (ident,))
    assert dependente_dovezi.verifica(state, ID, run["id"])["totaluri"]["indisponibil"] == 1


def test_rerun_rejects_changed_original_extraction(saved):
    state, run, request = saved
    with sqlite3.connect(documente_proiecte.cale_store(state)) as con:
        con.execute(
            "UPDATE documente SET text='Tampered' WHERE id=?",
            (request["proiecte"]["a"]["versiune_id"],),
        )
    with pytest.raises(ValueError):
        dosare.salveaza_rulare(
            state, {"dosar_id": ID, "filtre": run["filtre"], "sursa_rulare_id": run["id"]}
        )


def test_rerun_links_new_versions_without_changing_reviews(saved):
    state, run, request = saved
    path = dosare.cale(state)
    finding = revizuiri.constatari(run)[0]["id"]
    revizuiri.salveaza(
        path,
        {
            "id": "b" * 32,
            "dosar_id": ID,
            "rulare_id": run["id"],
            "constatare_id": finding,
            "revizie": 0,
            "stare": "needs_evidence",
            "evaluator": "Reviewer",
            "motiv": "Check draft",
        },
    )
    new = add(state, "plx-1", A + "\nText nou.", "2026-02-01")
    rerun = dosare.salveaza_rulare(
        state, {"dosar_id": ID, "filtre": run["filtre"], "sursa_rulare_id": run["id"]}
    )
    assert rerun["raport"]["selectie_proiecte"]["a"] == new
    assert dosare.rulari(path, ID, run["id"]) == run
    assert revizuiri.lista(path, ID, run["id"])["constatari"][0]["stare"] == "needs_evidence"
    assert revizuiri.lista(path, ID, rerun["id"])["constatari"][0]["stare"] == "unreviewed"
    assert verificari_dovezi.istoric(path, ID, rerun["id"])["origini"][0]["sursa_id"] == run["id"]
    assert dosare.salveaza_rulare(state, request) == run


def test_invalid_selection_ownership_and_missing_store(saved, tmp_path):
    state, run, request = saved
    wrong = copy.deepcopy(request)
    wrong["proiecte"]["a"]["plx_id"] = "foreign"
    with pytest.raises(ValueError):
        dosare.salveaza_rulare(state, wrong)
    for value in (None, {}, {"a": {"plx_id": "a", "versiune_id": "x"}, "b": {}}):
        with pytest.raises(ValueError):
            dependente_proiecte.selectie(value)
    absent = SimpleNamespace(initiative=tmp_path / "missing.db")
    assert dependente_proiecte.citeste(absent, "x", "a" * 64)["stare"] == "sursa_indisponibila"
    assert not documente_proiecte.cale_store(absent).exists()


def test_snapshot_byte_limit_and_invalid_extracted_type(saved, monkeypatch):
    state, run, request = saved
    monkeypatch.setattr(documente_proiecte, "MAX_BYTES", 1)
    assert dependente_dovezi.verifica(state, ID, run["id"])["totaluri"]["indisponibil"] == 1
    monkeypatch.setattr(documente_proiecte, "MAX_BYTES", 30_000_000)
    with sqlite3.connect(documente_proiecte.cale_store(state)) as con:
        con.execute(
            "UPDATE documente SET text=x'00' WHERE id=?", (request["proiecte"]["a"]["versiune_id"],)
        )
    assert dependente_dovezi.verifica(state, ID, run["id"])["totaluri"]["indisponibil"] == 1
