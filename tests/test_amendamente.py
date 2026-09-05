"""Tests for the amendment layer.

The chapeau test is the one that matters most: without inheritance every amendment in a real
Romanian amending act comes out with no target, which is not poor recall but an empty graph.
"""

from __future__ import annotations

from scripts.amendamente import amendamente, unitati
from scripts.referinte import Act

GAZDA = Act("lege", "200", 2026)
TINTA = Act("lege", "98", 2016)

CHAPEAU = (
    "Legea nr. 98/2016 privind achizițiile publice, cu modificările și completările "
    "ulterioare, se modifică și se completează după cum urmează:\n"
)


def test_numbered_points_inherit_the_target_named_only_in_the_chapeau():
    """Point 2 abrogates article 15 of Legea 98/2016 and says so nowhere."""
    gasite = amendamente(
        CHAPEAU + "1. La articolul 7, alineatul (2) se modifică.\n2. Articolul 15 se abrogă.",
        act_gazda=GAZDA,
    )
    assert [(a.fel, a.act_tinta.id, a.locator.id) for a in gasite] == [
        ("modifica", "lege-98-2016", "art7.alin2"),
        ("abroga", "lege-98-2016", "art15"),
    ]


def test_an_inherited_target_says_it_was_inherited():
    """A target read from the sentence and one carried down from a chapeau are not equally
    certain, and the repository's rule is that a derived value declares itself."""
    mostenit = amendamente(CHAPEAU + "1. Articolul 15 se abrogă.", act_gazda=GAZDA)[0]
    assert mostenit.mostenit and mostenit.increderea == "derived"

    explicit = amendamente("Se abrogă Legea nr. 50/1991.", act_gazda=GAZDA)[0]
    assert not explicit.mostenit and explicit.increderea == "verbatim"


def test_abrogation_points_inward_or_outward_depending_on_where_the_target_sits():
    """`Articolul 15 se abrogă` repeals part of the host act; `se abrogă Legea nr. 50/1991`
    repeals a different act entirely. Swapped, the most consequential edge in the graph
    reverses direction."""
    intern = amendamente("Articolul 15 se abrogă.", act_gazda=GAZDA)[0]
    assert intern.act_tinta == GAZDA and intern.locator.id == "art15"

    extern = amendamente(
        "La data intrării în vigoare a prezentei legi se abrogă Legea nr. 50/1991 privind "
        "autorizarea executării lucrărilor de construcții.",
        act_gazda=GAZDA,
    )[0]
    assert extern.act_tinta.id == "lege-50-1991" and not extern.locator


def test_a_derogation_keeps_the_article_it_derogates_from():
    """The target follows the verb here as it does in an outward abrogation, but it carries a
    locator — and dropping it turns a derogation from one article into one from a whole law."""
    a = amendamente(
        "Prin derogare de la prevederile art. 5 din Legea nr. 98/2016, contractele se atribuie "
        "direct.",
        act_gazda=GAZDA,
    )[0]
    assert (a.fel, a.act_tinta.id, a.locator.id) == ("deroga", "lege-98-2016", "art5")


def test_an_inserted_article_is_kept_apart_from_the_article_it_follows():
    """`După articolul 12 se introduce ... art. 12^1` — the anchor is 12, the new provision is
    12^1, and reporting against the wrong one points a warning at the wrong text."""
    a = amendamente(
        CHAPEAU + "1. După articolul 12 se introduce un nou articol, art. 12^1, cu "
        "următorul cuprins:",
        act_gazda=GAZDA,
    )[0]
    assert a.fel == "introduce" and a.locator.id == "art12"
    assert a.locator_nou.id == "art12^1" and a.articole_noi == ("12^1",)


def test_a_negated_verb_is_not_an_amendment():
    """`nu se abrogă` read as an abrogation inverts the edge."""
    assert (
        amendamente(
            "Prezenta lege nu se abrogă prin intrarea în vigoare a altor acte normative.",
            act_gazda=GAZDA,
        )
        == []
    )


