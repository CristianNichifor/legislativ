"""Tests for the assembled report.

The section that did not run is tested as carefully as the sections that did, because to a
reader an empty contradictions list and a contradictions pass that never executed look the same,
and the difference is the entire meaning of the result.
"""

from __future__ import annotations

import json
from datetime import date

from scripts.linter import EXEMPLU, analizeaza, din_exemplu

PROIECT = json.loads(EXEMPLU.read_text(encoding="utf-8"))["proiect"]


def _analiza(model=None):
    corpus, obligatii_corpus, termeni, provizii = din_exemplu()
    return analizeaza(
        proiect=PROIECT,
        corpus=corpus,
        obligatii_corpus=obligatii_corpus,
        termeni=termeni,
        provizii=provizii,
        la_data=date(2026, 9, 4),
        model=model,
    )


def test_an_obligation_the_corpus_discharges_does_not_appear_and_one_it_cannot_does():
    """HG 395/2016 answers the norms obligation; nothing in the corpus answers the order."""
    raport = _analiza()
    tinte = {f"{v.obligatie.act.id} {v.obligatie.locator.id}" for v in raport.vid}
    assert tinte == {"lege-98-2016 art236"}
    assert raport.vid[0].severitate == "blocking"


def test_the_terminology_pass_finds_the_parallel_category_in_the_draft():
    raport = _analiza()
    assert any(a.regula == "categorie-paralela" for a in raport.jargon)


def test_the_contradiction_section_says_it_did_not_run_rather_than_looking_empty():
    raport = _analiza()
    assert raport.contradictii is None
    assert "Nu a rulat" in raport.text()


def test_the_context_handed_to_the_model_is_what_the_validator_holds_it_to():
    """Anything the model cites outside this set was reached for from memory."""
    raport = _analiza()
    assert "lege-98-2016 art7.alin2" in raport.context
    assert all(cheie.split()[0] in {"lege-98-2016", "hg-395-2016"} for cheie in raport.context)


def test_a_grounded_model_finding_survives_and_an_invented_one_does_not():
    """One fixture response carrying both, so the gate is exercised the way a real model
    exercises it: some of the output is usable and some of it is invented."""

    def model(prompt: str) -> str:
        assert "CONTEXT:" in prompt and "PROIECT:" in prompt
        return json.dumps(
            [
                {
                    "tip": "contradictie",
                    "provizie": "lege-98-2016 art7.alin2",
                    "citat": "publica anunțul de participare în termen de 15 zile",
                    "motiv": "proiectul prevede 30 de zile pentru aceeași obligație",
                    "fragment_proiect": "în termen de 30 de zile",
                },
                {
                    "tip": "contradictie",
                    "provizie": "lege-215-2001 art23",
                    "citat": "consiliul local hotărăște în condițiile legii",
                    "motiv": "articol care nu a fost trimis modelului",
                },
            ]
        )

    raport = _analiza(model=model)
    assert [c.provizie for c in raport.contradictii.acceptate] == ["lege-98-2016 art7.alin2"]
    assert [r.motiv_respingerii for r in raport.contradictii.respinse] == ["provizie-inexistenta"]

    # The invented citation is in the report — as a rejection, which is the point. The rejection
    # rate is how a team decides whether this model can be trusted on this corpus at all, so it
    # is shown rather than swallowed. What must never happen is its appearing as a finding.
    text = raport.text()
    assert "✗ [lege-215-2001 art23]" in text
    assert "• [lege-215-2001" not in text
    assert raport.contradictii.rata_de_respingere == 0.5


def test_a_model_that_answers_in_prose_costs_nothing_downstream():
    """Small models do this. It must degrade to an empty, honest section rather than raise."""
    raport = _analiza(model=lambda _: "Nu am suficiente informații pentru a răspunde.")
    assert raport.contradictii.acceptate == ()


def test_the_example_fixture_says_it_is_not_real_legal_text():
    """It is written in the register of Romanian legislation and would otherwise be quotable as if
    it were the law. The warning is a `blocking` limitation rather than a field of its own, so it
    means here exactly what it means in every dataset in this repository."""
    date_ = json.loads(EXEMPLU.read_text(encoding="utf-8"))
    blocante = [lim for lim in date_["limitations"] if lim["severity"] == "blocking"]
    assert any("NU TEXT DE LEGE" in lim["text"] for lim in blocante)
    assert all(lim["affects"] for lim in date_["limitations"])
