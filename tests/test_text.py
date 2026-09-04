"""Tests for the normaliser.

The cedilla fold is guarded in both directions because getting it wrong does not raise: the
extractors simply return nothing, and nothing reads as "this act amends nothing".
"""

from __future__ import annotations

from scripts.text import cheie, fara_diacritice, normalizeaza


def test_cedilla_letters_fold_to_the_comma_below_ones():
    """ş U+015F and ţ U+0163 are different characters from ș U+0219 and ț U+021B. A pattern
    written with one matches none of the other, and half the portal is typed in the legacy form."""
    assert normalizeaza("se modifică şi va avea următorul cuprins") == (
        "se modifică și va avea următorul cuprins"
    )
    assert "ţ" not in normalizeaza("hotărârea Guvernului privind funcţionarea")


def test_superscript_article_numbers_become_the_caret_form():
    """`12¹` is the article inserted between 12 and 13. Read as 121 it points at nothing."""
    assert normalizeaza("art. 12¹") == "art. 12^1"
    assert normalizeaza("art. 12 ind. 1") == "art. 12^1"


def test_normalising_twice_changes_nothing():
    """Text is normalised on the way in and again at match time; drift between the two would
    make stored text stop matching freshly-read text."""
    o_data = normalizeaza("La articolul 12¹, alineatul (2) se modifică şi  va  avea")
    assert normalizeaza(o_data) == o_data


def test_diacritics_are_stripped_only_for_comparison():
    assert fara_diacritice("hotărâre") == "hotarare"
    assert cheie("  Hotărârea   GUVERNULUI ") == "hotararea guvernului"


def test_folding_does_not_erase_the_difference_between_locator_forms():
    """`alin. (2)` and `alin 2` differ by punctuation the parser depends on, so the comparison
    key keeps it rather than tolerating what would really be a parse error."""
    assert cheie("alin. (2)") != cheie("alin 2")
