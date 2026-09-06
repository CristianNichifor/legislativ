"""Recognising defined terms in a draft — the chips the editor shows, and their definitions."""

from __future__ import annotations

from scripts.definitii import Termen, recunoaste

_TERMENI = [
    Termen(termen="autoritate contractantă", definitie="entitatea care atribuie contractul"),
    Termen(termen="achiziție publică", definitie="achiziția de lucrări, produse sau servicii"),
    Termen(termen="dobîndă", definitie="echivalentul folosirii capitalului"),
]


def test_recunoaste_termen_exact():
    o = recunoaste("Autoritatea contractantă publică anunțul.", _TERMENI)
    assert [x.termen.termen for x in o] == ["autoritate contractantă"]
    assert o[0].termen.definitie.startswith("entitatea")


def test_recunoaste_forma_flexionata():
    # plural / genitive of the defined term still counts as a use, not a deviation
    o = recunoaste("Deciziile autorităților contractante sunt publice.", _TERMENI)
    assert any(x.termen.termen == "autoritate contractantă" for x in o)


def test_mai_multi_termeni_in_ordinea_aparitiei():
    # nominative forms, so both stems match exactly; ordered by first appearance
    text = "Fiecare achiziție publică se face de o autoritate contractantă."
    o = recunoaste(text, _TERMENI)
    nume = [x.termen.termen for x in o]
    assert nume == ["achiziție publică", "autoritate contractantă"]
    assert o[0].start < o[1].start


def test_un_singur_marcaj_per_termen():
    text = "Autoritatea contractantă și cealaltă autoritate contractantă."
    o = recunoaste(text, _TERMENI)
    assert sum(x.termen.termen == "autoritate contractantă" for x in o) == 1


def test_fragmentul_pastreaza_forma_din_text():
    # the recorded fragment is the draft's own inflected surface form, for highlighting
    o = recunoaste("Deciziile autorității contractante rămân publice.", _TERMENI)
    assert o and o[0].termen.termen == "autoritate contractantă"
    assert "autorit" in o[0].fragment.lower() and o[0].fragment != "autoritate contractantă"


def test_termen_scurt_inclus_in_unul_lung_este_suprimat():
    # "funcționar" nested in "funcționar public" is noise — only the longer term survives
    termeni = [
        Termen(termen="funcționar", definitie="persoana din serviciul unei unități"),
        Termen(termen="funcționar public", definitie="funcționar în serviciul unei autorități"),
    ]
    o = recunoaste("Fiecare funcționar public răspunde.", termeni)
    assert [x.termen.termen for x in o] == ["funcționar public"]


def test_niciun_termen_recunoscut():
    assert recunoaste("Un text oarecare fără termeni definiți.", _TERMENI) == []


def test_text_gol():
    assert recunoaste("", _TERMENI) == []
