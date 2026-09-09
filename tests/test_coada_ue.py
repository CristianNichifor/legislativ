import sqlite3
from types import SimpleNamespace

import pytest

from scripts import coada_ue, dosare
from tests.test_dosare import request


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)


def seed(state, number=1, *, refs=True, dossier=1):
    path = dosare.cale(state)
    ident = f"{dossier:032x}"
    dosare.creeaza(path, {"id": ident, "titlu": f"EU dossier {dossier} <script>"})
    run = f"{number:032x}"
    evidence = {"referinte_ue": [{"celex": "32014L0024"}]} if refs else {}
    with dosare._open(path, write=True) as con:
        con.execute(
            "INSERT INTO rulari VALUES (?,?,?,?,?,?,?,?)",
            (
                run,
                ident,
                "2026-01-01",
                "test",
                run,
                "{}",
                "{}",
                dosare._json(evidence),
            ),
        )
    return run


def check(state, run, number=1, *, kind="same", incomplete=False):
    source = {
        "celex": "32014L0024",
        "stare": "neschimbat",
        "text_schimbat": False,
        "limba_schimbata": False,
        "metadate_schimbate": False,
    }
    if kind in ("text", "language"):
        source.update(
            stare="schimbat",
            text_schimbat=True if kind == "text" else None,
            limba_schimbata=kind == "language",
            metadate_schimbate=True,
        )
    elif kind == "metadata":
        source["metadate_schimbate"] = True
    elif kind == "unknown":
        incomplete = True
        source.update(
            stare="indisponibil", text_schimbat=None, limba_schimbata=None, metadate_schimbate=None
        )
    eu = {"schema_version": 1, "comparatie_incompleta": incomplete, "surse": [source]}
    if kind == "future":
        eu["schema_version"] = 999
    payload = {"surse_ue": eu} if kind != "legacy" else {}
    ident = f"{number:032x}"
    with dosare._open(dosare.cale(state), write=True) as con:
        con.execute(
            "INSERT INTO verificari_dovezi "
            "(id,rulare_id,verificat_la,schimbate,incomplete,constatari,rezultat_json) "
            "VALUES (?,?,?,0,0,0,?)",
            (ident, run, "2026-02-01", dosare._json(payload)),
        )
    return ident


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("same", {"toate", "neschimbat"}),
        ("text", {"toate", "text", "schimbat"}),
        ("language", {"toate", "limba", "schimbat"}),
        ("metadata", {"toate", "metadate"}),
        ("unknown", {"toate", "indisponibil"}),
        ("future", {"toate", "indisponibil"}),
        ("legacy", {"toate", "neverificat"}),
    ],
)
def test_filters_keep_signals_independent(state, kind, expected):
    run = seed(state)
    ident = check(state, run, kind=kind)
    for status in (
        "toate",
        "text",
        "limba",
        "schimbat",
        "metadate",
        "indisponibil",
        "neverificat",
        "neschimbat",
    ):
        result = coada_ue.lista(dosare.cale(state), status=status)
        assert result["total"] == int(status in expected), status
        if result["rulari"]:
            assert result["rulari"][0]["verificare_id"] == ident
            assert "eu" not in result["rulari"][0]


def test_latest_sequence_wins_even_without_eu_results(state):
    run = seed(state)
    assert coada_ue.lista(dosare.cale(state), status="neverificat")["total"] == 1
    check(state, run, 9, kind="text")
    check(state, run, 2, kind="same")
    assert coada_ue.lista(dosare.cale(state), status="text")["total"] == 0
    assert coada_ue.lista(dosare.cale(state), status="neschimbat")["total"] == 1
    check(state, run, 1, kind="legacy")
    assert coada_ue.lista(dosare.cale(state), status="neverificat")["total"] == 1


def test_incomplete_changed_check_matches_both_filters(state):
    run = seed(state)
    check(state, run, kind="text", incomplete=True)
    for status in ("text", "indisponibil"):
        assert coada_ue.lista(dosare.cale(state), status=status)["total"] == 1


