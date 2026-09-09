"""Deadline candidates must match the obligation, not just two numbers."""

import pytest

from scripts.contradictii_termene import termen_comparabil, termene_diferite


def _text(durata="30 de zile", *, trigger="înregistrarea cererii"):
    return f"Autoritatea contractantă comunică decizia în termen de {durata} de la {trigger}."


def test_same_obligation_with_different_duration_preserves_evidence():
    a = termen_comparabil(_text())
    b = termen_comparabil(_text("60 de zile"))
    assert a["cheie"] == b["cheie"]
    assert termene_diferite(a, b)
    assert a["responsabil"] == "autoritatea contractanta"
    assert a["actiune"] == "comunica decizia"
    assert a["eveniment"] == "inregistrarea cererii"
    assert a["termen_text"] == "în termen de 30 de zile"
    assert a["text"] == _text()
    assert a["baza"] == "neprecizata"


@pytest.mark.parametrize(
    "durata, diferite",
    [
        ("treizeci de zile", False),
        ("30 zile calendaristice", False),
        ("30 zile lucrătoare", False),
        ("60 zile lucrătoare", True),
    ],
)
def test_number_words_and_unspecified_basis(durata, diferite):
    a, b = termen_comparabil(_text()), termen_comparabil(_text(durata))
    assert a["cheie"] == b["cheie"]
    assert termene_diferite(a, b) is diferite


def test_explicit_working_calendar_difference():
    a = termen_comparabil(_text("30 de zile lucrătoare"))
    b = termen_comparabil(_text("30 de zile calendaristice"))
    assert a["cheie"] == b["cheie"]
    assert termene_diferite(a, b)
    assert a["baza"] == "lucratoare"


@pytest.mark.parametrize("durata", ["o lună", "un an", "12 luni"])
def test_units_never_converted_to_approximate_days(durata):
    assert termen_comparabil(_text())["cheie"] != termen_comparabil(_text(durata))["cheie"]


@pytest.mark.parametrize(
    "replacement",
    [
        ("Autoritatea contractantă", "Ministerul Finanțelor"),
        ("comunică", "aprobă"),
        ("decizia", "autorizația"),
        ("înregistrarea cererii", "primirea documentației complete"),
        ("cererii", "cererii de autorizare"),
    ],
)
def test_different_party_action_object_or_trigger_do_not_match(replacement):
    a = termen_comparabil(_text())
    b = termen_comparabil(_text("60 zile").replace(*replacement))
    assert b is not None
    assert a["cheie"] != b["cheie"]


@pytest.mark.parametrize(
    "text",
    [
        _text(trigger="intrarea în vigoare a prezentei legi"),
        _text(trigger="data publicării"),
        _text(trigger="evenimentul prevăzut la art. 3"),
        _text(trigger="data menționată mai sus"),
        _text(trigger="înregistrarea acestei cereri"),
        _text().replace(" de la înregistrarea cererii", ""),
        _text().replace("Autoritatea contractantă comunică", "Se comunică"),
        _text().replace("comunică", "poate comunica"),
        _text().replace("30 de zile", "0 zile"),
        _text().replace("30 de zile", "multe zile"),
        _text().replace("30 de zile", "30-60 zile"),
        _text().replace("30 de zile", "o lună lucrătoare"),
        _text().replace("30 de zile", "30 de zile sau în termen de 60 zile"),
        _text() + " Prin excepție, termenul este de 60 zile.",
        _text().replace("decizia", "decizia, dacă cererea este completă,"),
    ],
)
def test_ambiguous_and_conditional_provisions_are_excluded(text):
    assert termen_comparabil(text) is None


def test_article_headers_and_diacritics_do_not_change_obligation():
    a = termen_comparabil("Art. 3. - (1) " + _text())
    b = termen_comparabil("Art. 7. - (2) " + _text("60 zile").replace("în", "in"))
    assert a is not None and b is not None
    assert a["cheie"] == b["cheie"]
