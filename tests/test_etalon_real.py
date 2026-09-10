"""The real gold set is part of the product, so it is tested like the rest of it.

A measurement that can quietly stop measuring is worse than none. These assert the harness runs
against committed fixtures, that the acts it scores actually carry publisher marks, and that
reference recall holds above a floor — set below today's number so a real improvement need not
edit the test while a regression fails it.
"""

from __future__ import annotations

from scripts.etalon_real import masoara, recall_global


def test_there_are_marked_acts_to_measure_against():
    masuri = masoara()
    assert masuri, "niciun act cu marcaje S_LGI în sources/"
    assert sum(m.marcaje for m in masuri) > 500  # a real, citation-dense sample


def test_locator_recall_holds_against_the_publishers_own_marks():
    """98.7% today over 822 marks. The floor is 0.93 — a regression below it fails; an
    improvement above it does not have to touch this line.

    Named for locators since 2026-09-10: `S_LGI` marks positions, not citations of other acts,
    and 808 of those 822 marks are `lit. e)`-shaped. Reference precision is measured by
    `etalon_precizie.py` against human verdicts; external reference recall is measured by
    nothing yet, and calling this number reference recall was what hid that."""
    assert recall_global(masoara()) >= 0.93


def test_each_marked_act_recalls_most_of_its_marks():
    """No single act collapses — a corpus-wide average can hide one act at 40%."""
    for m in masoara():
        assert m.recall >= 0.85, f"{m.act}: recall a scăzut la {m.recall:.1%}"
