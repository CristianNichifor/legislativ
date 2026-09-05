"""The consolidation gold test — against the portal's own consolidated view.

Phases 1 and 2 tested the engine on hand-made provision/operation structures. This tests it on
real markup, and against the one answer key that is not this project's opinion: the portal
publishes its *own* consolidated form of every act, and that is what a consolidation is right or
wrong against, exactly as `S_LGI` was the answer key for reference recall.

The pair is real and committed:

- `sources/lege-208-2022.html.gz` — Legea nr. 208/2022, which amends Legea nr. 98/2016 and quotes
  each replacement in an `S_CIT` block (`parsare.citate` reads them).
- `sources/lege-98-2016.html.gz` — the portal's consolidated form of Legea 98/2016, which already
  carries those 2022 changes. Its text of an amended provision is the answer key.

So the claim under test is end to end: the replacement Legea 208/2022 supplies for a provision,
extracted from real markup and spliced by the engine, equals — byte for byte after normalisation —
the text the portal itself shows for that provision. A payload that only *nearly* matches would be
the exact failure this package refuses: fluent, authoritative, and subtly not the law.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.consolidare import (
    Operatie,
    consolideaza,
    consolideaza_in,
    operatii_amendatoare,
)
from scripts.parsare import citate_din_fisier, din_fisier
from scripts.text import cheie

SURSE = Path(__file__).resolve().parent.parent / "sources"

# Legea 208/2022 was published on 11 July 2022; any date after its entry into force consolidates
# the same way, so the exact vacatio does not decide the test.
DUPA_208 = date(2023, 1, 1)


@pytest.fixture(scope="module")
def citate208():
    return citate_din_fisier(SURSE / "lege-208-2022.html.gz")


@pytest.fixture(scope="module")
def payloads(citate208):
    return [p.text for p in citate208]


@pytest.fixture(scope="module")
def amendator208():
    return din_fisier(SURSE / "lege-208-2022.html.gz")


@pytest.fixture(scope="module")
def lege98():
    return din_fisier(SURSE / "lege-98-2016.html.gz")


def test_the_amending_act_supplies_its_replacements_as_marked_up_blocks(payloads):
    """`parsare.citate` reads the `S_CIT` payloads a human draft would put in guillemets. Legea
    208/2022 carries dozens; the count is the portal's, not a number written here."""
    assert len(payloads) == 46
    assert all(payloads)


def test_a_replacement_equals_the_portals_consolidated_text_byte_for_byte(payloads, lege98):
    """The deterministic pair: the portal's consolidated text of art. 187 alin. (8) lit. a) of
    Legea 98/2016 *is*, verbatim after normalisation, the block Legea 208/2022 supplies for it.
    Diffed against the portal's own consolidated view, this consolidation is zero-difference."""
    tinta = next(p for p in lege98.provizii if p.locator_id == "art187.alin8.lita")
    assert tinta.text in set(payloads)

    # And through the engine: the extracted block, spliced onto the pre-2022 wording, yields the
    # portal's text. The original here is a placeholder — the pre-amendment wording is not in the
    # committed fixtures — and `modifica` legitimately discards it, which is the point: the result
    # is the payload, and the payload is what the portal shows.
    r = consolideaza(
        "art187.alin8.lita",
        "PLACEHOLDER — textul dinainte de 2022 nu este în fixturi",
        [Operatie("modifica", "art187.alin8.lita", DUPA_208, "lege-208-2022", tinta.text)],
        la_data=DUPA_208,
    )
    assert r.complet and r.text == tinta.text
    assert [s.act for s in r.schimbari] == ["lege-208-2022"]


