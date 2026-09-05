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


def test_reference_recall_holds_against_the_publishers_own_marks():
    """97.2% today over 822 marks. The floor is 0.93 — a regression below it fails; an
    improvement above it does not have to touch this line."""
    assert recall_global(masoara()) >= 0.93


def test_each_marked_act_recalls_most_of_its_references():
    """No single act collapses — a corpus-wide average can hide one act at 40%."""
    for m in masoara():
        assert m.recall >= 0.85, f"{m.act}: recall a scăzut la {m.recall:.1%}"
