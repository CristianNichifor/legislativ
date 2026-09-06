"""Tests for the register of struck provisions nobody repaired.

The load-bearing one is `test_an_amendment_that_predates_the_decision_is_not_a_repair`. Every
provision the Court strikes has been amended at some point — that is usually how it came to be
challenged — and a register that accepts any amendment as a repair reports an empty list and
looks like it worked.
"""

from __future__ import annotations

from datetime import date

from scripts.decizii import Proviziune
from scripts.neconstitutional import Lovitura, Muchie, registru

LOVITURA = Lovitura(
    decizie="decizie-101-1996",
    publicat=date(1996, 1, 17),
    proviziune=Proviziune(
        "lege-15-1994", "art34", "art. 34 din Legea nr. 15/1994", "neconstitutional"
    ),
    definitiva=True,
)
TIPURI = {"lege-15-1994": "lege", "lege-20-1996": "lege", "ordin-1459-1995": "ordin"}


def _registru(muchii: list[Muchie], **kw):
    return registru(
        [LOVITURA],
        muchii,
        TIPURI,
        la_data=date(2026, 9, 6),
        complet_pentru=frozenset({"lege"}),
        **kw,
    )


def test_a_provision_nobody_touched_after_the_decision_is_reported_unrepaired():
    (n,) = _registru([])
    assert n.lovitura is LOVITURA
    assert n.reparatii == ()
    # 45 days from publication under art. 147 (1) — art. 145 (1) before the 2003 revision.
    assert n.termen == date(1996, 3, 2)
    assert n.zile_de_la_termen == (date(2026, 9, 6) - date(1996, 3, 2)).days


def test_an_amendment_after_the_decision_counts_as_a_repair_and_clears_the_row():
    assert (
        _registru([Muchie("lege-20-1996", "lege-15-1994", "art34", "modifica", date(1996, 2, 1))])
        == []
    )


def test_an_amendment_that_predates_the_decision_is_not_a_repair():
    reparat = _registru(
        [Muchie("lege-20-1996", "lege-15-1994", "art34", "modifica", date(1995, 6, 1))]
    )
    assert len(reparat) == 1
    # It is still worth showing: it is what a reader will ask about first.
    assert [a.din_act for a in reparat[0].atingeri] == ["lege-20-1996"]


def test_amending_the_whole_act_repairs_a_provision_inside_it():
    assert (
        _registru([Muchie("lege-20-1996", "lege-15-1994", "", "modifica", date(1996, 2, 1))]) == []
    )


def test_amending_a_paragraph_of_the_struck_article_counts_as_a_repair():
    # Generous on purpose, as in `vid.py`: a quiet register costs a missed row, a loud one costs
    # a researcher standing behind a finding that dissolves.
    assert (
        _registru(
            [Muchie("lege-20-1996", "lege-15-1994", "art34.alin2", "modifica", date(1996, 2, 1))]
        )
        == []
    )


def test_amending_a_different_article_is_not_a_repair():
    ramase = _registru(
        [Muchie("lege-20-1996", "lege-15-1994", "art35", "modifica", date(1996, 2, 1))]
    )
    assert len(ramase) == 1
    assert ramase[0].atingeri == ()


def test_a_mere_reference_is_not_a_repair():
    ramase = _registru(
        [Muchie("lege-20-1996", "lege-15-1994", "art34", "refera", date(1996, 2, 1))]
    )
    assert len(ramase) == 1


def test_an_instrument_that_cannot_amend_a_law_is_a_near_miss_not_a_repair():
    # An ordin of a minister cannot amend a law. Accepting it as a repair would clear the row
    # on the strength of an edge that is either a parse error or an illegality.
    ramase = _registru(
        [Muchie("ordin-1459-1995", "lege-15-1994", "art34", "modifica", date(1996, 4, 1))]
    )
    assert len(ramase) == 1
    assert [a.din_act for a in ramase[0].atingeri] == ["ordin-1459-1995"]
    assert any("rang" in lim for lim in ramase[0].limitari)


