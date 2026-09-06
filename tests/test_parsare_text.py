"""Tests for the plain-text act parser.

The parser recovers Articol ▸ Alineat ▸ Literă from the numbering alone, so the cases that matter
are the ones where the numbering also appears as a *reference* inside the running text: the parser
must take the headings and skip the citations.
"""

from __future__ import annotations

from scripts.parsare_text import parseaza_text


def _art(res, i=0):
    return res["noduri"][i]


def test_gol():
    assert parseaza_text("")["noduri"] == []
    assert parseaza_text("   \n ")["noduri"] == []


def test_articol_cu_alineate():
    res = parseaza_text("Articolul 7\n(1) Primul alineat.\n(2) Al doilea alineat.")
    art = _art(res)
    assert art["nivel"] == "art" and art["numar"] == "7"
    assert [a["numar"] for a in art["copii"]] == ["1", "2"]
    assert art["copii"][0]["text"] == "Primul alineat."
    assert art["copii"][1]["text"] == "Al doilea alineat."


def test_abrevieri_si_bis():
    res = parseaza_text("Art. 12^1. - Conținut.")
    assert _art(res)["numar"] == "12^1"
    assert _art(res)["text"] == "Conținut."


def test_litere_in_alineat():
    res = parseaza_text(
        "Articolul 3\n(1) Se constituie prin:\na) virament bancar;\nb) instrumente."
    )
    alin = _art(res)["copii"][0]
    assert alin["text"] == "Se constituie prin:"
    assert [c["numar"] for c in alin["copii"]] == ["a", "b"]
    assert alin["copii"][0]["text"] == "virament bancar;"
    assert alin["copii"][1]["text"] == "instrumente."


def test_ignora_referinte_in_secventa():
    # "(2)" is cited inside alineat (1) before the real (2); the parser must not split there.
    t = (
        "Articolul 5\n(1) Autoritatea, potrivit art. 7 alin. (2), decide.\n"
        "(2) Termenul este de 30 de zile."
    )
    art = _art(parseaza_text(t))
    assert [a["numar"] for a in art["copii"]] == ["1", "2"]
    assert "art. 7 alin. (2)" in art["copii"][0]["text"]
    assert art["copii"][1]["text"] == "Termenul este de 30 de zile."


def test_text_inline_fara_intreruperi():
    # everything on one line, markers glued to punctuation — the wall-of-text case from the corpus.
    t = "Articolul 154 (1) Autoritatea are obligația.(2) Are dreptul prin:a) unu;b) doi."
    art = _art(parseaza_text(t))
    assert art["numar"] == "154"
    assert [a["numar"] for a in art["copii"]] == ["1", "2"]
    assert [c["numar"] for c in art["copii"][1]["copii"]] == ["a", "b"]


def test_mai_multe_articole():
    res = parseaza_text("Articolul 1\nPrima dispoziție.\nArticolul 2\nA doua dispoziție.")
    assert [n["numar"] for n in res["noduri"]] == ["1", "2"]
    assert res["noduri"][0]["text"] == "Prima dispoziție."
    assert res["noduri"][1]["text"] == "A doua dispoziție."


def test_chapeau_pastrat():
    res = parseaza_text("Articolul 9\nDispoziții generale.\n(1) Primul.\n(2) Al doilea.")
    art = _art(res)
    assert art["text"] == "Dispoziții generale."
    assert len(art["copii"]) == 2


def test_fara_antet_un_singur_articol():
    res = parseaza_text("(1) Un text fără antet de articol.\n(2) Al doilea.")
    art = _art(res)
    assert art["numar"] == ""
    assert [a["numar"] for a in art["copii"]] == ["1", "2"]


def test_litera_nu_e_confundata_cu_cuvant():
    # a ")" that closes a word or an inline "(2)" must not read as a litera marker.
    res = parseaza_text("Articolul 4\n(1) Contractul (în forma sa) rămâne valabil.")
    assert _art(res)["copii"][0]["copii"] == []
