"""Tests for the increment that keeps an offline copy current.

A 742 MB release re-sent to announce a dozen new acts is a corpus a team updates twice and then
stops. These tests are about the increment being *correct*, because an update that silently drops
or half-writes an act is worse than no update: the copy still answers, just wrongly.

Four properties carry it.

**A copy's position is recorded, not inferred from its rows.** Inferring it — `max(acte.citit_la)`
— was the first design and looked free until the case in
`test_local_work_does_not_make_a_copy_skip_what_the_source_published`: a reader who upgrades an act
locally marks it *now*, pushing an inferred position past everything the source published in
between, and the next pack skips exactly that range with no symptom. Releases are stamped when they
are cut and packs move the stamp forward.

**Every write path maintains `citit_la`.** Upgrading an act's provisions from its HTML page changes
its content without re-collecting it; a write that left the mark alone would hide that act from
every offline copy for ever — not fail, just quietly never arrive.
`test_a_provision_upgrade_is_carried_by_the_next_pack` is that one.

**Replace, never merge.** An act's provisions, references, relations, strikes and edges go and come
back together. Half of an old parse beside half of a new one is a corpus nobody can reason about.

**Applying twice changes nothing.** Packs get re-sent, re-downloaded and applied out of order by
people with intermittent connections, which is the whole population this is for.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.delta import aplica, construieste, versiune


def _rec(numar: str, text: str, an: int = 2020) -> Inregistrare:
    return Inregistrare(
        titlu=f"LEGE nr. {numar}/{an}",
        tip_act="LEGE",
        numar=numar,
        an=an,
        data_vigoare=date(an, 1, 1),
        emitent="PARLAMENTUL",
        publicatie="MO",
        link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}",
        text=text,
    )


def _scrie(cale, *inregistrari):
    with depozit.deschide(cale) as con:
        for r in inregistrari:
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))


def _fixeaza(cale, act_id: str, cand: str):
    """Pin an act's mark, so a test can say 'before' and 'after' without sleeping."""
    with depozit.deschide(cale) as con:
        con.execute("UPDATE acte SET citit_la = ? WHERE id = ?", (cand, act_id))


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    cale = tmp_path / "corpus.db"
    _scrie(cale, _rec("1", "Articolul 1 Prima lege, colectată devreme."))
    _fixeaza(cale, "lege-1-2020", "2020-01-01T00:00:00+00:00")
    return cale


def test_a_copys_position_is_the_last_thing_written_into_it(corpus):
    assert versiune(str(corpus)) == "2020-01-01T00:00:00+00:00"


def test_an_empty_copy_has_no_position_and_asks_for_everything(tmp_path):
    cale = tmp_path / "gol.db"
    with depozit.deschide(cale):
        pass
    assert versiune(str(cale)) == ""


def test_a_pack_carries_only_what_arrived_after_the_stated_moment(corpus, tmp_path):
    _scrie(corpus, _rec("2", "Articolul 1 A doua lege, sosită mai târziu."))
    p = construieste(
        str(corpus), str(tmp_path / "delta.db"), "2020-01-01T00:00:00+00:00", log=lambda *_: None
    )
    assert p.acte == 1

    cx = sqlite3.connect(str(tmp_path / "delta.db"))
    try:
        assert [r[0] for r in cx.execute("SELECT id FROM acte")] == ["lege-2-2020"]
    finally:
        cx.close()


def test_applying_a_pack_brings_the_copy_to_the_packs_position(corpus, tmp_path):
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())

    _scrie(corpus, _rec("2", "Articolul 1 A doua lege."))
    construieste(str(corpus), str(tmp_path / "delta.db"), versiune(str(copie)), log=lambda *_: None)
    aplica(str(copie), str(tmp_path / "delta.db"), log=lambda *_: None)

    assert versiune(str(copie)) == versiune(str(corpus))
    cx = sqlite3.connect(str(copie))
    try:
        assert sorted(r[0] for r in cx.execute("SELECT id FROM acte")) == [
            "lege-1-2020",
            "lege-2-2020",
        ]
    finally:
        cx.close()


