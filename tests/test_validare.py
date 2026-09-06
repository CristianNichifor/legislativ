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


def test_unparseable_output_is_reported_rather_than_read_as_no_findings():
    """It used to return an empty pair, which is the mistake the next test names: an unreadable
    reply and a clean bill of health are the same empty list, and they mean opposite things. A
    model that answered in prose has not told you there is nothing wrong with the draft."""
    constatari, respinse = citeste("nu pot răspunde la această întrebare")
    assert constatari == []
    assert [r.motiv_respingerii for r in respinse] == ["raspuns-neparsabil"]


def test_a_reasoning_model_that_thinks_out_loud_is_still_read():
    """Qwen3 and the DeepSeek-R1 distills emit `<think>…</think>` before the answer by default.
    Every reply from them parsed as nothing at all, which read as a clean draft."""
    constatari, respinse = citeste(
        "<think>Trebuie să compar textele.</think>\n"
        '[{"tip":"acelasi-viciu","provizie":"d-1","citat":"un citat destul de lung","motiv":"m"}]'
    )
    assert respinse == []
    assert [c.provizie for c in constatari] == ["d-1"]


def test_a_thought_that_never_finished_is_reported_not_swallowed():
    """A model that ran out of tokens mid-thought emitted no JSON at all."""
    _, respinse = citeste("<think>Mă gândesc și nu apuc să termin")
    assert [r.motiv_respingerii for r in respinse] == ["raspuns-neparsabil"]


def test_json_buried_in_prose_is_still_found():
    constatari, _ = citeste(
        'Iată răspunsul:\n[{"tip":"t","provizie":"d-1","citat":"un citat destul de lung",'
        '"motiv":"m"}]\nSper că ajută.'
    )
    assert [c.provizie for c in constatari] == ["d-1"]


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


def test_a_flood_of_unclosed_thinking_tags_does_not_hang_the_parser():
    """`py/polynomial-redos`, and a real one: on the browser path this string arrives straight from
    a client POST. The obvious `re.sub(r"<think>.*?</think>", …)` rescans forward from every opening
    tag looking for a close that is not there, so a few hundred kilobytes of `<think>` would hold
    the localhost server inside one regex. The scan that replaced it only moves forward.

    The bound is deliberately generous — this is not a performance measurement, it is a trap for
    catastrophic backtracking, which misses it by orders of magnitude.
    """
    import time

    patologic = "<think>" * 40_000
    t0 = time.monotonic()
    _, respinse = citeste(patologic)
    assert time.monotonic() - t0 < 2.0, "quadratic backtracking is back"
    assert [r.motiv_respingerii for r in respinse] == ["raspuns-neparsabil"]


def test_several_thinking_blocks_are_all_removed():
    constatari, _ = citeste(
        "<think>întâi</think> ceva text <THINK>și a doua oară</THINK>\n"
        '[{"tip":"t","provizie":"d-1","citat":"un citat destul de lung","motiv":"m"}]'
    )
    assert [c.provizie for c in constatari] == ["d-1"]
