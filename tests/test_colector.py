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
from scripts.colector import act_din_inregistrare, colecteaza, este_normativ, slug_tip


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


def test_the_six_normative_types_get_canonical_slugs():
    assert slug_tip("LEGE") == "lege"
    assert slug_tip("ORDONANȚĂ DE URGENȚĂ") == "oug"
    assert este_normativ("LEGE") and not este_normativ("ADEVERINȚĂ")


def test_other_types_are_kept_with_a_derived_slug_not_dropped():
    """Collection keeps everything keyable; the codes, the norms and the drafts matter. Type
    filtering is the product's job at query time, not the collector's."""
    assert slug_tip("CODUL FISCAL") == "codul-fiscal"
    assert slug_tip("PROIECT DE LEGE") == "proiect-de-lege"
    assert slug_tip("NORMĂ") == "norma"


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


def test_a_run_keeps_every_keyable_act_including_drafts(tmp_path: Path):
    """A numbered draft is kept — it is what duplicate-check needs. Only a numberless record
    (no citable identity) is skipped."""
    db = tmp_path / "c.db"
    client = _FakeClient(
        {
            1: [
                _rec("LEGE", "10", vig=date(2020, 1, 1)),
                _rec("PROIECT DE LEGE", "5", vig=date(2020, 1, 1)),
                _rec("LISTĂ", "", vig=date(2020, 1, 1)),  # numberless -> skipped
            ],
            2: [_rec("CODUL FISCAL", "227", vig=date(2015, 9, 1))],
        }
    )
    p = colecteaza(str(db), client=client, lucratori=2, pagina_start=1, pagina_stop=2)
    assert p.acte_scrise == 3 and p.sarite_tip == 1
    with depozit.deschide(db) as con:
        ids = {a.id for a in depozit.acte(con)}
    assert ids == {"lege-10-2020", "proiect-de-lege-5-2020", "codul-fiscal-227-2015"}


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
