import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import analize_propuneri as analyses
from scripts import dosare, interventii_propuneri, propuneri
from tests import test_interventii_propuneri, test_propuneri
from tests.test_dosare import request as http

case = test_propuneri.case
structured = test_interventii_propuneri.structured


def request(req, revision=1, ident="d" * 32):
    return {k: req[k] for k in ("dosar_id", "rulare_id", "constatare_id")} | {
        "id": ident,
        "revizie": revision,
    }


def history(path, req, revision=1, **kw):
    return analyses.istoric(
        path, req["dosar_id"], req["rulare_id"], req["constatare_id"], revision, **kw
    )


def checks(result):
    return {c["cheie"]: c for c in result["controale"]}


def save_text(path, req, text="Articolul 1 din Legea nr. 98/2016 se abrog\u0103."):
    return propuneri.salveaza(path, {**req, "text": text})


def test_exact_revision_provenance_retry_and_backup(structured, monkeypatch):
    state, path, run, req, intent = structured
    preview = interventii_propuneri.pregateste(state, intent)
    saved = propuneri.salveaza(
        path, {**req, "text": preview["text_compus"], "interventie": preview["cerere"]}, state
    )
    before = state.corpus.read_bytes()
    result = analyses.salveaza(state, request(req))
    assert result["text_analizat"] == saved["text"]
    assert result["baza"]["propunere_sha256"] == analyses._sha(saved)
    assert result["baza"]["text_sha256"] == hashlib.sha256(saved["text"].encode()).hexdigest()
    assert result["baza"]["raport_sha256"] == run["sha256"]
    assert result["surse_sha256"] == analyses._sha(result["surse"])
    source = result["surse"][0]
    assert source["sha256"] == analyses._sha({k: v for k, v in source.items() if k != "sha256"})
    assert source["prevederi"][0]["text"] == "Original local text"
    citations = checks(result)["citari"]
    # Composer includes an internal article heading inside the replacement quote.
    assert citations["stare"] == "partial"
    assert citations["rezultate"][0]["stare"] == "verificat"
    assert before == state.corpus.read_bytes()
    assert history(path, req)["selectata"] == result
    backup = path.with_name("backup.db")
    dosare.backup(path, backup)
    assert history(backup, req) == history(path, req)
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed source'")
    with monkeypatch.context() as m:
        m.setattr(analyses, "executa", lambda *args: pytest.fail("Retry recomputed sources"))
        assert analyses.salveaza(state, request(req)) == result
    newer = analyses.salveaza(state, request(req, ident="e" * 32))
    assert newer["surse_sha256"] != result["surse_sha256"]
    assert history(path, req, analysis_id=result["id"])["selectata"] == result
    with sqlite3.connect(path) as con:
        for sql in (
            "DELETE FROM analize_propuneri",
            "UPDATE analize_propuneri SET rezultat_json='{}'",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)


@pytest.mark.parametrize(
    "field,value", [("text", "Different text"), ("titlu", "New title"), ("motiv", "New rationale")]
)
def test_new_revision_never_inherits_analysis_even_with_identical_text(case, field, value):
    state, path, _, req = case
    first = save_text(path, req)
    result = analyses.salveaza(state, request(req))
    propuneri.salveaza(
        path, {**req, "id": "c" * 32, "revizie": 1, "text": first["text"], field: value}
    )
    assert history(path, req, 2)["selectata"] is None
    assert history(path, req, 1)["istorica"]
    assert history(path, req, 1)["selectata"] == result
    with pytest.raises(ValueError):
        history(path, req, 2, analysis_id=result["id"])
    with pytest.raises(ValueError, match="reutilizat"):
        analyses.salveaza(state, request(req, 2))
    args = (path, req["dosar_id"], req["rulare_id"], req["constatare_id"])
    exported = propuneri.exporta(*args, 1)
    assert exported["schema_version"] == 2 and exported["analiza"] == result
    assert result["baza"]["text_sha256"] in exported["markdown"]
    assert "nesuportat" in exported["markdown"]
    assert propuneri.exporta(*args, 2)["analiza"] is None
    with pytest.raises(ValueError):
        propuneri.exporta(*args, 2, result["id"])