def test_pagination_all_dossiers_and_excludes_runs_without_eu(state):
    for number in range(1, 56):
        seed(state, number, dossier=number, refs=number != 55)
    path = dosare.cale(state)
    first, second = coada_ue.lista(path), coada_ue.lista(path, 50)
    assert first["total"] == second["total"] == 54
    assert len(first["rulari"]) == 50 and len(second["rulari"]) == 4
    assert not (
        {r["rulare_id"] for r in first["rulari"]} & {r["rulare_id"] for r in second["rulari"]}
    )
    assert coada_ue.lista(path, 100)["rulari"] == []


@pytest.mark.parametrize("version", [1, 2])
def test_old_schemas_read_without_migration(state, version):
    seed(state)
    path = dosare.cale(state)
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE verificari_dovezi")
        con.execute("DROP TABLE contexte_juridice")
        con.execute("DROP TABLE ciorne")
        con.execute("DROP TABLE legaturi_ue")
        con.execute("DROP TABLE dosare_stare")
        con.execute("DROP TABLE analize_propuneri")
        con.execute("DROP TABLE interventii_propuneri")
        con.execute("DROP TABLE propuneri")
        con.execute("DROP TABLE recalculari")
        con.execute(f"PRAGMA user_version={version}")
    before = path.read_bytes()
    assert coada_ue.lista(path, status="neverificat")["total"] == 1
    assert path.read_bytes() == before


def test_missing_invalid_and_route_security(state):
    path = dosare.cale(state)
    assert coada_ue.lista(path)["total"] == 0 and not path.exists()
    for offset in (-1, True, "0", 1_000_001):
        with pytest.raises(ValueError):
            coada_ue.lista(path, offset)
    with pytest.raises(ValueError):
        coada_ue.lista(path, status="sql'")
    url = "/api/dosare/coada-ue"
    assert request(state, "GET", url)[1]["total"] == 0
    assert request(state, "GET", url, host="evil:8123")[0] == 403
    assert request(state, "GET", url, origin="https://evil.test")[0] == 403
    assert request(state, "GET", url + "?offset=bad")[0] == 400
    assert request(state, "GET", url + "?stare=bad")[0] == 400
    state.date_dir = "static"
    assert request(state, "GET", url)[0] == 400
    assert not path.exists()


def test_source_changes_do_not_refresh_saved_queue_results(state, monkeypatch):
    from scripts import verificari_dovezi
    from tests.test_cellar import EU_TEXT
    from tests.test_instantanee_ue import write

    state.eu = state.initiative.with_name("eu.db")
    write(state)
    path = dosare.cale(state)
    dossier = "a" * 32
    dosare.creeaza(path, {"id": dossier, "titlu": "EU"})
    monkeypatch.setattr(
        "scripts.servicii._matrice_dosar",
        lambda qs, s: {
            "gasit": True,
            "referinte_ue": [{"celex": "32018R1805"}],
            "markdown": "EU",
        },
    )
    run = dosare.salveaza_rulare(state, {"dosar_id": dossier, "filtre": {"emitent": "P"}})
    request = {"id": "b" * 32, "dosar_id": dossier, "rulare_id": run["id"]}
    first = verificari_dovezi.salveaza(state, request)
    write(state, EU_TEXT + "\nChanged wording.")
    assert coada_ue.lista(path, status="neschimbat")["total"] == 1
    assert coada_ue.lista(path, status="text")["total"] == 0
    second = verificari_dovezi.salveaza(state, {**request, "id": "c" * 32})
    state.eu.unlink()
    assert coada_ue.lista(path, status="text")["rulari"][0]["verificare_id"] == second["id"]
    assert (
        verificari_dovezi.istoric(path, dossier, run["id"], check_id=first["id"])["selectata"]
        == first
    )
    assert dosare.rulari(path, dossier, run["id"]) == run
    assert not state.eu.exists()
