"""Legislation-as-code: parse a provision-as-rule, render it, check it, enumerate its cases."""

from __future__ import annotations

import pytest

from scripts.lac import (
    Comparatie,
    EroareRegula,
    Nu,
    Regula,
    Sau,
    Si,
    Valoare,
    analizeaza,
    cazuri,
    parseaza,
    randeaza,
    variabile,
    verifica,
)

# --- parsing -----------------------------------------------------------------------------------


def test_parseaza_regula_simpla():
    r = parseaza("DACĂ valoare >= 5000000 lei ATUNCI se aplică procedura deschisă")
    assert isinstance(r.conditie, Comparatie)
    assert r.conditie.var == "valoare"
    assert r.conditie.op == ">="
    assert r.conditie.val.numar == 5000000
    assert r.conditie.val.unitate == "lei"
    assert r.atunci == "se aplică procedura deschisă."
    assert r.altfel is None


def test_parseaza_cu_altfel():
    r = parseaza("DACĂ x > 10 ATUNCI se face A ALTFEL se face B")
    assert r.atunci == "se face A."
    assert r.altfel == "se face B."


def test_parseaza_si_sau_nu():
    r = parseaza("DACĂ a >= 1 ȘI b < 2 SAU NU c = 3 ATUNCI se aplică")
    # precedence: SI binds tighter than SAU -> Sau( Si(a,b), Nu(c) )
    assert isinstance(r.conditie, Sau)
    assert isinstance(r.conditie.parti[0], Si)
    assert isinstance(r.conditie.parti[1], Nu)


def test_operatori_in_cuvinte():
    r = parseaza("DACĂ valoare cel puțin 100 ATUNCI se aplică")
    assert r.conditie.op == ">="
    assert r.conditie.val.numar == 100


def test_fara_diacritice_la_cuvinte_cheie():
    r = parseaza("DACA x > 1 ATUNCI y ALTFEL z")
    assert r.atunci == "y." and r.altfel == "z."


def test_numar_cu_separatori():
    r = parseaza("DACĂ prag >= 5.000.000 lei ATUNCI se aplică")
    assert r.conditie.val.numar == 5000000


def test_numar_zecimal_cu_punct():
    # a bare 1-2 digit fraction is a decimal, not thousands — must not become 25
    r = parseaza("DACĂ rata >= 2.5 ATUNCI se aplică")
    assert r.conditie.val.numar == 2.5


def test_numar_zecimal_cu_virgula():
    r = parseaza("DACĂ rata >= 2,5 ATUNCI se aplică")
    assert r.conditie.val.numar == 2.5


def test_numar_nu_fuzioneaza_peste_spatiu():
    # "12. 5" must not fuse into 125 (only the 12 is the number)
    r = parseaza("DACĂ termen >= 12. 5 zile ATUNCI se aplică")
    assert r.conditie.val.numar == 12


def test_unitate_procent():
    r = parseaza("DACĂ tva >= 19 % ATUNCI se aplică")
    assert r.conditie.val.unitate == "%"


def test_unitate_compusa_zile_lucratoare():
    r = parseaza("DACĂ termen >= 5 zile lucratoare ATUNCI se aplică")
    assert r.conditie.val.unitate == "zile lucratoare"


def test_regula_neconditionala():
    r = parseaza("Autoritatea publică anunțul în 30 de zile")
    assert r.conditie is None
    assert r.atunci.endswith(".")


def test_lipsa_atunci_este_eroare():
    with pytest.raises(EroareRegula):
        parseaza("DACĂ x > 1 se aplică ceva")


def test_operator_lipsa_este_eroare():
    with pytest.raises(EroareRegula):
        parseaza("DACĂ valoare ATUNCI se aplică")


# --- rendering ---------------------------------------------------------------------------------


def test_randeaza_norma_noua():
    r = parseaza(
        "DACĂ valoare >= 5000000 lei ATUNCI se aplică procedura deschisă ALTFEL cea simplă"
    )
    s = randeaza(r, "nou")
    assert s.startswith("Dacă valoare este cel puțin 5.000.000 lei")
    assert "Altfel" in s


def test_randeaza_norma_actuala():
    r = parseaza("DACĂ valoare >= 100 ATUNCI se aplică")
    s = randeaza(r, "actual")
    assert s.startswith("În cazul în care valoare este mai mare sau egal cu 100")


# --- checks ------------------------------------------------------------------------------------


def test_variabile_extrase():
    r = parseaza("DACĂ a >= 1 ȘI b < 2 ATUNCI se aplică")
    assert variabile(r) == ["a", "b"]


def test_conditie_imposibila():
    r = parseaza("DACĂ valoare >= 100 ȘI valoare < 50 ATUNCI se aplică")
    probleme = verifica(r)
    assert any("imposibil" in p for p in probleme)


def test_prag_fara_altfel_semnalat():
    r = parseaza("DACĂ valoare >= 100 ATUNCI se aplică procedura deschisă")
    assert any("ALTFEL" in p for p in verifica(r))


