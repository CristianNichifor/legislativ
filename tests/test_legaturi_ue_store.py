import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import dosare, legaturi_ue, propuneri
from scripts import legaturi_ue_store as store
from tests import test_interventii_propuneri, test_legaturi_ue, test_propuneri
from tests.test_dosare import request as http
from tests.test_instantanee_ue import write

case = test_propuneri.case
structured = test_interventii_propuneri.structured
linked_case = test_legaturi_ue.linked_case


def request(state, selected):
    preview = legaturi_ue.preview(state, selected)
    return {
        **selected,
        "id": "d" * 32,
        "baza_sha256": preview["baza_sha256"],
        "autor": "Declared author",
        "ipoteza": "potential_gap",
        "motiv": "Compare scope",
        "obligatie": "Obligatie explicita de test.",
    }


def history(path, selected, **kwargs):
    return store.istoric(
        path,
        selected["dosar_id"],
        selected["rulare_id"],
        selected["constatare_id"],
        selected["revizie"],
        **kwargs,
    )


def test_save_retry_offline_history_export_backup_and_immutability(linked_case):
    state, path, selected = linked_case
    req = request(state, selected)
    result = store.salveaza(state, req)
    assert result["scope"] == "substantive_candidate"
    state.eu.unlink()
    assert store.salveaza(state, req) == result
    exported = history(path, selected, link_id=req["id"])
    assert exported["selectata"] == result and "Obligatie" in exported["markdown"]
    for patch in ({"motiv": "Other"}, {"autor": "Other"}, {"baza_sha256": "f" * 64}):
        with pytest.raises(ValueError, match="reutilizat"):
            store.salveaza(state, {**req, **patch})
    backup = path.with_name("backup.db")
    dosare.backup(path, backup)
    assert history(backup, selected) == exported
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 9
        for sql in ("DELETE FROM legaturi_ue", "UPDATE legaturi_ue SET creat_la='bad'"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                con.execute(sql)


def test_concurrent_retry_and_history_pages(linked_case):
    state, path, selected = linked_case
    req = request(state, selected)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.salveaza(state, req), range(2)))
    assert results[0] == results[1] and history(path, selected)["total"] == 1
    for n in range(21):
        store.salveaza(state, {**req, "id": f"{n:032x}"})
    assert len(history(path, selected)["legaturi"]) == 20
    assert len(history(path, selected, offset=20)["legaturi"]) == 2


def test_new_revision_never_inherits_link_and_foreign_id_rejected(linked_case):
    state, path, selected = linked_case
    saved = store.salveaza(state, request(state, selected))
    propuneri.salveaza(
        path,
        {
            "id": "e" * 32,
            **{k: selected[k] for k in ("dosar_id", "rulare_id", "constatare_id")},
            "revizie": 1,
            "titlu": "Next revision",
            "text": "Text changed",
            "motiv": "Change",
        },
    )
    assert history(path, {**selected, "revizie": 2})["total"] == 0
    with pytest.raises(ValueError):
        history(path, {**selected, "revizie": 2}, link_id=saved["id"])
    with pytest.raises(ValueError):
        history(path, {**selected, "dosar_id": "f" * 32})


def test_missing_source_blocks_and_stale_confirmation_cannot_save(linked_case):
    state, path, selected = linked_case
    req = request(state, selected)
    with pytest.raises(ValueError, match="Baza s-a schimbat"):
        store.salveaza(state, {**req, "baza_sha256": "0" * 64})
    state.eu.unlink()
    with pytest.raises(ValueError, match="blocata"):
        store.salveaza(state, req)
    assert history(path, selected)["total"] == 0


def test_schema8_read_no_migration_failed_write_rollback_and_upgrade(linked_case, monkeypatch):
    state, path, selected = linked_case
    req = request(state, selected)
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE legaturi_ue")
        con.execute("PRAGMA user_version=8")
    before = path.read_bytes()
    assert history(path, selected)["total"] == 0 and path.read_bytes() == before
    from scripts import legaturi_ue_schema

    original = legaturi_ue_schema.migreaza

    def fail(con):
        original(con)
        raise ValueError("rollback test")

    monkeypatch.setattr(legaturi_ue_schema, "migreaza", fail)
    with pytest.raises(ValueError, match="rollback test"):
        store.salveaza(state, req)
    assert path.read_bytes() == before
    monkeypatch.setattr(legaturi_ue_schema, "migreaza", original)
    store.salveaza(state, req)
    assert history(path, selected)["total"] == 1


def test_write_http_bounds_author_requirement_and_read_only_export(linked_case):
    state, path, selected = linked_case
    req = request(state, selected)
    url = "/api/dosare/propuneri/legaturi-ue"
    assert http(state, "POST", url, {**req, "autor": ""})[0] == 400
    assert http(state, "POST", url, {**req, "ipoteza": []})[0] == 400
    assert http(state, "POST", url, {**req, "obligatie": "Invented obligation"})[0] == 400
    assert http(state, "POST", url, {**req, "obligatie": "Obligatii"})[0] == 400
    assert http(state, "POST", url, req, origin="https://evil.test")[0] == 403
    assert http(state, "POST", url, req, length=16001)[0] == 413
    assert http(state, "POST", url, req)[0] == 200
    write(state, "Article 1\nChanged EU source", "ENG")
    assert history(path, selected)["selectata"]["baza"]["eu_snapshot"]["sursa"]["limba"] == "RON"
