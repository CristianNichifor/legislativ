import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts import achizitii_ue, cellar, date_personale, documente_proiecte, instantanee_ue
from tests.test_cellar import _manifestare

CELEX = "32018R1805"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(
        cellar, "datetime", SimpleNamespace(now=lambda tz: datetime(2026, 1, 1, tzinfo=UTC))
    )


def write(path, word, *, celex=CELEX, local=False, legacy=False):
    m = replace(_manifestare(), celex=celex)
    with cellar.deschide(path) as con:
        cellar.scrie_celex(con, celex, [m], m, "Articolul 1\n" + word + " observatie legislativa.")
        if local:
            con.execute(achizitii_ue.ATTEMPT_SCHEMA)
            con.execute(
                "INSERT OR REPLACE INTO eu_achizitii VALUES (?,?,?,?,?)",
                (celex, "2026-01-03", "2026-01-02", "eroare", "offline"),
            )
        if legacy:
            con.execute("DROP TABLE eu_instantanee")
        return instantanee_ue.citeste_curenta(con, celex)


def rows(path, table):
    with sqlite3.connect(path) as con:
        return con.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()


def detail(path, celex=CELEX, **kwargs):
    return achizitii_ue.detaliu(SimpleNamespace(eu=path), celex, **kwargs)


def test_local_precedence_all_history_and_repeated_activation(tmp_path):
    public, previous, target = (tmp_path / n for n in ("public?#.db", "previous.db", "target.db"))
    old = write(previous, "anterior")
    local = write(previous, "personalizat", local=True)
    published = write(public, "publicat", local=True)
    other = write(public, "adaugat", celex="32014L0024")
    before = {p: p.read_bytes() for p in (public, previous)}
    date_personale.prepare_eu(public, previous, target)
    assert all(p.read_bytes() == b for p, b in before.items())
    assert detail(target)["curenta"]["id"] == local["id"]
    assert rows(target, "eu_achizitii") == rows(previous, "eu_achizitii")
    for observation in (old, local, published):
        assert detail(target, snapshot_id=observation["id"]) == observation
    assert detail(target, "32014L0024")["curenta"]["id"] == other["id"]
    with cellar.deschide(target, readonly=True) as con:
        assert cellar.cauta_ue(con, "personalizat")[0]["celex"] == CELEX
        assert not cellar.cauta_ue(con, "publicat")
    again = tmp_path / "again.db"
    date_personale.prepare_eu(public, target, again)
    for table in date_personale.TABLES:
        assert rows(again, table) == rows(target, table)
    assert target.stat().st_mode & 0o777 == 0o600


def test_public_update_archives_legacy_current_without_new_timestamp(tmp_path):
    public, previous, target = (tmp_path / n for n in ("public.db", "previous.db", "target.db"))
    old = write(previous, "anterior", legacy=True)
    new = write(public, "publicat", legacy=True)
    removed = write(previous, "eliminat", celex="32014L0024", legacy=True)
    date_personale.prepare_eu(public, previous, target)
    assert detail(target)["curenta"]["id"] == new["id"]
    for observation in (old, new):
        assert detail(target, snapshot_id=observation["id"]) == observation
    assert detail(target, "32014L0024")["curenta"]["id"] == removed["id"]
    assert rows(target, "eu_achizitii") == []


def test_first_activation_does_not_adopt_published_import_attempts(tmp_path):
    public, target = tmp_path / "public.db", tmp_path / "target.db"
    observation = write(public, "publicat", local=True)
    date_personale.prepare_eu(public, None, target)
    assert detail(target)["curenta"]["id"] == observation["id"]
    assert detail(target)["incercare"] is None
    assert rows(target, "eu_instantanee") == rows(public, "eu_instantanee")


def test_metadata_only_local_attempts_survive(tmp_path):
    public, previous, target = (tmp_path / n for n in ("public.db", "previous.db", "target.db"))
    write(previous, "personalizat", local=True)
    write(public, "publicat")
    with cellar.deschide(previous) as con:
        con.execute("DELETE FROM eu_acte")
        con.execute("UPDATE eu_achizitii SET reusit_la=NULL,stare='metadate'")
        con.execute("UPDATE eu_manifestari SET format='pdf'")
    date_personale.prepare_eu(public, previous, target)
    assert rows(target, "eu_achizitii") == rows(previous, "eu_achizitii")
    assert rows(target, "eu_manifestari") == rows(previous, "eu_manifestari")
    current = detail(target)["curenta"]
    assert "publicat" in detail(target, snapshot_id=current["id"])["sursa"]["text"]


def test_private_generation_accepts_imports_and_next_activation_retains_them(tmp_path):
    public, target, next_target = (tmp_path / n for n in ("public.db", "target.db", "next.db"))
    initial = write(public, "publicat")
    date_personale.prepare_eu(public, None, target)
    public_bytes = public.read_bytes()
    imported = write(target, "personalizat", local=True)
    assert public.read_bytes() == public_bytes
    date_personale.prepare_eu(public, target, next_target)
    assert detail(next_target)["curenta"]["id"] == imported["id"]
    assert detail(next_target, snapshot_id=initial["id"]) == initial
    with sqlite3.connect(next_target) as con, pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM eu_instantanee")


