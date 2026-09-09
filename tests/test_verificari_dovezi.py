import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from scripts import depozit, dosare
from scripts import verificari_dovezi as checks

ID = "a" * 32


@pytest.fixture
def saved(tmp_path, monkeypatch):
    state = SimpleNamespace(
        corpus=tmp_path / "corpus.db", initiative=tmp_path / "initiative.db", date_dir=None
    )
    with sqlite3.connect(state.corpus) as con:
        con.executescript(depozit.SCHEMA)
        con.execute("INSERT INTO acte(id,tip,titlu,citit_la) VALUES ('A','lege','A','now')")
        con.execute("INSERT INTO provizii(act_id,locator,ord,text) VALUES ('A','art1',0,'First')")
    report = {
        "gasit": True,
        "rand": {"exemple": {"viduri": [{"act_id": "A", "locator": "art1"}]}},
        "markdown": "Saved",
    }
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report)
    dosare.creeaza(dosare.cale(state), {"id": ID, "titlu": "Research"})
    run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "P"}})
    return state, run


def request(run, number=1):
    return {"id": f"{number:032x}", "dosar_id": ID, "rulare_id": run["id"]}


def test_append_only_retry_restart_and_backup(saved, tmp_path):
    state, run = saved
    path = dosare.cale(state)
    first = checks.salveaza(state, request(run))
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed'")
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert (
            list(pool.map(lambda _: checks.salveaza(state, request(run)), range(3))) == [first] * 3
        )
    second = checks.salveaza(state, request(run, 2))
    assert first["totaluri"]["neschimbat"] == second["totaluri"]["schimbat"] == 1
    history = checks.istoric(path, ID, run["id"])
    assert history["total"] == 2 and history["selectata"] == second
    assert checks.istoric(path, ID, run["id"], check_id=first["id"])["selectata"] == first
    assert dosare.rulari(path, ID, run["id"]) == run
    with sqlite3.connect(path) as con:
        for sql in (
            "DELETE FROM verificari_dovezi",
            "UPDATE verificari_dovezi SET rulare_id=rulare_id",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(sql)
    target = tmp_path / "backup.db"
    dosare.backup(path, target)
    assert checks.istoric(target, ID, run["id"]) == history


def test_concurrent_first_retry_is_one_event(saved):
    state, run = saved
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: checks.salveaza(state, request(run)), range(4)))
    assert results == [results[0]] * 4
    assert checks.istoric(dosare.cale(state), ID, run["id"])["total"] == 1


def test_queue_latest_only_and_history_paging(saved):
    state, run = saved
    path = dosare.cale(state)
    assert checks.coada(path, status="neverificat")["total"] == 1
    for n in range(1, 22):
        checks.salveaza(state, request(run, n))
    assert checks.istoric(path, ID, run["id"])["total"] == 21
    older = checks.istoric(path, ID, run["id"], offset=20)
    assert len(older["verificari"]) == 1 and older["verificari"][0]["id"] == f"{1:032x}"
    assert checks.coada(path, status="neschimbat")["total"] == 1
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed'")
    checks.salveaza(state, request(run, 22))
    assert checks.coada(path, status="schimbat")["total"] == 1
    assert checks.coada(path, status="neschimbat")["total"] == 0
    with sqlite3.connect(state.corpus) as con:
        con.execute("DELETE FROM provizii")
    checks.salveaza(state, request(run, 23))
    assert checks.coada(path, status="indisponibil")["total"] == 1
    assert checks.coada(path, status="schimbat")["total"] == 0