def test_a_corpus_not_complete_for_the_repairing_instrument_downgrades_the_finding():
    (n,) = registru([LOVITURA], [], TIPURI, la_data=date(2026, 9, 6), complet_pentru=frozenset())
    assert n.severitate == "blocking"
    assert any("complet" in lim for lim in n.limitari)


def test_a_strike_that_was_still_open_to_recourse_cannot_be_called_settled():
    lov = Lovitura(LOVITURA.decizie, LOVITURA.publicat, LOVITURA.proviziune, definitiva=False)
    (n,) = registru([lov], [], TIPURI, la_data=date(2026, 9, 6), complet_pentru=frozenset({"lege"}))
    assert n.severitate == "blocking"
    assert any("recurs" in lim for lim in n.limitari)


def test_an_article_150_abrogation_has_no_45_day_clock():
    # The provision was abrogated by the Constitution's own entry into force. There was never a
    # window in which Parliament was supposed to align it, so an overdue count would be invented.
    lov = Lovitura(
        "decizie-16-1994",
        date(1994, 3, 1),
        Proviziune("cod-penal", "art224", "art. 224 din Codul penal", "abrogat_constitutional"),
        definitiva=True,
    )
    (n,) = registru(
        [lov],
        [],
        {"cod-penal": "lege"},
        la_data=date(2026, 9, 6),
        complet_pentru=frozenset({"lege"}),
    )
    assert n.termen is None
    assert n.zile_de_la_termen is None
    assert any("150" in lim for lim in n.limitari)


def test_a_provision_whose_act_is_unknown_is_not_in_the_register():
    lov = Lovitura(
        "decizie-4-2004",
        date(2004, 1, 1),
        Proviziune(None, "art27", "art. 27", "neconstitutional"),
        definitiva=None,
    )
    assert registru([lov], [], {}, la_data=date(2026, 9, 6), complet_pentru=frozenset()) == []


def test_a_provision_struck_by_several_decisions_is_one_row_in_the_summary():
    """The question is "which provisions are still unconstitutional", not "which strikes exist".

    A provision reaches the register once per decision that struck it — `cod-penal art224` is
    struck by four separate decisions in the real corpus — and listing it four times answers a
    question nobody asked while hiding how many distinct provisions there actually are.
    """
    from scripts.neconstitutional import sumar

    prov = Proviziune("cod-penal", "art224", "art. 224 din Codul penal", "abrogat_constitutional")
    rows = registru(
        [
            Lovitura("decizie-33-1993", date(1993, 6, 1), prov, True),
            Lovitura("decizie-16-1994", date(1994, 3, 1), prov, True),
            Lovitura(
                "decizie-59-1994",
                date(1994, 9, 15),
                Proviziune("cod-muncii", "art175", "art. 175", "neconstitutional"),
                True,
            ),
        ],
        [],
        {"cod-penal": "lege", "cod-muncii": "lege"},
        la_data=date(2026, 9, 6),
        complet_pentru=frozenset({"lege"}),
    )
    text = sumar(rows)
    assert text.count("cod-penal art224") == 1, "the provision was listed once per decision"
    assert "2 decizii" in text or "2 decizii" in text.replace("  ", " ")
    assert "cod-muncii art175" in text


def test_the_summary_names_the_earliest_decision_that_struck_it():
    """The clock runs from the first strike, so that is the decision a reader needs."""
    from scripts.neconstitutional import sumar

    prov = Proviziune("cod-penal", "art224", "art. 224", "abrogat_constitutional")
    rows = registru(
        [
            Lovitura("decizie-tarziu", date(1998, 1, 1), prov, True),
            Lovitura("decizie-devreme", date(1993, 6, 1), prov, True),
        ],
        [],
        {"cod-penal": "lege"},
        la_data=date(2026, 9, 6),
        complet_pentru=frozenset({"lege"}),
    )
    assert "decizie-devreme" in sumar(rows)