def test_a_rewritten_act_is_replaced_not_doubled(corpus, tmp_path):
    """Replace, never merge: half an old parse beside half a new one is unreadable."""
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())

    _scrie(corpus, _rec("1", "Articolul 1 Prima lege, recolectată cu alt text."))
    construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)
    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)

    cx = sqlite3.connect(str(copie))
    try:
        assert cx.execute("SELECT count(*) FROM acte WHERE id='lege-1-2020'").fetchone()[0] == 1
        (text,) = cx.execute(
            "SELECT text FROM provizii WHERE act_id='lege-1-2020' AND locator='text'"
        ).fetchone()
        assert "alt text" in text
        assert (
            cx.execute("SELECT count(*) FROM provizii WHERE act_id='lege-1-2020'").fetchone()[0]
            == 1
        ), "the old provisions survived beside the new ones"
    finally:
        cx.close()


def test_applying_the_same_pack_twice_changes_nothing(corpus, tmp_path):
    """Packs get re-sent and re-downloaded by people with intermittent connections."""
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())
    _scrie(corpus, _rec("2", "Articolul 1 A doua lege."))
    construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)

    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)
    cx = sqlite3.connect(str(copie))
    intai = (
        cx.execute("SELECT count(*) FROM acte").fetchone()[0],
        cx.execute("SELECT count(*) FROM provizii").fetchone()[0],
    )
    cx.close()

    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)
    cx = sqlite3.connect(str(copie))
    try:
        dupa = (
            cx.execute("SELECT count(*) FROM acte").fetchone()[0],
            cx.execute("SELECT count(*) FROM provizii").fetchone()[0],
        )
    finally:
        cx.close()
    assert intai == dupa


def test_a_pack_never_removes_an_act_it_does_not_mention(corpus, tmp_path):
    """The collector only adds and rewrites. An update that pruned would delete law the copy
    holds legitimately, and no tombstone exists to say it should."""
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())
    _scrie(corpus, _rec("2", "Articolul 1 A doua lege."))
    construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)
    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)

    cx = sqlite3.connect(str(copie))
    try:
        assert cx.execute("SELECT count(*) FROM acte WHERE id='lege-1-2020'").fetchone()[0] == 1
    finally:
        cx.close()


def test_search_finds_the_new_law_after_an_update(corpus, tmp_path):
    """`provizii_fts` is external content: a copy that gained rows but not index entries would
    answer that the new law does not exist."""
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())
    _scrie(corpus, _rec("2", "Articolul 1 Regimul juridic al concesiunilor de bunuri."))
    construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)
    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)

    with depozit.deschide(copie, readonly=True) as con:
        assert depozit.cauta(con, "concesiunilor", 5), "the new law is not searchable"


def test_a_provision_upgrade_is_carried_by_the_next_pack(corpus, tmp_path):
    """The hole this nearly had. `surse.imbogateste` rewrites an act's provisions from its HTML
    page without re-collecting the act; if that left `citit_la` alone, the act would never appear
    in a pack again and every offline copy would keep the flattened text for ever."""
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())

    from scripts.parsare import Provizie

    with depozit.deschide(corpus) as con:
        depozit.scrie_provizii(
            con,
            "lege-1-2020",
            [Provizie(locator_id="art1", text="Articolul 1 Text structurat din HTML.")],
        )

    p = construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)
    assert p.acte == 1, "a provision upgrade did not reach the pack"

    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)
    cx = sqlite3.connect(str(copie))
    try:
        assert [
            r[0] for r in cx.execute("SELECT locator FROM provizii WHERE act_id='lege-1-2020'")
        ] == ["art1"]
    finally:
        cx.close()