def test_lineage_is_separate_idempotent_and_owned(saved):
    state, original = saved
    path = dosare.cale(state)
    req = {"dosar_id": ID, "filtre": original["filtre"], "sursa_rulare_id": original["id"]}
    assert dosare.salveaza_rulare(state, req) == original
    assert checks.istoric(path, ID, original["id"])["origini"] == []
    with sqlite3.connect(state.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed'")
    new = dosare.salveaza_rulare(state, req)
    assert dosare.salveaza_rulare(state, req) == new
    origins = checks.istoric(path, ID, new["id"])["origini"]
    assert len(origins) == 1 and origins[0]["sursa_id"] == original["id"]
    assert dosare.rulari(path, ID, original["id"]) == original
    with sqlite3.connect(path) as con:
        for sql in ("DELETE FROM recalculari", "UPDATE recalculari SET creat_la='bad'"):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(sql)
    with pytest.raises(ValueError):
        dosare.salveaza_rulare(state, {**req, "filtre": {"emitent": "Other"}})
    dosare.creeaza(path, {"id": "b" * 32, "titlu": "Other"})
    with pytest.raises(ValueError):
        dosare.salveaza_rulare(state, {**req, "dosar_id": "b" * 32})
    with pytest.raises(ValueError):
        checks.salveaza(state, {**request(new), "dosar_id": "b" * 32})
    checks.salveaza(state, request(original))
    with pytest.raises(ValueError):
        checks.salveaza(state, request(new))
    with pytest.raises(ValueError):
        checks.istoric(path, ID, new["id"], check_id=request(original)["id"])


def test_legacy_read_only_atomic_upgrade_and_limits(saved, monkeypatch):
    state, run = saved
    path = dosare.cale(state)
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE verificari_dovezi")
        con.execute("DROP TABLE contexte_juridice")
        con.execute("DROP TABLE interventii_propuneri")
        con.execute("DROP TABLE propuneri")
        con.execute("DROP TABLE recalculari")
        con.execute("PRAGMA user_version=2")
    before = path.read_bytes()
    assert checks.istoric(path, ID, run["id"])["total"] == 0
    assert checks.coada(path, status="neverificat")["total"] == 1
    assert path.read_bytes() == before
    migrate = checks.migreaza

    def interrupted(con):
        migrate(con)
        raise RuntimeError("interrupted")

    monkeypatch.setattr(checks, "migreaza", interrupted)
    with pytest.raises(RuntimeError):
        checks.salveaza(state, request(run))
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert not con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='verificari_dovezi'"
        ).fetchall()
    monkeypatch.setattr(checks, "migreaza", migrate)
    monkeypatch.setattr(dosare, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError, match="4 MB"):
        checks.salveaza(state, request(run))
    assert checks.istoric(path, ID, run["id"])["total"] == 0
    monkeypatch.setattr(dosare, "MAX_REPORT_BYTES", 4_000_000)
    checks.salveaza(state, request(run))
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == dosare.SCHEMA_VERSION


@pytest.mark.parametrize("offset", [-1, True, 1_000_001, "0"])
def test_invalid_offsets_and_missing_store(tmp_path, offset):
    path = tmp_path / "absent.db"
    with pytest.raises(ValueError):
        checks.coada(path, offset)
    assert checks.coada(path)["total"] == 0 and not path.exists()


def test_cross_dossier_queue_paging(saved):
    state, run = saved
    path = dosare.cale(state)
    for n in range(51):
        ident = f"{n:032x}"
        dosare.creeaza(path, {"id": ident, "titlu": "Other"})
        dosare.salveaza_rulare(state, {"dosar_id": ident, "filtre": run["filtre"]})
    first, second = checks.coada(path), checks.coada(path, 50)
    assert first["total"] == second["total"] == 52
    assert len(first["rulari"]) == 50 and len(second["rulari"]) == 2
    assert not {r["rulare_id"] for r in first["rulari"]} & {
        r["rulare_id"] for r in second["rulari"]
    }


def test_no_findings_and_invalid_inputs_are_not_clear(saved, monkeypatch):
    state, _ = saved
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: {"gasit": True})
    run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "P"}})
    checks.salveaza(state, request(run))
    path = dosare.cale(state)
    assert checks.coada(path, status="neschimbat")["total"] == 0
    assert checks.coada(path, status="indisponibil")["total"] == 1
    for patch in ({"id": "invalid"}, {"result": {}}, {"dosar_id": "b" * 32}):
        with pytest.raises(ValueError):
            checks.salveaza(state, {**request(run), **patch})
    with pytest.raises(ValueError):
        checks.coada(path, status="invalid")
