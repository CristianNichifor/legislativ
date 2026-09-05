"""Tests for the amendment compiler.

The property that matters is the round trip: the composed text, read back by the extractor, must
yield the operations that went in. A test that only checked the string would not know whether the
tool had emitted something the rest of the package can actually parse.
"""

from __future__ import annotations

from scripts.compunere import Interventie, compune

L98 = "Legea nr. 98/2016 privind achizițiile publice"


def test_a_single_change_compiles_and_reads_back():
    r = compune([Interventie("modifica", L98, articol="7", alineat="2", text_nou="Text nou.")])
    assert r.titlu == "Lege pentru modificarea Legii nr. 98/2016 privind achizițiile publice"
    assert "Articolul I. - Legea nr. 98/2016 privind achizițiile publice se modifică" in r.text
    assert "1. La articolul 7, alineatul (2) se modifică și va avea următorul cuprins:" in r.text
    assert "«Text nou.»" in r.text
    assert r.curat  # every intent round-tripped through amendamente


def test_changes_are_grouped_by_act_into_numbered_articles():
    r = compune(
        [
            Interventie("modifica", L98, articol="7", text_nou="A."),
            Interventie("abroga", L98, articol="15"),
            Interventie(
                "modifica",
                "OUG nr. 57/2019 privind Codul administrativ",
                articol="3",
                text_nou="B.",
            ),
        ]
    )
    assert "Articolul I. - Legea nr. 98/2016" in r.text
    assert "Articolul II. - OUG nr. 57/2019" in r.text
    # the 98/2016 group carries both its points, numbered from 1
    assert "1. Articolul 7 se modifică" in r.text and "2. Articolul 15 se abrogă." in r.text
    assert r.curat


def test_the_chapeau_verb_reflects_the_mix_of_operations():
    doar_compl = compune(
        [Interventie("introduce", L98, articol="12", articol_nou="art. 12^1", text_nou="X.")]
    )
    assert "se completează după cum urmează" in doar_compl.text

    ambele = compune(
        [
            Interventie("modifica", L98, articol="7", text_nou="A."),
            Interventie("completeaza", L98, articol="8", text_nou="B."),
        ]
    )
    assert "se modifică și se completează după cum urmează" in ambele.text
    assert "modificarea și completarea" in ambele.titlu


def test_the_title_puts_the_act_in_the_genitive():
    r = compune([Interventie("abroga", L98, articol="15")])
    assert r.titlu.startswith("Lege pentru modificarea Legii nr. 98/2016")


def test_an_empty_list_is_a_refusal_not_a_crash():
    r = compune([])
    assert r.text == "" and not r.curat and r.verificare
