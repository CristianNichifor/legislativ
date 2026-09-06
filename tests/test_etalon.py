"""The gold set is part of the product, so it is tested like the rest of it.

A scoring harness that can silently stop measuring is worse than none: the number keeps printing
and stops meaning anything.
"""

from __future__ import annotations

import json

from scripts.etalon import ETALON, evalueaza, raporteaza


def test_the_gold_set_is_not_trimmed_to_flatter_the_score():
    """A case may be *fixed*; it may not be *removed*.

    This used to assert that some case was still marked `cunoscut_ratat`, with `ref-10` — article
    enumerations — as the standing failure. That case now passes, so the assertion would force the
    set to keep a failure on purpose, which is not what the principle protects. The principle is
    that the score must never be raised by deleting the cases that produce it, and a floor on the
    count says exactly that: fixing an extractor keeps the case and turns it green, trimming the
    set fails here.
    """
    cazuri = json.loads(ETALON.read_text(encoding="utf-8"))["cazuri"]
    assert len(cazuri) >= 36, "cazuri scoase din etalon — scorul urcă fără un extractor mai bun"


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


def test_the_report_names_the_cases_that_fail_not_just_the_total(tmp_path):
    """An aggregate that does not say which cases fail cannot be acted on.

    Checked against a case built to fail rather than a real one. Naming a live case meant this
    test could only pass while that case stayed broken — it went red the moment `ref-10` was
    fixed, which is the wrong way round for a test guarding the *reporting*, not the extractor.
    """
    fals = {
        "cazuri": [
            {
                "id": "fals-1",
                "grup": "referinte",
                "text": "Se aplică art. 7 din Legea nr. 98/2016.",
                # deliberately wrong: the extractor reads art. 7, so art. 9 comes back missing
                "asteptat": {"referinte": [["lege-98-2016", "art9"]]},
                "nota": "caz sintetic, doar pentru acest test",
            }
        ]
    }
    cale = tmp_path / "etalon.json"
    cale.write_text(json.dumps(fals, ensure_ascii=False), encoding="utf-8")

    raport = raporteaza(cale)
    assert "fals-1" in raport, "raportul nu numește cazul care cade"
    assert "abateri" in raport
    assert "art9" in raport, "raportul nu spune ce anume lipsește"
