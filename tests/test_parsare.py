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


def test_a_first_publication_page_has_no_republication_date(lege):
    """The committed fixture is a first publication, not a republication — the field stays empty
    rather than being filled from the ordinary publication line."""
    assert lege.republicat_din is None


def test_a_republished_header_fills_the_republication_date():
    """When the header says the act is republished, the date on its publication line is the
    republication in Monitorul Oficial — read into `republicat_din` so consolidation can refuse to
    apply pre-republication amendments to the renumbered tree."""
    from scripts.parsare import parseaza

    html = (
        '<span class="S_DEN">LEGE nr. 99 din 1 martie 2021</span>'
        '<span class="S_PUB_BDY">Republicat în MONITORUL OFICIAL nr. 500 din 15 aprilie 2021</span>'
    )
    a = parseaza(html)
    assert a.republicat_din == date(2021, 4, 15)


def test_the_word_alone_without_a_date_does_not_invent_a_republication():
    from scripts.parsare import parseaza

    html = (
        '<span class="S_DEN">LEGE nr. 99 din 1 martie 2021</span>'
        '<span class="S_PUB_BDY">Text republicat, fără nicio dată de publicare.</span>'
    )
    a = parseaza(html)
    assert a.republicat_din is None  # no date to pin it to → no claim


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


PAGINA_REZERVA = """<html><body>
<div class="S_DEN">ACORD din 2003 de garanție</div>
<span class="S_PAR">Părțile au convenit următoarele.</span>
<span class="S_LIT_BDY">a) Garantul se va asigura că nicio acțiune nu împiedică
executarea prezentului acord.</span>
<span class="S_LIT_BDY">b) Garantul va asista Împrumutatul în aprobarea documentelor.</span>
<span class="S_PAR">Prezentul acord intră în vigoare la semnare.</span>
<span class="S_LIT_BDY">---</span>
</body></html>"""


def test_the_reserve_keeps_body_blocks_not_only_paragraphs():
    """Where an act's wrappers do not close the way the structured walk needs, its letters still
    carry their text in `S_LIT_BDY` — and taking paragraphs alone dropped every one of them.
    Measured over 462 previously-refused acts, the median recovery of the archived body was 0.90;
    with the body blocks kept it is 1.08, and 314 of them stop losing a tenth of their text."""
    from scripts.parsare import parseaza

    a = parseaza(PAGINA_REZERVA, "u")
    tot = " ".join(p.text for p in a.provizii)
    assert "Garantul se va asigura" in tot, "corpul literei a) a fost pierdut"
    assert "Garantul va asista" in tot, "corpul literei b) a fost pierdut"
    assert "Părțile au convenit" in tot and "intră în vigoare" in tot


def test_the_reserve_skips_blocks_with_no_letters():
    """Reading the body blocks brought the page's separators with them: a decision came out with a
    fifty-first provision reading `---`. A block with no letter is not text a finding can quote,
    and giving it a locator invites a citation to a horizontal rule."""
    from scripts.parsare import parseaza

    a = parseaza(PAGINA_REZERVA, "u")
    assert all(any(c.isalpha() for c in p.text) for p in a.provizii)
    assert not any(p.text.strip() == "---" for p in a.provizii)


# --- puncte ------------------------------------------------------------------------------------

PAGINA_PUNCTE = """<html><body>
<div class="S_DEN">LEGE nr. 273 din 2006 privind finanțele publice locale</div>
<span class="S_ART" id="a2"><span class="S_ART_TTL">Articolul 2</span>
<span class="S_ART_BDY"><span class="S_ALN"><span class="S_ALN_TTL">(1)</span>
<span class="S_ALN_BDY">În înțelesul prezentei legi, termenii se definesc astfel:
<span class="S_PCT"><span class="S_PCT_TTL">1.</span>
<span class="S_PCT_BDY">activitate — totalitatea acțiunilor efectuate.</span>
<span style="display:none" class="S_PCT_SHORT"> ... </span></span>
<span class="S_PCT"><span class="S_PCT_TTL">39.</span>
<span class="S_PCT_BDY">excedent bugetar — partea veniturilor ce depășește cheltuielile.</span>
<span style="display:none" class="S_PCT_SHORT"> ... </span></span>
</span></span></span></span>
<span class="S_ART" id="a3"><span class="S_ART_TTL">Articolul 3</span>
<span class="S_ART_BDY"><span class="S_ALN"><span class="S_ALN_TTL">(4)</span>
<span class="S_ALN_BDY"><span class="S_LIT"><span class="S_LIT_TTL">b)</span>
<span class="S_LIT_BDY">instrumente de garantare, astfel:
<span class="S_PCT"><span class="S_PCT_TTL">(i)</span>
<span class="S_PCT_BDY">scrisori de garanție emise de instituții de credit;</span></span>
<span class="S_PCT"><span class="S_PCT_TTL">(ii)</span>
<span class="S_PCT_BDY">asigurări de garanții emise de societăți de asigurare;</span></span>
</span></span></span></span></span></span>
</body></html>"""


