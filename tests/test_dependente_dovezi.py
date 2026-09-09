import copy
import hashlib
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import dependente_dovezi as dependencies
from scripts import depozit, dosare, revizuiri


@pytest.fixture
def source(tmp_path):
    state = SimpleNamespace(
        corpus=tmp_path / "corpus?#.db", initiative=tmp_path / "initiative.db", date_dir=None
    )
    with sqlite3.connect(state.corpus) as con:
        con.executescript(depozit.SCHEMA)
        con.execute(
            "INSERT INTO acte (id,tip,titlu,citit_la,sursa_url) VALUES (?,?,?,?,?)",
            ("lege-1-2020", "Lege", "Test", "2026-01-01", "https://legislatie.just.ro/test"),
        )
        con.executemany(
            "INSERT INTO provizii (act_id,locator,ord,text) VALUES (?,?,?,?)",
            [("lege-1-2020", "art1", n, text) for n, text in enumerate(["First", "Second"])],
        )
    return state


def report(locator="art1", act_id="lege-1-2020"):
    return {
        "gasit": True,
        "rand": {"exemple": {"viduri": [{"act_id": act_id, "locator": locator}]}},
        "markdown": "Saved report",
    }


def test_exact_dependencies_and_stable_ids(source):
    out = dependencies.captureaza(source, report())
    entry = out["dependente"][0]
    assert entry["stare"] == "capturat"
    assert entry["numar_prevederi"] == 2
    assert entry["metadate"]["citit_la"] == "2026-01-01"
    assert entry["metadate"]["sursa_url"] == "https://legislatie.just.ro/test"
    assert out["constatari"][0]["dependente"] == [entry["id"]]
    assert (
        out["constatari"][0]["constatare_id"] == revizuiri.constatari({"raport": report()})[0]["id"]
    )
    assert dependencies.captureaza(source, report()) == out
    with sqlite3.connect(source.corpus) as con:
        con.execute("UPDATE provizii SET text='Changed second' WHERE ord=1")
    changed = dependencies.captureaza(source, report())["dependente"][0]
    assert changed["id"] == entry["id"]
    assert changed["sha256_continut"] != entry["sha256_continut"]


def test_act_scope_and_deduplicated_links(source):
    data = report(None)
    data["contradictii"] = {"candidati": [{"a": {"act_id": "lege-1-2020"}, "b": {}}]}
    out = dependencies.captureaza(source, data)
    assert len(out["dependente"]) == 2
    assert out["dependente"][0]["nivel"] == "act"
    assert out["dependente"][0]["numar_prevederi"] == 2
    assert out["dependente"][1]["stare"] == "referinta_incompleta"
    assert out["constatari"][0]["dependente"][0] == out["constatari"][1]["dependente"][0]


@pytest.mark.parametrize(
    ("act_id", "locator", "status"),
    [("missing", "art1", "act_negasit"), ("lege-1-2020", "art99", "prevederi_negasite")],
)
def test_missing_references_are_not_captured(source, act_id, locator, status):
    entry = dependencies.captureaza(source, report(locator, act_id))["dependente"][0]
    assert entry["stare"] == status and "sha256_continut" not in entry


def test_unavailable_sources_never_created_or_migrated(source, tmp_path):
    source.corpus = tmp_path / "missing.db"
    assert dependencies.captureaza(source, report())["dependente"][0]["stare"] == (
        "sursa_indisponibila"
    )
    assert not source.corpus.exists()
    with sqlite3.connect(source.corpus) as con:
        con.execute("CREATE TABLE unrelated(value)")
    before = source.corpus.read_bytes()
    assert dependencies.captureaza(source, report())["dependente"][0]["stare"] == (
        "sursa_indisponibila"
    )
    assert source.corpus.read_bytes() == before


@pytest.mark.parametrize("bound", ["MAX_PROVISIONS", "MAX_TEXT_BYTES"])
def test_limits_do_not_emit_partial_fingerprints(source, monkeypatch, bound):
    monkeypatch.setattr(dependencies, bound, 1)
    entry = dependencies.captureaza(source, report())["dependente"][0]
    assert entry["stare"] == "limita_depasita" and "sha256_continut" not in entry


def test_runs_preserve_manifest_reviews_and_hash_contract(source, monkeypatch):
    path = dosare.cale(source)
    dossier_id = "a" * 32
    dosare.creeaza(path, {"id": dossier_id, "titlu": "Research"})
    monkeypatch.setattr("scripts.servicii._matrice_dosar", lambda qs, s: report())
    request = {"dosar_id": dossier_id, "filtre": {"emitent": "Parlamentul"}}
    first = dosare.salveaza_rulare(source, request)
    assert dosare.salveaza_rulare(source, request) == first
    payload = {k: first[k] for k in ("engine_version", "filtre", "raport", "dovezi")}
    assert first["sha256"] == hashlib.sha256(dosare._json(payload).encode()).hexdigest()
    finding_id = revizuiri.constatari(first)[0]["id"]
    revizuiri.salveaza(
        path,
        {
            "id": "b" * 32,
            "dosar_id": dossier_id,
            "rulare_id": first["id"],
            "constatare_id": finding_id,
            "revizie": 0,
            "stare": "confirmed_by_reviewer",
            "evaluator": "Reviewer",
            "motiv": "Checked",
        },
    )
    with sqlite3.connect(source.corpus) as con:
        con.execute("UPDATE provizii SET text='Updated' WHERE ord=0")
    second = dosare.salveaza_rulare(source, request)
    assert second["id"] != first["id"]
    assert second["raport"] == first["raport"]
    assert dosare.rulari(path, dossier_id, first["id"]) == first
    assert revizuiri.lista(path, dossier_id, first["id"])["constatari"][0]["stare"] == (
        "confirmed_by_reviewer"
    )
    assert revizuiri.lista(path, dossier_id, second["id"])["constatari"][0]["stare"] == (
        "unreviewed"
    )
    exported = revizuiri.lista(path, dossier_id, first["id"])
    assert dosare._json(first["dovezi"]["manifest"]) in exported["markdown"]
    assert exported["rulare"]["dovezi"]["manifest"] == first["dovezi"]["manifest"]
    restored = path.with_name("backup.db")
    dosare.backup(path, restored)
    assert dosare.rulari(restored, dossier_id, first["id"]) == first

    # Simulate the pre-manifest contract. Reads must never backfill from today's corpus.
    legacy = copy.deepcopy(first["dovezi"])
    del legacy["manifest"]
    with sqlite3.connect(path) as con:
        con.execute(
            "UPDATE rulari SET dovezi_json=?,engine_version=? WHERE id=?",
            (dosare._json(legacy), "matrice-dosar-v1", first["id"]),
        )
    old = revizuiri.lista(path, dossier_id, first["id"])
    assert "manifest" not in old["rulare"]["dovezi"]
    assert "Manifest necapturat" in old["markdown"]