def test_the_graph_travels_with_the_acts_that_changed(corpus, tmp_path):
    """An increment without edges leaves the copy reasoning about new law with an old graph —
    every new amending act invisible, and every repair it made unrecorded."""
    from scripts.graf import construieste as construieste_graf

    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())
    graf_copie = tmp_path / "graf-copie.db"
    construieste_graf(str(copie), str(graf_copie), log=lambda *_: None)

    _scrie(corpus, _rec("2", "Articolul 1 Se modifică art. 1 din Legea nr. 1/2020."))
    graf_sursa = tmp_path / "graf.db"
    construieste_graf(str(corpus), str(graf_sursa), log=lambda *_: None)

    p = construieste(
        str(corpus),
        str(tmp_path / "d.db"),
        versiune(str(copie)),
        graf_db=str(graf_sursa),
        log=lambda *_: None,
    )
    assert p.muchii >= 1, "the pack carried no edges for the new act"

    aplica(str(copie), str(tmp_path / "d.db"), graf_db=str(graf_copie), log=lambda *_: None)
    gx = sqlite3.connect(str(graf_copie))
    try:
        assert (
            gx.execute("SELECT count(*) FROM muchii WHERE din_act='lege-2-2020'").fetchone()[0] >= 1
        )
    finally:
        gx.close()


def test_a_pack_with_nothing_in_it_is_valid_and_empty(corpus, tmp_path):
    p = construieste(
        str(corpus), str(tmp_path / "d.db"), versiune(str(corpus)), log=lambda *_: None
    )
    assert (p.acte, p.provizii) == (0, 0)
    assert p.de_la == p.pana_la


def test_a_pack_is_itself_a_corpus_a_reader_can_open(corpus, tmp_path):
    """So an update can be inspected before it is trusted."""
    _scrie(corpus, _rec("2", "Articolul 1 Regimul concesiunilor de bunuri proprietate publică."))
    construieste(
        str(corpus), str(tmp_path / "d.db"), "2020-01-01T00:00:00+00:00", log=lambda *_: None
    )
    with depozit.deschide(tmp_path / "d.db", readonly=True) as con:
        assert depozit.cauta(con, "concesiunilor", 5)


def test_local_work_does_not_make_a_copy_skip_what_the_source_published(corpus, tmp_path):
    """The flaw a derived watermark had, and the reason the position is recorded.

    A copy is not read-only: `surse.imbogateste` rewrites acts locally and marks them *now*. With
    the position read from the rows, that local work pushes it past everything the source wrote in
    between — and the next pack skips exactly that range, permanently and without a symptom.
    """
    from scripts.distributie import construieste as cuta_distributie
    from scripts.parsare import Provizie

    # A real copy is a release cut by `distributie`, which stamps it with where it stands. A raw
    # file copy would not carry that stamp — and this is exactly the case where inferring it fails.
    copie = tmp_path / "copie.db"
    cuta_distributie(str(corpus), str(copie), log=lambda *_: None)

    # the source publishes something, at a moment between the copy's position and "now"
    _scrie(corpus, _rec("2", "Articolul 1 Lege publicată cât timp cititorul lucra local."))
    _fixeaza(corpus, "lege-2-2020", "2020-06-01T00:00:00+00:00")

    # meanwhile the reader upgrades an act they already hold, which marks it now
    with depozit.deschide(copie) as con:
        depozit.scrie_provizii(
            con, "lege-1-2020", [Provizie(locator_id="art1", text="Structurat local.")]
        )

    p = construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)
    assert p.acte == 1, "the reader's own work hid the source's new law from them"

    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)
    cx = sqlite3.connect(str(copie))
    try:
        assert cx.execute("SELECT count(*) FROM acte WHERE id='lege-2-2020'").fetchone()[0] == 1
    finally:
        cx.close()


def test_the_recorded_position_is_the_packs_end_not_the_copys_rows(corpus, tmp_path):
    copie = tmp_path / "copie.db"
    copie.write_bytes(corpus.read_bytes())
    _scrie(corpus, _rec("2", "Articolul 1 A doua lege."))
    _fixeaza(corpus, "lege-2-2020", "2021-03-04T00:00:00+00:00")
    construieste(str(corpus), str(tmp_path / "d.db"), versiune(str(copie)), log=lambda *_: None)
    aplica(str(copie), str(tmp_path / "d.db"), log=lambda *_: None)
    assert versiune(str(copie)) == "2021-03-04T00:00:00+00:00"
