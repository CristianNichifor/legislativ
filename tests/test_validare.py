"""Tests for the gate in front of the model.

Each test is one way a fluent, well-formatted, correctly-typed finding can still be worthless.
"""

from __future__ import annotations

from scripts.validare import Constatare, citeste, valideaza

CONTEXT = {
    "lege-98-2016 art7.alin2": (
        "Autoritatea contractantă are obligația de a publica anunțul de participare în termen "
        "de 15 zile de la data aprobării."
    )
}


def _constatare(provizie: str, citat: str) -> Constatare:
    return Constatare("contradictie", provizie, citat, "proiectul prevede alt termen")


def test_a_quoted_finding_from_the_supplied_context_survives():
    rezultat = valideaza(
        [
            _constatare(
                "lege-98-2016 art7.alin2",
                "obligația de a publica anunțul de participare în termen de 15 zile",
            )
        ],
        CONTEXT,
    )
    assert len(rezultat.acceptate) == 1 and not rezultat.respinse


def test_a_provision_that_was_never_in_the_prompt_is_rejected_even_if_it_exists():
    """A model that cites it reached for it from memory, so the finding is not about this
    corpus whether or not the article is real."""
    rezultat = valideaza([_constatare("lege-215-2001 art23", "consiliul local hotărăște")], CONTEXT)
    assert rezultat.respinse[0].motiv_respingerii == "provizie-inexistenta"


def test_a_paraphrase_is_rejected():
    """This is where a contradiction quietly becomes one between what the law says and what the
    model remembers it saying."""
    rezultat = valideaza(
        [_constatare("lege-98-2016 art7.alin2", "termen de 10 zile de la aprobare")], CONTEXT
    )
    assert rezultat.respinse[0].motiv_respingerii == "citat-neregasit"


def test_a_quote_too_short_to_check_is_rejected():
    rezultat = valideaza([_constatare("lege-98-2016 art7.alin2", "15 zile")], CONTEXT)
    assert rezultat.respinse[0].motiv_respingerii == "citat-prea-scurt"


def test_matching_folds_diacritics_and_case_but_nothing_looser():
    rezultat = valideaza(
        [
            _constatare(
                "lege-98-2016 art7.alin2",
                "OBLIGATIA de a publica anuntul de participare in termen de 15 zile",
            )
        ],
        CONTEXT,
    )
    assert len(rezultat.acceptate) == 1


def test_the_same_finding_twice_is_kept_once():
    citat = "obligația de a publica anunțul de participare în termen de 15 zile"
    rezultat = valideaza([_constatare("lege-98-2016 art7.alin2", citat)] * 2, CONTEXT)
    assert len(rezultat.acceptate) == 1 and rezultat.respinse[0].motiv_respingerii == "duplicat"


def test_fenced_json_from_a_small_model_is_read():
    """Local models wrap JSON in a code fence regardless of instructions."""
    constatari, _ = citeste(
        '```json\n[{"provizie": "lege-98-2016 art7.alin2", "citat": "x", "motiv": "y"}]\n```'
    )
    assert len(constatari) == 1 and constatari[0].provizie == "lege-98-2016 art7.alin2"


def test_unparseable_output_yields_nothing_rather_than_raising():
    assert citeste("nu pot răspunde la această întrebare") == ([], [])


def test_a_finding_missing_its_required_fields_is_rejected_not_dropped_silently():
    """The rejected list is the measurement of the model. Swallowing malformed output would
    make a bad model look like a quiet one."""
    _, respinse = citeste([{"provizie": "lege-98-2016 art7.alin2"}])
    assert respinse[0].motiv_respingerii == "camp-lipsa"


def test_the_rejection_rate_is_reported_because_it_is_the_number_that_matters():
    rezultat = valideaza(
        [
            _constatare(
                "lege-98-2016 art7.alin2",
                "obligația de a publica anunțul de participare în termen de 15 zile",
            ),
            _constatare("lege-215-2001 art23", "consiliul local hotărăște ce vrea"),
        ],
        CONTEXT,
    )
    assert rezultat.rata_de_respingere == 0.5