def test_pure_checks_and_explicit_unsupported_scope(case):
    state, path, _, req = case
    save_text(
        path,
        req,
        "Articolul 7 se schimb\u0103. Articolul 1 din Legea nr. 98/2016 se abrog\u0103. "
        "Articolul 1 din Legea nr. 98/2016 se modific\u0103 "
        "\u0219i va avea urm\u0103torul cuprins: X. "
        "Guvernul aprob\u0103 normele metodologice prin hot\u0103r\u00e2re, "
        "\u00een termen de 30 de zile de la intrarea \u00een vigoare.",
    )
    result = analyses.salveaza(state, request(req))
    cs = checks(result)
    assert cs["redactare"]["total"] > 0
    assert cs["conflicte_interne"]["total"] > 0
    assert cs["termene"]["total"] > 0 and cs["termene"]["tip_rezultate"] == "inventar"
    assert cs["citari"]["stare"] == "indisponibil"
    for key in ("compatibilitate", "ccr", "vid", "proiecte"):
        assert cs[key]["stare"] == "nesuportat" and cs[key]["limitare"]


@pytest.mark.parametrize("text", ["Text fara referinte.", "Articolul 1 se abrog\u0103."])
def test_no_external_context_is_unsupported_not_clear(case, text):
    state, path, _, req = case
    save_text(path, req, text)
    cs = checks(analyses.salveaza(state, request(req)))
    assert cs["citari"]["stare"] == cs["terminologie"]["stare"] == "nesuportat"


@pytest.mark.parametrize(
    "change,expected",
    [
        ("DROP TABLE provizii", "indisponibil"),
        ("DELETE FROM acte", "indisponibil"),
        ("DELETE FROM provizii", "indisponibil"),
        ("UPDATE provizii SET locator='art2'", "partial"),
        ("UPDATE provizii SET text=''", "partial"),
    ],
)
def test_missing_sources_cannot_look_clear(structured, change, expected):
    state, path, _, req, _ = structured
    save_text(path, req)
    with sqlite3.connect(state.corpus) as con:
        con.execute(change)
    cs = checks(analyses.salveaza(state, request(req)))
    assert cs["citari"]["stare"] == expected
    assert cs["citari"]["rezultate"][0]["stare"] == "indisponibil"


@pytest.mark.parametrize("limit", ["MAX_ROWS", "MAX_SOURCE_BYTES", "MAX_ACTS"])
def test_source_bounds_report_partial(structured, monkeypatch, limit):
    state, path, _, req, _ = structured
    save_text(path, req)
    monkeypatch.setattr(analyses, limit, 0)
    result = analyses.salveaza(state, request(req))
    assert checks(result)["citari"]["stare"] == "partial"
    assert all(not s["prevederi"] for s in result["surse"])


def test_terminology_quotes_and_source_hash(structured):
    state, path, _, req, _ = structured
    with sqlite3.connect(state.corpus) as con:
        con.execute(
            "UPDATE provizii SET text=?",
            (
                "Prin autoritate contractant\u0103 se \u00een\u021belege "
                "orice autoritate public\u0103.",
            ),
        )
    save_text(
        path, req, "Legea nr. 98/2016. Autoritatea contractual\u0103 public\u0103 anun\u021bul."
    )
    result = analyses.salveaza(state, request(req))
    terms = checks(result)["terminologie"]
    assert terms["stare"] == "verificat" and terms["total"] > 0
    assert terms["rezultate"][0]["sursa_sha256"] == result["surse"][0]["sha256"]
    assert terms["rezultate"][0]["locator"] == "art1"


def test_concurrent_retry_and_paginated_history(case):
    state, path, _, req = case
    save_text(path, req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: analyses.salveaza(state, request(req)), range(2)))
    assert rows[0] == rows[1] and history(path, req)["total"] == 1
    for n in range(22):
        analyses.salveaza(state, request(req, ident=f"{n:032x}"))
    head, tail = history(path, req), history(path, req, offset=20)
    assert head["total"] == tail["total"] == 23
    assert len(head["analize"]) == 20 and len(tail["analize"]) == 3
    assert len({a["id"] for a in head["analize"] + tail["analize"]}) == 23
    assert "surse" not in head["analize"][0]


def test_duplicate_locator_and_blank_act_text_are_not_complete(structured):
    state, path, _, req, _ = structured
    saved = save_text(path, req, "Legea nr. 98/2016.")
    with sqlite3.connect(state.corpus) as con:
        con.execute("INSERT INTO provizii SELECT * FROM provizii")
    assert checks(analyses.executa(state, saved))["citari"]["stare"] == "partial"
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text=''")
    assert checks(analyses.executa(state, saved))["citari"]["stare"] == "partial"


