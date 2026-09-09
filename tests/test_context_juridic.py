import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from scripts import dosare, revizuiri
from tests.test_dosare import request as http

ID = "a" * 32


@pytest.fixture
def case(tmp_path, monkeypatch):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)
    path = dosare.cale(state)
    dosare.creeaza(path, {"id": ID, "titlu": "Context"})
    report = {
        "gasit": True,
        "contradictii": {
            "candidati": [
                {
                    "tip": "definitie",
                    "a": {"act_id": "A", "locator": "art1"},
                    "b": {"act_id": "B", "locator": "art2"},
                }
            ]
        },
        "markdown": "Saved",
    }
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "P"}})
    req = {
        "id": "b" * 32,
        "dosar_id": ID,
        "rulare_id": run["id"],
        "constatare_id": revizuiri.constatari(run)[0]["id"],
        "tinta": "a",
        "revizie": 0,
        "evaluator": "Reviewer",
        "motiv": "Scope assessed from cited provisions",
        "context": {key: {"valoare": "", "citare": ""} for key in revizuiri.CONTEXT_FIELDS},
    }
    return state, path, run, req


def test_context_unknown_then_cited_revisions_are_independent(case):
    _, path, run, req = case
    initial = revizuiri.lista(path, ID, run["id"])
    assert initial["constatari"][0]["context_juridic"]["a"]["curent"] is None
    req["context"]["clasificare"] = {"valoare": "organica", "citare": "A, art. 1 (review basis)"}
    req["context"]["aplicabil_de_la"] = {"valoare": "2026-01-01", "citare": "A, art. 2"}
    first = revizuiri.context_salveaza(path, req)
    assert revizuiri.context_salveaza(path, req) == first
    out = revizuiri.lista(path, ID, run["id"])
    finding = out["constatari"][0]
    assert finding["stare"] == "unreviewed" and finding["istoric"] == []
    assert finding["context_juridic"]["b"]["curent"] is None
    assert finding["context_juridic"]["a"]["curent"]["context"] == req["context"]
    assert "review basis" in out["markdown"]
    assert out["rulare"] == run
    second = copy.deepcopy(req)
    second.update(id="c" * 32, revizie=1, motiv="Previous basis withdrawn; classification unknown")
    second["context"]["clasificare"] = {"valoare": "", "citare": ""}
    revizuiri.context_salveaza(path, second)
    data = revizuiri.lista(path, ID, run["id"])["constatari"][0]["context_juridic"]["a"]
    assert data["curent"]["context"]["clasificare"]["valoare"] == ""
    assert data["istoric"][1]["context"]["clasificare"]["valoare"] == "organica"
    other = {**req, "id": "d" * 32, "tinta": "b"}
    assert revizuiri.context_salveaza(path, other)["revizie"] == 1
    backup = path.with_name("backup.db")
    dosare.backup(path, backup)
    assert revizuiri.lista(backup, ID, run["id"]) == revizuiri.lista(path, ID, run["id"])
    with sqlite3.connect(path) as con:
        for sql in ("DELETE FROM contexte_juridice", "UPDATE contexte_juridice SET motiv='x'"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)


@pytest.mark.parametrize(
    "change", ["citation", "orphan", "date", "interval", "classification", "field", "null", "long"]
)
def test_validate_context_before_write(case, change):
    _, path, run, req = case
    ctx = req["context"]
    if change == "citation":
        ctx["teritoriu"]["valoare"] = "Romania"
    elif change == "orphan":
        ctx["teritoriu"]["citare"] = "A art.1"
    elif change == "date":
        ctx["aplicabil_de_la"] = {"valoare": "2026-02-30", "citare": "A art.1"}
    elif change == "interval":
        ctx["aplicabil_de_la"] = {"valoare": "2027-01-01", "citare": "A art.1"}
        ctx["aplicabil_pana_la"] = {"valoare": "2026-01-01", "citare": "A art.2"}
    elif change == "classification":
        ctx["clasificare"] = {"valoare": "inferred", "citare": "A art.1"}
    elif change == "field":
        ctx["extra"] = {}
    elif change == "null":
        ctx["teritoriu"]["valoare"] = None
    else:
        ctx["teritoriu"] = {"valoare": "x" * 501, "citare": "A art.1"}
    with pytest.raises(ValueError):
        revizuiri.context_salveaza(path, req)
    assert (
        revizuiri.lista(path, ID, run["id"])["constatari"][0]["context_juridic"]["a"]["curent"]
        is None
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"tinta": "constatare"},
        {"constatare_id": "e" * 32},
        {"dosar_id": "f" * 32},
        {"revizie": True},
        {"motiv": " "},
        {"evaluator": ""},
        {"id": "bad"},
        {"extra": 1},
    ],
)
def test_membership_and_request_validation(case, patch):
    _, path, _, req = case
    with pytest.raises(ValueError):
        revizuiri.context_salveaza(path, {**req, **patch})


def test_retry_concurrency_and_stale_revision(case):
    _, path, _, req = case
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: revizuiri.context_salveaza(path, req), range(2)))
    assert results[0] == results[1]
    with pytest.raises(ValueError, match="schimbat"):
        revizuiri.context_salveaza(path, {**req, "id": "c" * 32})
    with pytest.raises(ValueError, match="reutilizat"):
        revizuiri.context_salveaza(path, {**req, "motiv": "Other"})


def test_history_pagination_and_no_transfer(case):
    state, path, run, req = case
    for n in range(22):
        revizuiri.context_salveaza(path, {**req, "id": f"{n:032x}", "revizie": n})
    item = revizuiri.lista(path, ID, run["id"])["constatari"][0]["context_juridic"]["a"]
    assert item["istoric_trunchiat"] and len(item["istoric"]) == 20
    tail = revizuiri.context_istoric(path, ID, run["id"], req["constatare_id"], "a", 20)
    assert [e["revizie"] for e in tail["evenimente"]] == [2, 1] and not tail["mai_multe"]
    new = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "Other"}})
    assert new["id"] != run["id"]
    assert (
        revizuiri.lista(path, ID, new["id"])["constatari"][0]["context_juridic"]["a"]["curent"]
        is None
    )


def test_v3_read_no_migration_and_failed_write_rolls_back(case):
    _, path, run, req = case
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE contexte_juridice")
        con.execute("DROP TABLE interventii_propuneri")
        con.execute("DROP TABLE propuneri")
        con.execute("PRAGMA user_version=3")
    before = path.read_bytes()
    assert (
        revizuiri.lista(path, ID, run["id"])["constatari"][0]["context_juridic"]["a"]["curent"]
        is None
    )
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="schimbat"):
        revizuiri.context_salveaza(path, {**req, "revizie": 1})
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert not con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='contexte_juridice'"
        ).fetchone()
    revizuiri.context_salveaza(path, req)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == dosare.SCHEMA_VERSION


def test_http_security_bounds_and_local_only(case):
    state, _, run, req = case
    url = "/api/dosare/context"
    assert http(state, "POST", url, req, origin="https://evil.test")[0] == 403
    assert http(state, "GET", url, host="evil:8123")[0] == 403
    assert http(state, "POST", url, req, length=16001)[0] == 413
    assert http(state, "POST", url, req)[0] == 200
    query = f"?id={ID}&rulare_id={run['id']}&constatare_id={req['constatare_id']}&tinta=a"
    assert len(http(state, "GET", url + query)[1]["evenimente"]) == 1
    assert http(state, "GET", url + query + "&offset=-1")[0] == 400
    state.date_dir = "static"
    assert http(state, "POST", url, req)[0] == 400
