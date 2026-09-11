"""The published copy is the only file a reader ever touches, and it is built by deletion.

Everything worth testing here is a property the browser silently depends on: no WAL, no build-time
tables, and a search index that still answers after the file has been rewritten.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts import depozit
from scripts.publica import DE_ARUNCAT, publica


def _corpus(cale) -> None:
    """A corpus small enough to rebuild in a test, shaped like the real one."""
    with depozit.deschide(str(cale)) as con:
        con.execute("PRAGMA journal_mode=WAL")  # what a live corpus is in
        for n in range(1, 6):
            con.execute(
                "INSERT INTO acte (id, tip, numar, an, titlu, id_portal, citit_la)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"lege-{n}-2020", "lege", str(n), 2020, f"Legea {n}", str(n), "2026-01-01"),
            )
            for art in range(1, 4):
                text = f"Articolul {art} priveste achizitiile publice si contractele sectoriale."
                cur = con.execute(
                    "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?,?,?,?)",
                    (f"lege-{n}-2020", f"art{art}", art, text),
                )
                # `content='provizii'` means fts5 is not maintained for us — see depozit.SCHEMA.
                con.execute(
                    "INSERT INTO provizii_fts(rowid, text, act_id, locator) VALUES (?,?,?,?)",
                    (cur.lastrowid, text, f"lege-{n}-2020", f"art{art}"),
                )
        # The build-time bulk the reader never queries.
        con.execute(
            "INSERT INTO documente (id_portal, cheie_act, tip, titlu, text, adus_la)"
            " VALUES (?,?,?,?,?,?)",
            (
                "1",
                "lege-1-2020",
                "lege",
                "Legea 1",
                "<html>" + "x" * 50_000 + "</html>",
                "2026-01-01",
            ),
        )
        con.commit()


def test_copia_publicata_nu_mai_are_wal(tmp_path):
    """`immutable=1` refuses a database with a `-wal` sidecar, and that is the mode the reader uses.

    A plain file copy of a live corpus keeps WAL, so the browser would fail with `disk I/O error`
    on the very first query — the failure that cost the most time to diagnose.
    """
    sursa = tmp_path / "corpus.db"
    _corpus(sursa)
    tinta = publica(sursa, tmp_path / "publicat.db")

    con = sqlite3.connect(tinta)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    finally:
        con.close()
    assert not (tmp_path / "publicat.db-wal").exists()

    # The real proof: open it the way the worker does.
    con = sqlite3.connect(f"file:{tinta}?immutable=1", uri=True)
    try:
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 5
    finally:
        con.close()


def test_arunca_doar_tabelele_de_construire(tmp_path):
    sursa = tmp_path / "corpus.db"
    _corpus(sursa)
    tinta = publica(sursa, tmp_path / "publicat.db")

    con = sqlite3.connect(tinta)
    try:
        ramase = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()

    assert not ramase & set(DE_ARUNCAT), (
        f"au rămas tabele de construire: {ramase & set(DE_ARUNCAT)}"
    )
    assert {"acte", "provizii", "provizii_fts"} <= ramase


def test_cautarea_supravietuieste_rescrierii(tmp_path):
    """fts5 here keeps no copy of the text, so VACUUM must not orphan the index behind it."""
    sursa = tmp_path / "corpus.db"
    _corpus(sursa)
    tinta = publica(sursa, tmp_path / "publicat.db")

    con = sqlite3.connect(f"file:{tinta}?immutable=1", uri=True)
    try:
        gasite = con.execute(
            "SELECT count(*) FROM (SELECT act_id FROM provizii_fts"
            " WHERE provizii_fts MATCH 'achizitiile')"
        ).fetchone()[0]
    finally:
        con.close()
    assert gasite == 15


def test_refuza_o_sursa_care_lipseste(tmp_path):
    with pytest.raises(SystemExit):
        publica(tmp_path / "nu-exista.db", tmp_path / "publicat.db")


def test_publica_initiative_fara_importuri_private(tmp_path):
    sursa = tmp_path / "initiative.db"
    con = sqlite3.connect(sursa)
    try:
        con.execute("CREATE TABLE initiative(plx_id TEXT PRIMARY KEY, titlu TEXT)")
        con.execute("CREATE TABLE initiative_tinta(plx_id TEXT, act_id TEXT)")
        con.execute("CREATE TABLE documente(id TEXT, plx_id TEXT, text TEXT)")
        con.execute("CREATE TABLE surse(id TEXT, html TEXT)")
        con.execute("CREATE TABLE cache(k TEXT, v TEXT)")
        con.execute("CREATE TABLE progres(k TEXT, v TEXT)")
        con.execute("INSERT INTO initiative VALUES ('plx-1', 'Proiect public')")
        con.execute("INSERT INTO initiative_tinta VALUES ('plx-1', 'lege-1')")
        con.execute("INSERT INTO documente VALUES ('doc-1', 'plx-1', 'privat')")
        con.execute("INSERT INTO surse VALUES ('src-1', '<html>')")
        con.commit()
    finally:
        con.close()

    tinta = publica(sursa, tmp_path / "initiative-publicat.db", verifica="auxiliar")
    con = sqlite3.connect(f"file:{tinta}?immutable=1", uri=True)
    try:
        ramase = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"initiative", "initiative_tinta"} <= ramase
        assert not ramase & set(DE_ARUNCAT)
        assert con.execute("SELECT titlu FROM initiative").fetchone()[0] == "Proiect public"
    finally:
        con.close()
