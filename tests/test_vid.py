"""Tests for the gap report.

The completeness test is the one that keeps this output usable in public: a missing hotărâre in
a corpus that never collected hotărâri is not a legislative gap, and reporting it as one is how
a research team stops trusting the tool.
"""

from __future__ import annotations

from datetime import date

from scripts.referinte import Act, Locator
from scripts.termene import obligatii
from scripts.vid import ActCunoscut, Corpus, vid_legislativ

LEGE = Act("lege", "98", 2016)
NORME = (
    "În termen de 30 de zile de la data intrării în vigoare, Guvernul aprobă normele "
    "metodologice de aplicare."
)


def _corpus(*, cu_norme: bool, complet: frozenset[str] = frozenset({"hg"})) -> Corpus:
    acte = {
        "lege-98-2016": ActCunoscut(LEGE, "achiziții publice", date(2016, 5, 23), date(2016, 5, 26))
    }
    if cu_norme:
        acte["hg-395-2016"] = ActCunoscut(
            Act("hg", "395", 2016),
            "norme",
            date(2016, 6, 2),
            date(2016, 6, 2),
            frozenset({"lege-98-2016"}),
        )
    return Corpus(acte=acte, complet_pentru=complet)


def _obligatii():
    return obligatii(NORME, act=LEGE, locator=Locator(articol="236"))


def test_an_obligation_the_corpus_can_show_was_met_is_not_reported():
    assert vid_legislativ(_obligatii(), _corpus(cu_norme=True), date(2026, 9, 4)) == []


def test_an_obligation_with_nothing_to_discharge_it_is_reported_with_the_days_counted():
    v = vid_legislativ(_obligatii(), _corpus(cu_norme=False), date(2026, 9, 4))[0]
    assert v.scadenta == date(2016, 6, 25)
    assert v.zile_intarziere == (date(2026, 9, 4) - date(2016, 6, 25)).days
    assert v.severitate == "material"


def test_absence_is_blocking_when_the_corpus_does_not_claim_to_have_collected_the_instrument():
    """The finding is still emitted — silence would be worse — but it says on its face that it
    cannot tell a gap in the law from a gap in the scrape."""
    corpus = _corpus(cu_norme=False, complet=frozenset())
    v = vid_legislativ(_obligatii(), corpus, date(2026, 9, 4))[0]
    assert v.severitate == "blocking"
    assert any("colect" in lim for lim in v.limitari)


def test_a_near_miss_is_returned_with_the_finding_rather_than_filtered_out():
    """An implementing act of the wrong type is a different political fact from nothing at all,
    and it is the first thing a researcher will be asked about."""
    ordin = obligatii(
        "În termen de 60 de zile de la intrarea în vigoare, ministrul finanțelor emite ordinul "
        "de aplicare.",
        act=LEGE,
        locator=Locator(articol="237"),
    )
    v = vid_legislativ(ordin, _corpus(cu_norme=True), date(2026, 9, 4))[0]
    assert v.candidati == ("hg-395-2016",)


def test_overdue_is_none_rather_than_guessed_when_the_host_act_is_not_in_the_corpus():
    v = vid_legislativ(_obligatii(), Corpus(complet_pentru=frozenset({"hg"})), date(2026, 9, 4))[0]
    assert v.zile_intarziere is None and v.scadenta is None
    assert any("intrare în vigoare" in lim for lim in v.limitari)


def test_the_absence_is_always_derived_even_though_the_obligation_is_quoted():
    v = vid_legislativ(_obligatii(), _corpus(cu_norme=False), date(2026, 9, 4))[0]
    assert v.increderea == "derived"