def _puncte():
    from scripts.parsare import parseaza

    return parseaza(PAGINA_PUNCTE, "u")


def test_a_point_is_addressable_at_the_locator_citations_use():
    """15 550 citations in the collected graph name a point — `art. 2 alin. (1) pct. 39` — and the
    corpus held not one provision at such a locator, so every one of them resolved to nothing."""
    pe_loc = {p.locator_id: p.text for p in _puncte().provizii}
    assert "art2.alin1.pct39" in pe_loc
    assert "excedent bugetar" in pe_loc["art2.alin1.pct39"]
    assert "art2.alin1.pct1" in pe_loc


def test_the_hover_duplicate_of_a_point_is_not_counted_twice():
    """The portal writes a collapsed `_SHORT` twin of every addressable unit. Only the letter's was
    being dropped, so reading points without dropping theirs doubles every point in the act."""
    provizii = _puncte().provizii
    assert "..." not in " ".join(p.text for p in provizii)
    puncte = [p.locator_id for p in provizii if p.locator_id.startswith("art2.alin1.pct")]
    assert sorted(puncte) == ["art2.alin1.pct1", "art2.alin1.pct39"]


def test_a_sub_point_under_a_letter_keeps_the_letter_in_its_locator():
    """The portal marks the roman sub-letter level `S_PCT` as well. Nothing in the corpus cites one
    — all 15 550 point references are arabic — but they carry text, so they are numbered rather
    than dropped, and the letter above them stays in the address."""
    locs = {p.locator_id for p in _puncte().provizii}
    assert "art3.alin4.litb.pcti" in locs
    assert "art3.alin4.litb.pctii" in locs


def test_a_point_whose_number_cannot_be_read_is_not_emitted_at_its_parents_locator():
    """This is what went wrong the first time points were tried. With no number the point built the
    same locator as the unit containing it and appended a second row under it — Legea 98/2016 went
    from 1 435 provisions to 1 455 with not one new locator among them. Every reader that maps
    locator to text keeps the last row it sees, so `art187.alin8.lita` came back holding a
    sub-point, and the consolidation pairing landed 0 of 8 blocks."""
    from scripts.parsare import parseaza

    a = parseaza(
        """<html><body><div class="S_DEN">LEGE nr. 1 din 2020</div>
        <span class="S_ART"><span class="S_ART_TTL">Articolul 5</span>
        <span class="S_ART_BDY"><span class="S_LIT"><span class="S_LIT_TTL">a)</span>
        <span class="S_LIT_BDY">textul literei a).
        <span class="S_PCT"><span class="S_PCT_TTL">&#8212;</span>
        <span class="S_PCT_BDY">o liniuță fără număr.</span></span>
        </span></span></span></span></body></html>""",
        "u",
    )
    locs = [p.locator_id for p in a.provizii]
    assert len(locs) == len(set(locs)), f"locatori duplicați: {locs}"
    assert "art5.lita" in locs


def test_the_amending_text_is_read_once_and_not_once_per_level():
    """Provisions are stored at every depth on purpose, so joining all of them repeats every
    sentence. `amendamente` carries the chapeau forward from one instruction to the next, so a
    repeat re-enters it with a stale `La articolul 187,` — Legea 208/2022 went from 49 amendments
    to 1 the moment points made the repetition visible."""
    from scripts.consolidare import text_o_singura_data

    a = _puncte()
    plat = text_o_singura_data(a.provizii)
    assert plat.count("excedent bugetar") == 1
    assert plat.count("scrisori de garanție") == 1
    assert "activitate" in plat and "asigurări de garanții" in plat
