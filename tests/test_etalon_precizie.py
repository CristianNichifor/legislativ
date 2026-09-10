"""A precision harness that cannot quietly report success it has not earned.

The whole risk in this file is one number: precision computed over an empty set is 1.0 in
every naive implementation, and 1.0 is exactly what someone skimming a release note wants to
see. So the arithmetic returns None rather than 1.0, and the tests below check the plumbing
that keeps the question honest — the sheet describes today's extractor, the verdicts describe
today's sheet, and nothing answers a question that was not asked.

The floor itself is marked xfail(strict=True): precision is genuinely not measured yet, so a
passing test would be a lie, and a failing build on every unrelated change teaches people to
ignore the build. Strict is the point — the day verdicts arrive and the assertions hold, this
test starts passing, strict turns that into a failure, and someone has to come here and delete
the marker. It cannot drift into a green tick nobody looked at.
"""

from __future__ import annotations

import pytest

from scripts.etalon_precizie import (
    ESANTION,
    Scor,
    amprenta,
    candidati,
    citeste_fisa,
    citeste_verdicte,
    esantion,
    scor,
)

PRAG_PRECIZIE = 0.95
MINIM_JUDECATE = 100


def test_the_sheet_describes_the_extractor_as_it_is_now():
    """The one check that makes the rest mean anything.

    If `referinte.py` changes what it claims, the fingerprint moves and this fails, so the
    sheet has to be regenerated and the new candidates read. Without it, verdicts would go on
    describing an extractor that no longer exists and precision would be a number about the
    past, reported in the present tense.
    """
    assert citeste_fisa()["amprenta"] == amprenta(candidati()), (
        "fișa nu mai descrie extractorul de azi; rulează "
        "`python -m scripts.etalon_precizie --scrie` și recitește candidații noi"
    )


def test_the_verdicts_answer_this_sheet_and_not_an_older_one():
    assert citeste_verdicte()["amprenta"] == citeste_fisa()["amprenta"]


def test_no_verdict_answers_a_question_that_was_not_asked():
    chei = {e["cheie"] for e in citeste_fisa()["elemente"]}
    straine = set(citeste_verdicte()["verdicte"]) - chei
    assert not straine, f"verdicte fără element în fișă: {sorted(straine)[:5]}"


def test_the_sample_is_the_same_sample_everywhere():
    """CI, a laptop and a rerun must produce one sheet, or the fingerprint above is noise."""
    lot = candidati()
    assert [c.cheie for c in esantion(lot)] == [c.cheie for c in esantion(lot)]
    assert len(esantion(lot)) == min(ESANTION, len(lot))


def test_the_sample_is_not_all_one_act():
    """A hundred citations of the same law measure one pattern, not an extractor."""
    ales = esantion(candidati())
    assert len({c.fisier for c in ales}) >= 3
    assert len({c.act for c in ales}) >= 20


def test_unmeasured_precision_is_not_reported_as_perfect():
    """The trap this whole file exists to avoid, asserted directly rather than trusted."""
    assert Scor(corecte=0, gresite=0, neclare=0, nelabelate=120).precizie is None
    assert Scor(corecte=19, gresite=1, neclare=0, nelabelate=100).precizie == pytest.approx(0.95)


def test_unclear_verdicts_are_counted_not_dropped():
    """`null` means a reviewer looked and could not tell. That is information about the
    extractor and it must not vanish into the denominator or out of the report."""
    fisa = {"elemente": [{"cheie": "a"}, {"cheie": "b"}, {"cheie": "c"}]}
    verdicte = {"verdicte": {"a": {"corect": True}, "b": {"corect": None}}}
    s = scor(fisa, verdicte)
    assert (s.corecte, s.gresite, s.neclare, s.nelabelate) == (1, 0, 1, 1)
    assert s.judecate == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Precizia referințelor externe nu este încă măsurată: data/etalon-precizie-verdicte.json "
        "este gol. Nu există cheie de răspuns pentru citările de acte — S_LGI marchează "
        "localizatori, nu acte — deci numărul cere un jurist. Când verdictele intră și acest "
        "test trece, `strict` îl transformă în eșec, ca să vină cineva să șteargă marcajul."
    ),
)
def test_precision_holds_over_an_adjudicated_sample():
    s = scor()
    assert s.judecate >= MINIM_JUDECATE, f"doar {s.judecate} candidați judecați"
    assert s.precizie is not None and s.precizie >= PRAG_PRECIZIE
