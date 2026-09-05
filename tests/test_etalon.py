"""The gold set is part of the product, so it is tested like the rest of it.

A scoring harness that can silently stop measuring is worse than none: the number keeps printing
and stops meaning anything.
"""

from __future__ import annotations

import json

from scripts.etalon import ETALON, evalueaza, raporteaza


def test_the_gold_set_keeps_its_known_failures():
    """Removing them would raise the printed score and drop the information in it to zero. A
    linter reporting 100% on a set curated to make it report 100% is the failure mode this
    repository exists against."""
    cazuri = json.loads(ETALON.read_text(encoding="utf-8"))["cazuri"]
    assert any(c.get("cunoscut_ratat") for c in cazuri)


def test_every_case_says_why_it_is_there():
    cazuri = json.loads(ETALON.read_text(encoding="utf-8"))["cazuri"]
    assert all(c.get("nota") for c in cazuri), "un caz fără motiv nu poate fi întreținut"


def test_the_extractors_do_not_regress_below_where_they_stand():
    """A floor, not a target. It is deliberately below the current score so that a real
    improvement does not have to edit this test, while a regression fails it."""
    scoruri, _ = evalueaza()
    for nume, s in scoruri.items():
        assert s.precizie >= 0.95, f"{nume}: precizia a scăzut la {s.precizie:.1%}"
        assert s.acoperire >= 0.80, f"{nume}: acoperirea a scăzut la {s.acoperire:.1%}"


def test_the_report_names_the_cases_that_fail_not_just_the_total():
    """An aggregate that does not say which cases fail cannot be acted on."""
    raport = raporteaza()
    assert "ref-10" in raport and "abateri" in raport
