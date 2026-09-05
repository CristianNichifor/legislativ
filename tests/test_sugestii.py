"""Tests for the drafting suggestion — the deterministic 'as you type' layer.

Two things matter: it recognises the operation from both the correct legistic verb and the
non-standard forms a person reaches for, and it stays silent on a line it does not understand,
because a wrong suggestion in a place a writer trusts is worse than none.
"""

from __future__ import annotations

from scripts.sugestii import sugereaza


def test_a_standard_modification_is_recognised_with_its_target_and_formula():
    s = sugereaza("La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică")
    assert s is not None
    assert s.fel == "modifica" and s.act_id == "lege-98-2016" and s.locator_id == "art7.alin2"
    assert not s.nestandard
    assert "se modifică și va avea următorul cuprins" in s.formula
    assert "alineatul (2)" in s.simplu and "articolului 7" in s.simplu


def test_a_non_standard_verb_is_caught_and_flagged_for_correction():
    """`se elimină` is how a person writes a repeal; the Council requires `se abrogă`. The
    suggestion recognises the intent, marks it non-standard, and offers the correct form."""
    s = sugereaza("Articolul 15 din OUG 57/2019 se elimină")
    assert s is not None
    assert s.fel == "abroga" and s.nestandard
    assert s.act_id == "oug-57-2019" and s.locator_id == "art15"
    assert "se abrogă" in s.formula


def test_an_abrogation_reads_as_removal_in_plain_language():
    s = sugereaza("Articolul 15 din Legea nr. 98/2016 se abrogă")
    assert s is not None and s.fel == "abroga"
    assert "Elimini" in s.simplu and "nu se mai aplică" in s.simplu


def test_a_line_with_no_operation_yields_nothing():
    assert sugereaza("Prezenta lege reglementează achizițiile publice de stat.") is None


def test_a_negated_verb_is_not_taken_as_an_operation():
    assert sugereaza("Prezenta lege nu se abrogă prin alte acte normative.") is None


def test_an_operation_with_no_target_yields_nothing():
    """Nothing to point the amendment at — no act and no locator — so no formula worth offering."""
    assert sugereaza("acest lucru se modifică") is None


def test_a_recognised_but_unredactable_verb_is_not_offered():
    """`se prorogă` is a real operation the extractors know, but there is no single paste-ready
    Legea 24/2000 form for it here, so a half-suggestion is withheld rather than faked."""
    assert sugereaza("Termenul din articolul 5 din Legea nr. 98/2016 se prorogă") is None


def test_the_act_citation_is_reconstructed_for_each_type():
    assert "Legea nr. 98/2016" in sugereaza("Articolul 7 din Legea 98/2016 se abrogă").formula
    oug = sugereaza("Articolul 7 din OUG 57/2019 se abrogă")
    assert "Ordonanța de urgență a Guvernului nr. 57/2019" in oug.formula
