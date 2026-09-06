"""Full-text search with type/year filters and pagination (the localhost SQLite path)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import depozit
from scripts.parsare import ActParsat, Provizie
from scripts.referinte import Act


@pytest.fixture
def db(tmp_path: Path) -> Path:
    cale = tmp_path / "corpus.db"
    # two acts of a different type and year, both matching «cadru»
    depozit.importa(
        cale,
        [
            ActParsat(
                act=Act("lege", "10", 2016),
                titlu="LEGE nr. 10 din 2016",
                provizii=(Provizie("art1", "dispoziții cadru din 2016"),),
            ),
            # the corpus keys acts by slug (`hg`), not `hotarare` — the filter matches the slug
            ActParsat(
                act=Act("hg", "20", 2020),
                titlu="HOTĂRÂRE nr. 20 din 2020",
                provizii=(Provizie("art1", "normă cadru din 2020"),),
            ),
        ],
    )
    return cale


def test_filters_by_act_type(db):
    with depozit.deschide(db) as con:
        doar_hg = depozit.cauta(con, "cadru", tip="hg")
        assert [r["act_id"] for r in doar_hg] == ["hg-20-2020"]
        assert depozit.cauta_numar(con, "cadru") == 2
        assert depozit.cauta_numar(con, "cadru", tip="hg") == 1


def test_filters_by_year_range(db):
    with depozit.deschide(db) as con:
        recent = depozit.cauta(con, "cadru", an_min=2018)
        assert [r["act_id"] for r in recent] == ["hg-20-2020"]
        assert depozit.cauta_numar(con, "cadru", an_max=2017) == 1


def test_paginates_with_offset(db):
    with depozit.deschide(db) as con:
        prima = depozit.cauta(con, "cadru", 1, offset=0)
        a_doua = depozit.cauta(con, "cadru", 1, offset=1)
        assert len(prima) == 1 and len(a_doua) == 1
        assert prima[0]["act_id"] != a_doua[0]["act_id"]


def test_no_filter_counts_every_match(db):
    with depozit.deschide(db) as con:
        assert depozit.cauta_numar(con, "cadru") == 2
        assert len(depozit.cauta(con, "cadru", 25)) == 2


def test_shard_filter_matches_the_sqlite_one():
    # the browser path filters on the same index metadata; keep the two rules in step
    from scripts.cauta_web import _trece_filtru

    hg2020 = {"tip": "hg", "an": 2020}
    assert _trece_filtru(hg2020, None, None, None) is True
    assert _trece_filtru(hg2020, "hg", None, None) is True
    assert _trece_filtru(hg2020, "lege", None, None) is False
    assert _trece_filtru(hg2020, None, 2018, None) is True
    assert _trece_filtru(hg2020, None, None, 2019) is False
