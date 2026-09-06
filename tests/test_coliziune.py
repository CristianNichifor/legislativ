"""Tests for checking a draft against provisions the Court struck and nobody repaired.

Two properties carry this module, and both are about refusing to be louder than the evidence.

The first is the severity inversion. `neconstitutional.py`'s `severitate` is *evidential* —
`blocking` there means the corpus cannot vouch for the row. The linter's is about *weight* —
`blocking` means stop. Passing one through as the other would take precisely the rows the data
cannot stand behind and put them in front of an MP as verdicts, which is the failure this whole
package is built to refuse. `test_a_row_the_register_cannot_vouch_for_never_blocks` pins it.

The second is that reach is graded rather than boolean. `neconstitutional._atinge` is generous on
purpose, because a register is read with its caveats. A finding on screen while somebody types is
read as a verdict, so only the grades where the cited text is *itself* without legal effect are
allowed to block.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.coliziune import Coliziune, coliziuni, raport

DRAFT_EXACT = "Art. 1. — Se modifică art. 5 alin. (7) din Legea nr. 59/1993, care va avea..."


def rand(**kw) -> dict:
    """One register row as `servicii.construieste_neconstitutional` ships it."""
    return {
        "act_id": "lege-59-1993",
        "locator": "art5.alin7",
        "fel": "neconstitutional",
        # The span `decizii.py` actually quotes: the provision as the decision names it.
        "text": "art. 5 alin. (7) din Legea nr. 59/1993",
        "decizie": "decizie-9-1994",
        "publicat": "1994-11-25",
        "definitiva": True,
        "termen": "1995-01-09",
        "zile_de_la_termen": 11_000,
        "severitate": "material",
        "limitari": [],
    } | kw


def test_a_draft_touching_a_struck_provision_is_caught_and_blocks():
    (c,) = coliziuni(DRAFT_EXACT, [rand()])
    assert c.act_id == "lege-59-1993"
    assert c.locator == "art5.alin7"
    assert c.potrivire == "exact"
    assert c.severitate == "blocking"
    assert "decizie-9-1994" in c.motiv
    assert "11000" in c.motiv or "11.000" in c.motiv or "de 11000 de zile" in c.motiv


def test_a_row_the_register_cannot_vouch_for_never_blocks():
    """The severity inversion, and the reason this module exists rather than a dict passthrough.

    `severitate: blocking` on a register row means the corpus cannot distinguish a provision still
    unrepaired from a repair it never collected. That is the weakest row in the register, and
    rendering it as the linter's `blocking` would stop a bill on an absence of data.
    """
    (c,) = coliziuni(DRAFT_EXACT, [rand(severitate="blocking", limitari=["corpus incomplet"])])
    assert c.potrivire == "exact", "the match itself is as direct as it gets"
    assert c.sustinut is False
    assert c.severitate == "material", "an unbackable row blocked a draft"
    assert "corpus incomplet" in c.limitari, "the reason it was demoted did not travel with it"


def test_one_unbacked_decision_is_enough_to_stop_it_blocking():
    """A provision struck four times is backed only if every one of those rows is."""
    (c,) = coliziuni(
        DRAFT_EXACT,
        [rand(), rand(decizie="decizie-40-1996", publicat="1996-03-01", severitate="blocking")],
    )
    assert len(c.decizii) == 2
    assert c.severitate == "material"


@pytest.mark.parametrize(
    ("locator_lovit", "asteptat", "severitate"),
    [
        ("art5.alin7", "exact", "blocking"),
        ("art5", "sub", "blocking"),
        ("art5.alin7.lita", "peste", "material"),
        ("", "tot_actul", "material"),
    ],
)
def test_reach_is_graded_and_only_the_direct_grades_block(locator_lovit, asteptat, severitate):
    """A draft citing art. 5 alin. (7) against strikes at four different depths.

    `sub` blocks because the struck text contains what the draft cites — strike art. 5 and art. 5
    alin. (7) has no legal effect either. `peste` does not, because only a part of what the draft
    cites is dead and the rest still stands. `tot_actul` does not, because 62% of the register is
    whole-act rows and they match any citation into the act: loudest finding, weakest basis.
    """
    (c,) = coliziuni(DRAFT_EXACT, [rand(locator=locator_lovit)])
    assert c.potrivire == asteptat
    assert c.severitate == severitate


def test_a_draft_that_touches_nothing_struck_says_nothing():
    assert coliziuni("Art. 1. — Se modifică art. 3 din Legea nr. 98/2016.", [rand()]) == []


def test_a_sibling_paragraph_is_not_a_collision():
    """Striking alin. (7) says nothing about alin. (8). The generous register match would let
    these two meet; here they must not."""
    draft = "Se modifică art. 5 alin. (8) din Legea nr. 59/1993."
    assert coliziuni(draft, [rand()]) == []


def test_no_register_shipped_means_no_findings_not_a_crash():
    """The data-gated behaviour every other pass has: silent, never a fabricated clean bill."""
    assert coliziuni(DRAFT_EXACT, []) == []


def test_a_provision_struck_four_times_is_one_finding_named_by_the_first():
    """`art. 224 din Codul penal` is struck by four decisions. Four identical rows against one
    line of a draft is noise; the clock runs from the earliest, so that is the one named."""
    randuri = [
        rand(decizie="decizie-40-1996", publicat="1996-03-01"),
        rand(decizie="decizie-9-1994", publicat="1994-11-25"),
        rand(decizie="decizie-71-1999", publicat="1999-06-02"),
    ]
    (c,) = coliziuni(DRAFT_EXACT, randuri)
    assert c.decizie == "decizie-9-1994", "named by a later decision than the one that started it"
    assert len(c.decizii) == 3
    assert "încă 2 decizii" in c.motiv


def test_article_150_strikes_carry_no_deadline_arithmetic():
    """A pre-1991 provision was abrogated by the Constitution itself; there was never a 45-day
    window for anyone to miss, so the finding must not invent an overdue count."""
    (c,) = coliziuni(
        DRAFT_EXACT,
        [rand(fel="abrogat_constitutional", termen=None, zile_de_la_termen=None)],
    )
    assert c.zile_de_la_termen is None
    assert "art. 150" in c.motiv
    assert "45 de zile" not in c.motiv


def test_the_worst_reach_is_reported_first():
    """A drafter reads the top of the list, so the direct hit cannot sit under a whole-act row."""
    gasite = coliziuni(
        "Se modifică art. 5 alin. (7) din Legea nr. 59/1993.",
        [rand(locator=""), rand()],
    )
    assert [c.potrivire for c in gasite] == ["exact", "tot_actul"]


def test_the_finding_quotes_the_draft_and_the_decision():
    """Every row must be checkable without leaving the screen: what the draft said, and the words
    the Court struck it with."""
    (c,) = coliziuni(DRAFT_EXACT, [rand()])
    assert "Legea nr. 59/1993" in c.text
    assert c.citat == "art. 5 alin. (7) din Legea nr. 59/1993"
    assert isinstance(c, Coliziune)


def test_the_report_shows_the_caveat_on_the_row_it_belongs_to():
    text = raport(coliziuni(DRAFT_EXACT, [rand(severitate="blocking", limitari=["corpus scurt"])]))
    assert "[material]" in text
    assert "⚠ corpus scurt" in text


def test_a_publication_date_that_is_missing_does_not_break_the_finding():
    """22% of the corpus has no publication date for ever; a strike is still a strike."""
    (c,) = coliziuni(DRAFT_EXACT, [rand(publicat=None, termen=None, zile_de_la_termen=None)])
    assert c.publicat is None
    assert c.severitate == "blocking"
    assert "decizie-9-1994" in c.motiv


def test_a_bare_act_citation_warns_without_blocking():
    """`în condițiile Legii nr. 59/1993` names no article. Something in that law is struck, which
    is worth saying and is not a verdict on the sentence."""
    (c,) = coliziuni("Contractul se încheie în condițiile Legii nr. 59/1993.", [rand()])
    assert c.potrivire == "act"
    assert c.severitate == "material"


def test_dates_survive_arriving_as_objects_rather_than_strings():
    """The register is read from JSON on the browser and could be handed straight from Python on
    the server; both must produce the same finding."""
    (c,) = coliziuni(DRAFT_EXACT, [rand(publicat=date(1994, 11, 25))])
    assert c.publicat == date(1994, 11, 25)