def test_prag_cu_altfel_nu_este_semnalat():
    r = parseaza("DACĂ valoare >= 100 ATUNCI A ALTFEL B")
    assert not any("ALTFEL" in p for p in verifica(r))


def test_ambele_ramuri_identice():
    r = parseaza("DACĂ x > 1 ATUNCI se aplică ALTFEL se aplică")
    assert any("aceeași consecință" in p for p in verifica(r))


# --- case enumeration --------------------------------------------------------------------------


def test_cazuri_straddle_pragul():
    r = parseaza("DACĂ valoare >= 100 ATUNCI deschisă ALTFEL simplă")
    rows = cazuri(r)
    vals = {row["valori"]["valoare"]: row["adevarat"] for row in rows}
    assert vals[99] is False and vals[100] is True and vals[101] is True
    assert any(row["consecinta"] == "deschisă." for row in rows)


def test_cazuri_marginit():
    r = parseaza("DACĂ a >= 1 ȘI b >= 1 ȘI c >= 1 ATUNCI ok")
    assert len(cazuri(r, limita=5)) <= 5


# --- the UI-facing wrapper ---------------------------------------------------------------------


def test_analizeaza_ok():
    d = analizeaza("DACĂ valoare >= 5000000 lei ATUNCI deschisă ALTFEL simplă")
    assert d["ok"] is True
    assert d["conditionala"] is True
    assert d["variabile"] == ["valoare"]
    assert d["proza_nou"].startswith("Dacă")
    assert d["cazuri"]


def test_analizeaza_eroare_este_data():
    d = analizeaza("DACĂ x ATUNCI y")
    assert d["ok"] is False
    assert "eroare" in d


def test_constructie_directa_ast():
    # the AST is usable without the parser (for compunere/round-trip callers)
    r = Regula(conditie=Si((Comparatie("a", ">=", Valoare(numar=1)),)), atunci="ok.")
    assert variabile(r) == ["a"]


# --- enum / string variables -------------------------------------------------------------------


def test_valoare_text_intre_ghilimele():
    r = parseaza('DACĂ procedura = "deschisă" ATUNCI se publică ALTFEL nu')
    assert r.conditie.op == "="
    assert r.conditie.val.text == "deschisă"


def test_enum_contradictoriu():
    r = parseaza('DACĂ tip = "A" ȘI tip = "B" ATUNCI se aplică')
    assert any("imposibil" in p for p in verifica(r))


def test_enum_cazuri_acopera_ambele_ramuri():
    r = parseaza('DACĂ procedura = "deschisă" ATUNCI se publică ALTFEL se restrânge')
    rows = cazuri(r)
    rezultate = {row["adevarat"] for row in rows}
    assert True in rezultate and False in rezultate


# --- serialization + round-trip ----------------------------------------------------------------


def test_roundtrip_regula_numerica():
    r = parseaza("DACĂ valoare >= 5000000 lei ATUNCI A ALTFEL B")
    from scripts.lac import roundtrip, serializeaza

    assert "DACĂ" in serializeaza(r) and "ATUNCI" in serializeaza(r)
    assert roundtrip(r) is True


def test_roundtrip_cu_si_sau():
    r = parseaza("DACĂ a >= 1 ȘI b < 2 SAU NU c = 3 ATUNCI ok")
    from scripts.lac import roundtrip

    assert roundtrip(r) is True


# --- cross-rule checks -------------------------------------------------------------------------


def test_reguli_multiple_parsate():
    from scripts.lac import parseaza_multe

    reguli = parseaza_multe("DACĂ v < 100 ATUNCI mic DACĂ v >= 100 ATUNCI mare")
    assert len(reguli) == 2


def test_reguli_suprapuse_semnalate():
    from scripts.lac import parseaza_multe, verifica_set

    reguli = parseaza_multe("DACĂ v >= 50 ATUNCI A DACĂ v >= 100 ATUNCI B")
    assert any("suprapuse" in p for p in verifica_set(reguli))


def test_reguli_cu_gol_semnalate():
    from scripts.lac import parseaza_multe, verifica_set

    # < 50 and >= 100 leave [50, 100) unhandled
    reguli = parseaza_multe("DACĂ v < 50 ATUNCI A DACĂ v >= 100 ATUNCI B")
    probleme = verifica_set(reguli)
    assert any("neacoperit" in p for p in probleme)


def test_reguli_acoperire_completa_fara_probleme():
    from scripts.lac import parseaza_multe, verifica_set

    # < 100 and >= 100 partition the line with no overlap and no gap
    reguli = parseaza_multe("DACĂ v < 100 ATUNCI A DACĂ v >= 100 ATUNCI B")
    assert verifica_set(reguli) == []


def test_analizeaza_multi_regula():
    d = analizeaza("DACĂ v >= 50 ATUNCI A DACĂ v >= 100 ATUNCI B")
    assert d["ok"] is True and d.get("multi") is True
    assert len(d["reguli"]) == 2
    assert any("suprapuse" in p for p in d["probleme_set"])