def test_terminology_and_result_work_limits_are_explicit(structured, monkeypatch):
    state, path, _, req, _ = structured
    saved = save_text(path, req, "Legea nr. 98/2016. " + "Text lung. " * 1000)
    from scripts.definitii import Termen

    terms = [Termen(f"term {n}", "definition", None, None) for n in range(50)]
    monkeypatch.setattr(analyses, "definitii", lambda *args, **kw: terms)
    observed = []
    monkeypatch.setattr(analyses, "jargon", lambda text, selected: observed.extend(selected) or [])
    result = analyses.executa(state, saved)
    assert len(observed) == analyses.MAX_TERM_CHAR_PAIRS // len(saved["text"])
    assert result["acoperire"]["termeni_comparati"] == len(observed)
    assert checks(result)["terminologie"]["stare"] == "partial"
    check = analyses._check("test", "Test", list(range(101)))
    assert check["stare"] == "partial" and check["trunchiat"]
    assert check["total"] == 101 and len(check["rezultate"]) == 100


def test_export_exact_historical_check_and_markdown_fence(case):
    state, path, _, req = case
    save_text(path, req, "```\n<script>fixture</script>\n````")
    first = analyses.salveaza(state, request(req))
    analyses.salveaza(state, request(req, ident="e" * 32))
    exported = propuneri.exporta(
        path, req["dosar_id"], req["rulare_id"], req["constatare_id"], 1, first["id"]
    )
    assert exported["analiza"] == first
    assert "`````json\n" in exported["markdown"]
    assert exported["analiza"]["limitari"]


@pytest.mark.parametrize(
    "patch",
    [
        {"revizie": True},
        {"revizie": 0},
        {"revizie": 2},
        {"revizie": "1"},
        {"id": "bad"},
        {"text": "Client text"},
        {"dosar_id": "f" * 32},
        {"rulare_id": "f" * 32},
        {"constatare_id": "f" * 32},
    ],
)
def test_bad_requests_never_write(case, patch):
    state, path, _, req = case
    save_text(path, req)
    dosare.creeaza(path, {"id": "f" * 32, "titlu": "Other dossier"})
    with pytest.raises(ValueError):
        analyses.salveaza(state, {**request(req), **patch})
    assert history(path, req)["total"] == 0


def test_empty_text_and_oversized_result_do_not_write(case, monkeypatch):
    state, path, _, req = case
    save_text(path, req, "")
    with pytest.raises(ValueError):
        analyses.salveaza(state, request(req))
    save_text(path, {**req, "id": "c" * 32, "revizie": 1})
    monkeypatch.setattr(analyses, "executa", lambda *args: {"huge": "x" * dosare.MAX_REPORT_BYTES})
    with pytest.raises(ValueError, match="4 MB"):
        analyses.salveaza(state, request(req, 2))
    assert history(path, req)["total"] == 0


def test_schema6_reads_without_migration_and_failed_write_rolls_back(case):
    state, path, _, req = case
    save_text(path, req)
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE ciorne")
        con.execute("DROP TABLE dosare_stare")
        con.execute("DROP TABLE analize_propuneri")
        con.execute("PRAGMA user_version=6")
    before = path.read_bytes()
    assert history(path, req)["selectata"] is None
    assert path.read_bytes() == before

    def interrupt():
        with dosare._open(path, write=True):
            raise RuntimeError("Interrupted migration")

    pytest.raises(RuntimeError, interrupt)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6
        assert not con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='analize_propuneri'"
        ).fetchone()
    analyses.salveaza(state, request(req))
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == dosare.SCHEMA_VERSION


def test_http_protections_explicit_revision_and_export(case):
    state, path, _, req = case
    save_text(path, req)
    url = "/api/dosare/propuneri/analize"
    query = (
        f"?id={req['dosar_id']}&rulare_id={req['rulare_id']}"
        f"&constatare_id={req['constatare_id']}&revizie=1"
    )
    assert http(state, "POST", url, request(req), length=16001)[0] == 413
    assert http(state, "POST", url, request(req), origin="https://evil.test")[0] == 403
    assert http(state, "GET", url + query, host="evil:8123")[0] == 403
    assert http(state, "GET", url + query.replace("revizie=1", "revizie=bad"))[0] == 400
    assert http(state, "GET", url + query)[1]["selectata"] is None
    code, result = http(state, "POST", url, request(req))
    assert code == 200
    assert http(state, "GET", url + query)[1]["selectata"] == result
    exported = http(
        state, "GET", "/api/dosare/propuneri" + query + "&mod=export&analiza_id=" + result["id"]
    )
    assert exported[0] == 200 and exported[1]["analiza"] == result
    assert http(state, "GET", url + query + "&analiza_id=" + "e" * 32)[0] == 400
    state.date_dir = "static"
    assert http(state, "GET", url + query)[0] == 400
    assert http(state, "POST", url, request(req))[0] == 400
