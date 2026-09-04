"""Tests for the obligation extractor.

The anchor test is here because `de la publicare` and `de la intrarea în vigoare` differ by the
act's vacatio legis, and an overdue figure computed from the wrong one is a number that looks
checkable and is not.
"""

from __future__ import annotations

from datetime import date

from scripts.termene import obligatii


def test_the_canonical_delegation_sentence():
    o = obligatii(
        "În termen de 30 de zile de la data intrării în vigoare a prezentei legi, "
        "Guvernul aprobă normele metodologice de aplicare."
    )[0]
    assert (o.instrument, o.tip_asteptat, o.termen_zile, o.ancora, o.institutie) == (
        "norme-metodologice",
        "hg",
        30,
        "vigoare",
        "guvern",
    )


def test_the_anchor_is_recorded_rather_than_collapsed_to_one_date():
    publicare = obligatii(
        "În termen de 6 luni de la data publicării în Monitorul Oficial, "
        "ministrul sănătății emite ordinul de aplicare."
    )[0]
    assert (publicare.ancora, publicare.termen_zile) == ("publicare", 180)
    assert publicare.scadenta(vigoare=date(2024, 1, 1), publicare=date(2023, 12, 20)) == (
        date(2024, 6, 17)
    )


def test_a_numeral_written_out_is_still_a_deadline():
    """`în termen de un an` contains no digit at all."""
    assert (
        obligatii(
            "În termen de un an de la intrarea în vigoare, consiliile locale adoptă "
            "procedura de punere în aplicare."
        )[0].termen_zile
        == 365
    )


def test_an_absolute_deadline_needs_no_anchor():
    o = obligatii(
        "Până la data de 31 decembrie 2026, Autoritatea Națională de Reglementare "
        "adoptă regulamentul de aplicare."
    )[0]
    assert o.ancora == "data-fixa" and o.scadenta() == date(2026, 12, 31)


def test_an_order_that_is_cited_is_not_an_order_that_is_required():
    """Without the lookahead on `nr.`, every sentence mentioning an existing order acquires a
    deadline and the gap report fills with instruments nobody was asked to issue."""
    assert (
        obligatii(
            "Prezenta lege se aplică în condițiile Ordinului ministrului finanțelor "
            "publice nr. 1.802/2014."
        )
        == []
    )


def test_a_deadline_with_no_recognised_instrument_is_still_returned():
    """An unrecognised instrument is this module's gap, not the law's. Dropping the sentence
    would hide the miss behind a smaller-looking result."""
    o = obligatii(
        "În termen de 15 zile de la primirea cererii, autoritatea contractantă "
        "răspunde solicitantului."
    )[0]
    assert o.instrument is None and o.termen_zile == 15


def test_the_due_date_is_none_when_the_host_act_has_no_dates():
    """An overdue count computed from an assumed entry into force survives one meeting."""
    o = obligatii(
        "În termen de 30 de zile de la intrarea în vigoare, Guvernul aprobă normele metodologice."
    )[0]
    assert o.scadenta() is None
    assert o.scadenta(vigoare=date(2016, 5, 26)) == date(2016, 6, 25)
