"""Tests for definitions and the terminology check.

The masking test exists because the first version of the check did the opposite of its job: it
flagged `o autoritate contractantă` — a correct use with an article in front — and stayed silent
on `achiziții de stat`, which is the drafting error it was built to catch.
"""

from __future__ import annotations

from scripts.definitii import definitii, jargon

LEGE = """Art. 3. - În sensul prezentei legi, termenii și expresiile de mai jos au următoarele
semnificații:
a) achiziție publică - achiziția de lucrări, de produse sau de servicii de către una ori mai
multe autorități contractante;
b) autoritate contractantă - entitățile prevăzute la art. 4;
Prin ofertant se înțelege orice operator economic care a depus o ofertă."""


def test_both_the_enumerated_and_the_inline_definition_forms_are_read():
    termeni = {t.termen for t in definitii(LEGE)}
    assert termeni == {"achiziție publică", "autoritate contractantă", "ofertant"}


def test_a_definition_keeps_its_text_so_the_warning_can_show_it():
    achizitie = next(t for t in definitii(LEGE) if t.termen == "achiziție publică")
    assert achizitie.definitie.startswith("achiziția de lucrări")


def test_using_a_defined_term_correctly_is_silent():
    """In any inflection — plural, enclitic article, missing diacritics — and with an article or
    preposition in front of it, which is how it is normally written. Romanian inflection is not
    a drafting error, and flagging it is what made the first version unusable."""
    assert (
        jargon("Se aplică oricărei autorități contractante și oricărui ofertant.", definitii(LEGE))
        == []
    )
    assert jargon("O autoritate contractantă publică anunțul.", definitii(LEGE)) == []
    assert jargon("Autoritatea contractanta transmite rezultatul.", definitii(LEGE)) == []


def test_a_parallel_category_is_caught_by_its_head_word():
    """`achiziții de stat` opens with the defined term's own noun and qualifies it differently —
    the drafting error that creates a second legal category beside the one the law defines."""
    avertismente = jargon("Prezenta lege se aplică oricărei achiziții de stat.", definitii(LEGE))
    assert [a.regula for a in avertismente] == ["categorie-paralela"]
    assert avertismente[0].termen.termen == "achiziție publică"
    assert "de stat" in avertismente[0].fragment


def test_drift_the_stemmer_cannot_explain_away_is_caught_as_a_variant():
    """`contractuală` is not an inflection of `contractantă` — it is a different word that
    resembles it, which is the case the variant rule is left in for."""
    avertismente = jargon("Autoritatea contractuală transmite rezultatul.", definitii(LEGE))
    assert [a.regula for a in avertismente] == ["varianta"]


def test_a_warning_is_never_verbatim_because_it_is_a_score():
    a = jargon("Autoritatea contractuală transmite rezultatul.", definitii(LEGE))[0]
    assert a.increderea == "derived" and 0.0 < a.scor < 1.0


def test_a_single_word_definition_does_not_raise_parallel_category_warnings():
    """A one-word term has no qualifier to diverge in, so the rule would fire on every
    inflection of a common noun."""
    avertismente = jargon("Ofertele se depun de ofertanții interesați.", definitii(LEGE))
    assert all(a.regula != "categorie-paralela" for a in avertismente)
