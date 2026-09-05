"""Tests for the legistic drafting-form layer.

Two things are asserted: intent said the wrong way is caught with the correct form named, and a
correctly-drafted amendment is left alone; and generation returns the phrasing the guide mandates,
article-first. The forms come from Legea nr. 24/2000 and the Consiliul Legislativ's drafting guide.
"""

from __future__ import annotations

from scripts.redactare import conformitate, redacteaza, titlu_modificator


def test_a_non_standard_repeal_is_flagged_with_the_correct_form():
    ab = conformitate("Alineatul (2) al articolului 7 se elimină.")
    assert ab and ab[0].operatie == "abroga" and "se abrogă" in ab[0].explicatie


def test_a_non_standard_modification_is_flagged():
    ab = conformitate("Articolul 7 se schimbă.")
    assert ab and ab[0].operatie == "modifica"
    assert "va avea următorul cuprins" in ab[0].explicatie


def test_a_correctly_drafted_amendment_is_left_alone():
    correct = "Articolul 15 din Legea nr. 98/2016 se abrogă."
    assert conformitate(correct) == []
    ok = (
        "La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică și va avea "
        "următorul cuprins: «text nou»."
    )
    assert conformitate(ok) == []


def test_a_modification_supplying_text_without_the_mandatory_clause_is_caught():
    """A change that gives new text must carry 'va avea următorul cuprins'."""
    ab = conformitate("Articolul 7 se modifică: «noul text al articolului».")
    assert any("cuprins" in a.gasit for a in ab)


def test_generation_matches_the_guides_article_first_form():
    out = redacteaza("modifica", "Legea nr. 98/2016", articol="7", alineat="2", text_nou="X.")
    assert out.startswith("La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică")
    assert "va avea următorul cuprins" in out
    assert conformitate(out) == []  # what we generate must pass our own check


def test_generation_of_a_repeal_and_an_insertion():
    assert redacteaza("abroga", "Legea nr. 50/1991", articol="15") == (
        "Articolul 15 din Legea nr. 50/1991 se abrogă."
    )
    ins = redacteaza(
        "introduce", "Legea nr. 98/2016", articol="12", articol_nou="art. 12^1", text_nou="Y."
    )
    assert "se introduce un nou articol, art. 12^1, cu următorul cuprins" in ins


def test_the_amending_title_names_the_touched_element():
    assert titlu_modificator("abroga", "Legea nr. 50/1991", articol="15") == (
        "Lege pentru abrogarea art. 15 din Legea nr. 50/1991"
    )