def test_rollback_uses_latest_private_history_with_older_public_release(tmp_path):
    old_public, new_public, first, latest, rollback = (
        tmp_path / n for n in ("old.db", "new.db", "first.db", "latest.db", "rollback.db")
    )
    old = write(old_public, "anterior")
    newer = write(new_public, "publicat")
    date_personale.prepare_eu(old_public, None, first)
    date_personale.prepare_eu(new_public, first, latest)
    imported = write(latest, "personalizat", local=True)
    private_only = write(latest, "exclusiv", celex="32014L0024", local=True)
    date_personale.prepare_eu(old_public, latest, rollback)
    assert detail(rollback)["curenta"]["id"] == imported["id"]
    assert detail(rollback, "32014L0024")["curenta"]["id"] == private_only["id"]
    for observation in (old, newer, imported):
        assert detail(rollback, snapshot_id=observation["id"]) == observation
    assert rows(rollback, "eu_achizitii") == rows(latest, "eu_achizitii")


@pytest.mark.parametrize("empty", [False, True])
def test_public_metadata_replaces_previous_unprotected_set(tmp_path, empty):
    public, previous, target = (tmp_path / n for n in ("public.db", "previous.db", "target.db"))
    write(previous, "anterior")
    write(public, "publicat")
    with sqlite3.connect(public) as con:
        if empty:
            con.execute("DELETE FROM eu_manifestari")
        else:
            con.execute("UPDATE eu_manifestari SET item_url='https://example.test/new'")
        con.execute("CREATE TABLE unrelated (secret TEXT)")
        con.execute(
            "CREATE TRIGGER source_only AFTER INSERT ON eu_acte "
            "BEGIN DELETE FROM eu_manifestari; END"
        )
    date_personale.prepare_eu(public, previous, target)
    assert rows(target, "eu_manifestari") == rows(public, "eu_manifestari")
    with sqlite3.connect(target) as con:
        assert not con.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN ('unrelated','source_only')"
        ).fetchall()


def test_row_bound_and_index_failure_cleanup(tmp_path, monkeypatch):
    public, target = tmp_path / "public.db", tmp_path / "target.db"
    write(public, "publicat")
    with monkeypatch.context() as patch:
        patch.setattr(date_personale, "MAX_ROWS", 0)
        with pytest.raises(ValueError, match="limit"):
            date_personale.prepare_eu(public, None, target)

    def fail(*args):
        raise RuntimeError("index failed")

    monkeypatch.setattr(cellar, "scrie_provizii_celex", fail)
    with pytest.raises(RuntimeError, match="index failed"):
        date_personale.prepare_eu(public, None, target)
    assert not target.exists() and not list(tmp_path.glob(".eu-*"))


@pytest.mark.parametrize(
    "failure", ["view", "columns", "primary_key", "hash", "archive", "collision", "limit"]
)
def test_rejected_input_leaves_no_target_or_temporary_files(tmp_path, monkeypatch, failure):
    public, previous, target = (tmp_path / n for n in ("public.db", "previous.db", "target.db"))
    write(public, "publicat")
    write(previous, "personalizat", local=True)
    with sqlite3.connect(public) as con:
        if failure == "view":
            con.execute("ALTER TABLE eu_acte RENAME TO original")
            con.execute("CREATE VIEW eu_acte AS SELECT * FROM original")
        elif failure == "columns":
            con.execute("ALTER TABLE eu_acte ADD COLUMN unexpected TEXT")
        elif failure == "primary_key":
            con.execute("ALTER TABLE eu_acte RENAME TO original")
            con.execute("CREATE TABLE eu_acte AS SELECT * FROM original")
        elif failure == "hash":
            con.execute("UPDATE eu_acte SET text_sha256='invalid'")
        elif failure == "archive":
            con.execute("DROP TRIGGER eu_instantanee_no_update")
            con.execute("UPDATE eu_instantanee SET snapshot_json='{}'")
        elif failure == "collision":
            old = rows(previous, "eu_instantanee")[0]
            altered = json.loads(old[2])
            altered["extra"] = "conflicting bytes for the same payload ID"
            con.execute(
                "INSERT INTO eu_instantanee VALUES (?,?,?)", (old[0], old[1], json.dumps(altered))
            )
        elif failure == "limit":
            monkeypatch.setattr(date_personale, "MAX_BYTES", 1)
    before = {p: p.read_bytes() for p in (public, previous)}
    with pytest.raises(ValueError):
        date_personale.prepare_eu(public, previous, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".eu-*"))
    assert all(p.read_bytes() == b for p, b in before.items())


def test_existing_target_and_missing_previous_fail_closed(tmp_path):
    public = tmp_path / "public.db"
    write(public, "publicat")
    with pytest.raises(FileExistsError):
        date_personale.prepare_eu(public, None, public)
    missing, target = tmp_path / "missing.db", tmp_path / "target.db"
    with pytest.raises(sqlite3.OperationalError):
        date_personale.prepare_eu(public, missing, target)
    assert not missing.exists() and not target.exists()


def test_document_store_explicit_override_and_legacy_fallback(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "datasets/release/initiative.db")
    assert documente_proiecte.cale_store(state) == state.initiative.with_suffix(".documente.db")
    state.documente_db = tmp_path / "private/initiative.documente.db"
    assert documente_proiecte.cale_store(state) == state.documente_db
    state.initiative = tmp_path / "datasets/next/initiative.db"
    assert documente_proiecte.cale_store(state) == state.documente_db
    state.documente_db = None
    with pytest.raises(TypeError):
        documente_proiecte.cale_store(state)
