"""Tests for the parser, against two real pages saved from the portal.

Every selector here was read off the fixtures rather than guessed, which is the whole reason
this module stopped being a stub. The fixtures are committed for that reason too: a parser
tested only against markup invented alongside it has never been tested.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.parsare import citate_din_fisier, din_fisier

SURSE = Path(__file__).resolve().parent.parent / "sources"


@pytest.fixture(scope="module")
def lege():
    return din_fisier(
        SURSE / "lege-98-2016.html.gz",
        url="https://legislatie.just.ro/Public/DetaliiDocument/178667",
    )


@pytest.fixture(scope="module")
def decizie():
    return din_fisier(
        SURSE / "decizie-815-2015.html.gz",
        url="https://legislatie.just.ro/Public/DetaliiDocument/175178",
    )


def test_the_act_is_identified_by_what_the_law_calls_itself(lege):
    assert lege.act.id == "lege-98-2016"
    assert lege.titlu.startswith("LEGE nr. 98 din 19 mai 2016")
    assert lege.emitent == "PARLAMENTUL"
    assert lege.publicat == date(2016, 5, 23)


def test_the_url_id_and_the_acts_own_id_are_different_numbers(lege):
    """This is the fact that decided the collection strategy. Requesting document 178667
    returns a page whose own `id_act` reads 290673 — so a range walk over URL ids enumerates
    handles, not acts, and neither number can be the key."""
    assert lege.id_portal == "178667"
    assert lege.id_act_portal == "290673"
    assert lege.id_portal != lege.id_act_portal
    assert lege.act.id not in (lege.id_portal, lege.id_act_portal)


def test_every_article_the_portal_marks_is_parsed(lege):
    """246 is the portal's own `S_ART` count. Checking against it rather than against a number
    written here is what makes this a guard instead of a restatement."""
    articole = [p for p in lege.provizii if "." not in p.locator_id]
    assert len(articole) == 246
    assert articole[0].locator_id == "art1"
    assert "Prezenta lege reglementează" in articole[0].text


def test_the_nesting_survives_into_locators(lege):
    ids = {p.locator_id for p in lege.provizii}
    assert "art2.alin1" in ids and "art2.alin2.lita" in ids
    alin = next(p for p in lege.provizii if p.locator_id == "art7.alin1")
    assert alin.text.startswith("(1)")


def test_the_expand_control_is_not_part_of_the_law(lege):
    """The page prefixes a heading with `+`. Left in, every article opens with punctuation the
    legislator did not write, and a verbatim quote stops being verbatim."""
    assert not any(p.text.lstrip().startswith(("+", "-")) for p in lege.provizii)


def test_a_heading_is_separated_from_the_body_it_is_welded_to(lege):
    art = next(p for p in lege.provizii if p.locator_id == "art1")
    assert "Articolul 1 - Prezenta lege" in art.text


def test_the_portals_own_reference_marks_are_kept(lege):
    """`S_LGI` is the publisher saying "there is a citation here". It does not resolve them, so
    `referinte.py` is still needed — but as ground truth for *where* references are, it is the
    only such signal in this package that nobody on this project wrote by hand."""
    cu_marcaje = [p for p in lege.provizii if p.referinte_marcate]
    assert len(cu_marcaje) > 100
    assert any("anexa" in m.lower() for p in cu_marcaje for m in p.referinte_marcate)


def test_the_hover_duplicate_is_not_counted_twice(lege):
    """`S_LIT_SHORT` is the collapsed copy the page reveals on hover. Counted, it doubles every
    letter in the act."""
    litere = [p for p in lege.provizii if ".lit" in p.locator_id]
    assert len(litere) == len({(p.locator_id, p.text) for p in litere})


def test_all_four_relation_flags_are_read(lege):
    assert lege.relatii == {"ActiuniInduse", "Actiunisuferite", "Referape", "Referitde"}


def test_an_act_with_no_article_tree_still_yields_its_text(decizie):
    """A Curtea Constituțională decision is `S_PAR` all the way down. The first version returned
    nothing for one — a document with text in it, stored as empty, which is worse than refusing
    it."""
    assert decizie.act.id == "decizie-815-2015"
    assert len(decizie.provizii) == 50
    assert all(p.locator_id.startswith("par") for p in decizie.provizii)
    assert any("neconstituțional" in p.text for p in decizie.provizii)


def test_an_amending_act_is_identified_like_any_other():
    """Legea 208/2022 is the fixture the first three lacked — an amending act, so the chapeau,
    the numbered points and the `S_CIT` replacement blocks are real rather than reconstructed."""
    act = din_fisier(SURSE / "lege-208-2022.html.gz")
    assert act.act.id == "lege-208-2022"
    assert act.titlu.startswith("LEGE nr. 208 din 11 iulie 2022")


def test_the_replacement_blocks_of_an_amending_act_are_read_off_the_markup():
    """`citate` reads the `S_CIT` payload the portal wraps each replacement in — the marked-up
    form of what a human draft puts in guillemets, and the payload consolidation splices."""
    blocuri = citate_din_fisier(SURSE / "lege-208-2022.html.gz")
    assert len(blocuri) == 46
    assert all(b.locator_id.startswith("cit") for b in blocuri)
    # every block is non-empty text, and the outermost-only rule kept them distinct payloads,
    # not one article's alineate counted again as their own blocks.
    assert all(b.text for b in blocuri)
    assert any("Autoritatea contractantă" in b.text for b in blocuri)


def test_legacy_cedilla_spellings_are_folded_on_the_way_in(decizie):
    """The real pages are typed with ş and ţ. Unfolded, every pattern in this package misses
    them silently."""
    tot = " ".join(p.text for p in decizie.provizii)
    assert "ţ" not in tot and "ş" not in tot
    assert "ț" in tot or "ș" in tot
