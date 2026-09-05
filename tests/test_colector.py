"""Tests for the corpus walk, offline.

The collector's judgement is in three places — which types it keeps, how it derives a year the
API leaves blank, and whether it resumes — and all three are tested here through an injected
client so nothing touches the network. The polite-concurrency and backoff behaviour is a property
of the live service and is not asserted here; it is measured, and the numbers live in the module
docstring.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare, colecteaza, tip_normativ


def _rec(tip, numar, an=None, vig=None, titlu="", text="corp"):
    return Inregistrare(
        titlu=titlu or f"{tip} nr. {numar}",
        tip_act=tip,
        numar=numar,
        an=an,
        data_vigoare=vig,
        emitent="X",
        publicatie="MO",
        link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}00",
        text=text,
    )


class _FakeClient:
    """Serves canned pages by number and refreshes no token."""

    def __init__(self, pagini: dict[int, list[Inregistrare]]):
        self._p = pagini

    def token(self) -> str:
        return "t"

    def search(self, *, pagina: int, pe_pagina: int = 10, **_):
        return self._p.get(pagina, [])


def test_only_the_six_normative_types_are_kept():
    assert tip_normativ("LEGE") == "lege"
    assert tip_normativ("ORDONANȚĂ DE URGENȚĂ") == "oug"
    assert tip_normativ("ADEVERINȚĂ") is None
    assert tip_normativ("AMENAJAMENT") is None


def test_the_year_is_recovered_when_the_api_leaves_it_blank():
    """The API's `An` field comes back empty, so the year is taken from the in-force date, then
    the title. An act with no recoverable year is dropped rather than keyed wrong."""
    assert act_din_inregistrare(_rec("LEGE", "98", vig=date(2016, 5, 26))).id == "lege-98-2016"
    assert (
        act_din_inregistrare(_rec("LEGE", "98", titlu="LEGE nr. 98 din 2016")).id == "lege-98-2016"
    )
    assert act_din_inregistrare(_rec("LEGE", "98")) is None  # no year anywhere


def test_a_dotted_number_is_cleaned():
    """`nr. 1.802` is order 1802, not 1."""
    a = act_din_inregistrare(_rec("ORDIN", "1.802", vig=date(2014, 1, 1)))
    assert a.id == "ordin-1802-2014"


def test_a_run_keeps_normative_acts_and_skips_the_rest(tmp_path: Path):
    db = tmp_path / "c.db"
    client = _FakeClient(
        {
            1: [
                _rec("LEGE", "10", vig=date(2020, 1, 1)),
                _rec("ADEVERINȚĂ", "5", vig=date(2020, 1, 1)),
                _rec("HOTĂRÂRE", "20", vig=date(2020, 2, 1)),
            ],
            2: [_rec("AMENAJAMENT", "1", vig=date(2020, 1, 1))],
        }
    )
    p = colecteaza(str(db), client=client, lucratori=2, pagina_start=1, pagina_stop=2)
    assert p.acte_scrise == 2 and p.sarite_tip == 2
    with depozit.deschide(db) as con:
        assert {a.id for a in depozit.acte(con)} == {"lege-10-2020", "hg-20-2020"}


def test_a_second_run_resumes_and_does_nothing(tmp_path: Path):
    db = tmp_path / "c.db"
    client = _FakeClient({1: [_rec("LEGE", "10", vig=date(2020, 1, 1))]})
    colecteaza(str(db), client=client, lucratori=1, pagina_start=1, pagina_stop=1)
    again = colecteaza(str(db), client=client, lucratori=1, pagina_start=1, pagina_stop=1)
    assert again.pagini == 0


def test_the_full_text_is_searchable_after_a_run(tmp_path: Path):
    db = tmp_path / "c.db"
    client = _FakeClient(
        {
            1: [
                _rec(
                    "LEGE",
                    "10",
                    vig=date(2020, 1, 1),
                    text="autoritatea contractantă publică anunțul",
                )
            ]
        }
    )
    colecteaza(str(db), client=client, lucratori=1, pagina_start=1, pagina_stop=1)
    with depozit.deschide(db) as con:
        # "publica" folds to "publică": diacritic-insensitive FTS over the API text
        assert depozit.cauta(con, "publica", 5)
