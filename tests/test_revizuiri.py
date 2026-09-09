import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from scripts import dosare, revizuiri

ID = "a" * 32


@pytest.fixture
def saved(tmp_path, monkeypatch):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)
    path = dosare.cale(state)
    dosare.creeaza(path, {"id": ID, "titlu": "Research"})
    report = {
        "gasit": True,
        "rand": {
            "exemple": {
                "viduri": [
                    {"act_id": "lege-1-2020", "locator": "art1", "text": "Obligation"},
                    {"act_id": "lege-1-2020", "locator": "art2", "text": "Other obligation"},
                ]
            }
        },
        "markdown": "Original report",
        "limitari": ["Partial corpus"],
    }
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "Parlamentul"}})
    finding = revizuiri.constatari(run)[0]["id"]
    request = {
        "id": "b" * 32,
        "dosar_id": ID,
        "rulare_id": run["id"],
        "constatare_id": finding,
        "revizie": 0,
        "stare": "needs_evidence",
        "evaluator": "Reviewer",
        "motiv": "Check scope",
    }
    return path, run, request, state, report


def test_defaults_append_only_and_export(saved):
    path, run, req, _, _ = saved
    assert revizuiri.lista(path, ID, run["id"])["constatari"][0]["stare"] == "unreviewed"
    first = revizuiri.salveaza(path, req)
    assert revizuiri.salveaza(path, req) == first
    second = revizuiri.salveaza(
        path,
        {
            **req,
            "id": "c" * 32,
            "revizie": 1,
            "stare": "confirmed_by_reviewer",
            "motiv": "Sources reviewed",
        },
    )
    out = revizuiri.lista(path, ID, run["id"])
    assert out["constatari"][0]["istoric"] == [second, first]
    assert out["constatari"][1]["stare"] == "unreviewed"
    assert "Sources reviewed" in out["markdown"] and "Check scope" in out["markdown"]
    assert run["sha256"] in out["markdown"] and "Original report" in out["markdown"]
    assert out["rulare"] == run
    with sqlite3.connect(path) as con:
        for sql in ("UPDATE revizuiri SET motiv='altered'", "DELETE FROM revizuiri"):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(sql)


@pytest.mark.parametrize(
    "patch",
    [
        {"motiv": " "},
        {"evaluator": ""},
        {"stare": "official"},
        {"revizie": True},
        {"constatare_id": "d" * 32},
        {"dosar_id": "e" * 32},
    ],
)
def test_reject_invalid_or_foreign_evidence(saved, patch):
    path, run, req, _, _ = saved
    with pytest.raises(ValueError):
        revizuiri.salveaza(path, {**req, **patch})
    assert not revizuiri.lista(path, ID, run["id"])["constatari"][0]["istoric"]
    with pytest.raises(ValueError):
        revizuiri.lista(path, ID, None)


def test_revision_conflict_and_concurrent_retry(saved):
    path, _, req, _, _ = saved
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: revizuiri.salveaza(path, req), range(2)))
    assert results[0] == results[1]
    with pytest.raises(ValueError, match="schimbat"):
        revizuiri.salveaza(path, {**req, "id": "c" * 32})
    with pytest.raises(ValueError, match="reutilizat"):
        revizuiri.salveaza(path, {**req, "motiv": "Changed"})


def test_v1_read_without_migration_then_atomic_upgrade_and_backup(saved, tmp_path):
    path, run, req, _, _ = saved
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE revizuiri")
        con.execute("DROP TABLE verificari_dovezi")
        con.execute("DROP TABLE recalculari")
        con.execute("PRAGMA user_version=1")
    before = path.read_bytes()
    assert revizuiri.lista(path, ID, run["id"])["constatari"][0]["revizie"] == 0
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="schimbat"):
        revizuiri.salveaza(path, {**req, "revizie": 1})
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='revizuiri'").fetchall()
    revizuiri.salveaza(path, req)
    restored = tmp_path / "restore.db"
    dosare.backup(path, restored)
    assert revizuiri.lista(restored, ID, run["id"]) == revizuiri.lista(path, ID, run["id"])


def test_reviews_do_not_transfer_to_new_run_and_history_limit_is_explicit(saved):
    path, run, req, state, report = saved
    for i in range(21):
        revizuiri.salveaza(path, {**req, "id": f"{i:032x}", "revizie": i})
    old = revizuiri.lista(path, ID, run["id"])
    assert old["constatari"][0]["revizie"] == 21
    assert old["constatari"][0]["istoric_trunchiat"]
    assert "Istoric parțial" in old["markdown"]
    page = revizuiri.istoric(path, ID, run["id"], req["constatare_id"], 20)
    assert page["total"] == 21 and page["evenimente"][0]["revizie"] == 1
    report["markdown"] = "Changed report"
    newer = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "Parlamentul"}})
    assert revizuiri.lista(path, ID, newer["id"])["constatari"][0]["revizie"] == 0