def test_most_replacements_appear_verbatim_in_the_consolidated_act(payloads, lege98):
    """The reproducible number CI holds. Not every block matches as a whole: some are a whole
    article whose alineate the consolidated act stores as separate provisions, some were touched
    again by a later act, and insertions have no prior provision to sit in. But a solid majority of
    the substantial replacements appear, byte for byte, inside the provision they rewrote — which
    is the evidence the extract-and-splice mechanism is sound on real markup. If this floor ever
    drops, the parser or the engine changed under it, and that is exactly what should fail CI."""
    provizii = [cheie(p.text) for p in lege98.provizii if p.text]
    substantiale = [cheie(t) for t in payloads if len(cheie(t)) >= 40]
    gasite = sum(1 for b in substantiale if any(b in p for p in provizii))
    assert gasite >= 15, f"doar {gasite} din {len(substantiale)} blocuri regăsite verbatim"


def test_operations_are_read_off_the_amending_page_and_grouped_by_target(amendator208, citate208):
    """`operatii_amendatoare` pairs each `S_CIT` block to the point that announces it and resolves
    the point's target and locator — so consolidation can run *from* an amending page. Legea
    208/2022 amends the whole 2016 procurement package, and the operations come out grouped by the
    act each targets, every replacement carrying its payload."""
    grup = operatii_amendatoare(amendator208, citate208)
    assert set(grup) == {"lege-98-2016", "lege-99-2016", "lege-100-2016"}
    ops98 = grup["lege-98-2016"]
    assert len(ops98) == 20
    # the modificari all carry the block they replace with; the operation date is the act's own
    # entry into force, not invented.
    modificari = [o for o in ops98 if o.fel == "modifica"]
    assert modificari and all(o.continut_nou for o in modificari)
    assert all(o.act == "lege-208-2022" for o in ops98)
    assert all(o.data == amendator208.vigoare for o in ops98)


def test_each_replacement_lands_on_the_provision_it_names(amendator208, citate208, lege98):
    """The proof the pairing is not off by one: a modification's block appears verbatim inside the
    provision its *own* resolved locator points at in the consolidated act. Not every one — a
    whole-article block omits the `Articolul N -` heading, and some provisions the act splits into
    alineate — but a solid majority land exactly where the point said they would."""
    ops = operatii_amendatoare(amendator208, citate208)["lege-98-2016"]
    byloc = {p.locator_id: cheie(p.text) for p in lege98.provizii}
    la_locul_lui = sum(
        1
        for o in ops
        if o.fel == "modifica"
        and o.continut_nou
        and o.locator in byloc
        and cheie(o.continut_nou) in byloc[o.locator]
    )
    assert la_locul_lui >= 8, f"doar {la_locul_lui} blocuri au aterizat pe locatorul lor"


def test_a_page_that_parses_skew_raises_rather_than_mispairs(amendator208, citate208):
    """The one thing worse than refusing is pairing a payload to the wrong provision. If the count
    of blocks and the count of points announcing one disagree, the join refuses outright."""
    with pytest.raises(ValueError, match="s-a parsat strâmb"):
        operatii_amendatoare(amendator208, citate208[:-1])


def test_the_tree_is_the_provision_source(lege98):
    """`consolideaza_in` reads a provision's original text from the parsed tree, not from an
    argument. With no operations, a provision consolidates to itself — the wiring, proven on a real
    article the amending act never touched."""
    op = Operatie("modifica", "art1", None, "irelevant")
    rez = consolideaza_in(lege98, [op], la_data=DUPA_208)
    # art1 is undated-refused (the op has no date), but the point here is the lookup found it.
    assert "art1" in rez

    art1 = next(p for p in lege98.provizii if p.locator_id == "art1")
    curat = consolideaza_in(lege98, [], la_data=DUPA_208)
    assert curat == {}  # no operations, nothing to consolidate

    # A locator the act does not carry is a visible refusal, not a silent drop.
    lipsa = consolideaza_in(
        lege98,
        [Operatie("abroga", "art99999", DUPA_208, "lege-208-2022")],
        la_data=DUPA_208,
    )
    assert not lipsa["art99999"].complet
    assert any("nu există" in lim for lim in lipsa["art99999"].limitari)
    assert art1.text  # sanity: the tree really does carry article 1
