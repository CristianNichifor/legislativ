"""Tests for the corpus store.

The one that matters is `test_nothing_is_silently_dropped`. It exists because the first schema
keyed provisions on (act_id, locator), Legea 98/2016 went in with 1 435 provisions and came out
with 1 404, and nothing said so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import depozit
from scripts.parsare import ActParsat, Provizie, din_fisier
from scripts.referinte import Act

SURSE = Path(__file__).resolve().parent.parent / "sources"


@pytest.fixture(scope="module")
def lege():
    return din_fisier(
        SURSE / "lege-98-2016.html.gz",
        url="https://legislatie.just.ro/Public/DetaliiDocument/178667",
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "corpus.db"


def test_an_act_round_trips(db, lege):
    (r,) = depozit.importa(db, [lege])
    assert r.act_id == "lege-98-2016" and r.provizii == len(lege.provizii)
    with depozit.deschide(db) as con:
        assert [a.id for a in depozit.acte(con)] == ["lege-98-2016"]
        row = con.execute("SELECT * FROM acte WHERE id='lege-98-2016'").fetchone()
        assert row["id_portal"] == "178667" and row["id_act_portal"] == "290673"


def test_nothing_is_silently_dropped(db, lege):
    """A locator is not unique — an article and an unnumbered block inside it produce the same
    one — so `ord` carries the identity and the writer counts the rows back."""
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["provizii"] == len(lege.provizii)


def test_the_writer_refuses_rather_than_lose_a_row(db):
    """If the count ever disagrees again, the import fails instead of returning a short corpus."""
    dublu = ActParsat(
        act=Act("lege", "1", 2020),
        titlu="LEGE nr. 1 din 1 ianuarie 2020",
        provizii=(Provizie("art1", "unu"), Provizie("art1", "doi")),
    )
    (r,) = depozit.importa(db, [dublu])
    assert r.provizii == 2
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["provizii"] == 2


def test_reimporting_replaces_rather_than_merges(db, lege):
    depozit.importa(db, [lege])
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["provizii"] == len(lege.provizii)
        assert depozit.rezumat(con)["acte"] == 1


def test_search_ignores_diacritics_in_both_directions(db, lege):
    """Half the corpus predates the comma-below letters. A search for `hotarare` that misses
    `hotărâre` is a search nobody can use."""
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        fara = depozit.cauta(con, "achizitie publica", 5)
        cu = depozit.cauta(con, "achiziție publică", 5)
        assert fara and cu
        assert {r["locator"] for r in fara} & {r["locator"] for r in cu}


def test_the_portals_relation_flags_are_stored_as_assumed(db, lege):
    """A flag says a relation exists, not what it points at. Stored as anything firmer, it
    would look like a fact somebody could act on."""
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        rows = con.execute("SELECT * FROM relatii WHERE din_act='lege-98-2016'").fetchall()
        assert len(rows) == 4
        assert {r["sursa"] for r in rows} == {"portal"}
        assert {r["incredere"] for r in rows} == {"assumed"}


def test_a_page_is_fetched_once_ever(db):
    """The cache is the collector's most important property: this reads a ministry's server on
    behalf of a political party, and it should ask for a document once."""
    url = "https://legislatie.just.ro/Public/DetaliiDocument/1"
    with depozit.deschide(db) as con:
        assert depozit.din_cache(con, url) is None
        depozit.pune_in_cache(con, url, b"<html>x</html>", 200)
    with depozit.deschide(db) as con:
        assert depozit.din_cache(con, url) == b"<html>x</html>"
        assert depozit.rezumat(con)["pagini_in_cache"] == 1


def test_a_failed_fetch_is_not_served_from_cache(db):
    url = "https://legislatie.just.ro/Public/DetaliiDocument/2"
    with depozit.deschide(db) as con:
        depozit.pune_in_cache(con, url, b"Error", 403)
        assert depozit.din_cache(con, url) is None