def test_a_global_phrase_substitution_is_recorded():
    """It rewrites dozens of articles while naming none, so it has to survive as an edge even
    though it has no locator. The singular `se înlocuiește` is the form that is actually used."""
    a = amendamente(
        "În cuprinsul legii, sintagma «autoritate publică» se înlocuiește cu sintagma "
        "«autoritate contractantă».",
        act_gazda=GAZDA,
    )[0]
    assert a.fel == "inlocuieste" and a.act_tinta == GAZDA


def test_the_chapeau_sentence_is_not_itself_an_amendment():
    """It announces the amendments; counting it as one doubles every amending act's first edge."""
    assert len(amendamente(CHAPEAU + "1. Articolul 15 se abrogă.", act_gazda=GAZDA)) == 1


def test_a_numbered_point_stays_whole():
    """A point contains the quoted new text of the provision, often several sentences. Split
    inside it, the verb lands in one unit and the target in another."""
    bucati = unitati(
        CHAPEAU + "1. La articolul 7, alineatul (2) se modifică și va avea "
        "următorul cuprins:\nAutoritatea publică decide. Termenul este de 30 de "
        "zile.\n2. Articolul 15 se abrogă."
    )
    puncte = [b for b, _ in bucati if b.lstrip().startswith(("1.", "2."))]
    assert len(puncte) == 2
    assert "Termenul este de 30 de zile" in puncte[0]


def test_abbreviations_that_end_in_a_full_stop_do_not_end_a_sentence():
    """`art.`, `alin.`, `nr.` all end in the character a naive splitter treats as a boundary."""
    bucati = unitati("Se aplică art. 5 din Legea nr. 98/2016. Articolul 15 se abrogă.")
    assert len(bucati) == 2


def test_a_modification_captures_the_quoted_replacement_text():
    """The payload consolidation needs: `va avea următorul cuprins: «...»`, verbatim."""
    a = amendamente(
        CHAPEAU + "1. La articolul 7, alineatul (2) se modifică și va avea următorul "
        "cuprins:\n«(2) Autoritatea contractantă publică anunțul de participare.»",
        act_gazda=GAZDA,
    )[0]
    assert a.fel == "modifica"
    assert a.continut_nou == "(2) Autoritatea contractantă publică anunțul de participare."
    assert a.increderea == "derived"  # target was inherited from the chapeau


def test_an_insertion_captures_its_new_text_in_low9_high6_quotes():
    """`se introduce ... cu următorul cuprins: „..."` — the other quote style, and an insert."""
    a = amendamente(
        CHAPEAU + "1. După articolul 12 se introduce un nou articol, art. 12^1, cu "
        'următorul cuprins:\n„Art. 12^1. - Prezenta procedură se aplică integral."',
        act_gazda=GAZDA,
    )[0]
    assert a.fel == "introduce"
    assert a.continut_nou == "Art. 12^1. - Prezenta procedură se aplică integral."


def test_a_multiline_payload_is_captured_whole():
    a = amendamente(
        CHAPEAU + "1. Articolul 7 se modifică și va avea următorul cuprins:\n"
        "«Art. 7. -\n(1) Prima regulă.\n(2) A doua regulă.»",
        act_gazda=GAZDA,
    )[0]
    assert a.continut_nou == "Art. 7. -\n(1) Prima regulă.\n(2) A doua regulă."


def test_an_abrogation_carries_no_payload():
    """Nothing to substitute; consolidation marks the provision repealed, it splices no text."""
    a = amendamente(CHAPEAU + "1. Articolul 15 se abrogă.", act_gazda=GAZDA)[0]
    assert a.fel == "abroga" and a.continut_nou is None


def test_a_modification_without_a_quoted_block_yields_no_payload():
    """A change that does not quote its new text leaves continut_nou None, so consolidation sees an
    operation it cannot apply and refuses rather than inventing text."""
    a = amendamente(CHAPEAU + "1. La articolul 7, alineatul (2) se modifică.", act_gazda=GAZDA)[0]
    assert a.fel == "modifica" and a.continut_nou is None
