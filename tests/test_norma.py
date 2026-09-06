"""The norm-consistency check: classify a passage, and catch a project that mixes the two norms."""

from __future__ import annotations

from scripts.norma import clasifica, coerenta, unitati

# --- classifying a single unit ---------------------------------------------------------------


def test_registrul_curent_recunoscut():
    u = clasifica("Prezentul articol se modifică și va avea următorul cuprins.")
    assert u.norma == "actual"
    assert u.scor_actual > u.scor_nou


def test_limbaj_clar_recunoscut():
    u = clasifica("Autoritatea contractantă trebuie să publice anunțul în 30 de zile.")
    assert u.norma == "nou"
    assert u.scor_nou > u.scor_actual


def test_daca_atunci_este_norma_noua():
    u = clasifica("Dacă cererea este incompletă, atunci autoritatea o respinge.")
    assert u.norma == "nou"


def test_fara_marcaj_este_neutru():
    u = clasifica("Anexa cuprinde lista completă a documentelor.")
    assert u.norma == "neutru"


def test_numar_scris_in_litere_leaga_de_registrul_curent():
    u = clasifica("Contractantul depune garanția în cincisprezece zile.")
    assert u.norma == "actual"


def test_marcajele_ignora_lipsa_diacriticelor():
    cu = clasifica("Prezentul articol se modifică.")
    fara = clasifica("Prezentul articol se modifica.")
    assert cu.norma == fara.norma == "actual"


# --- splitting into units --------------------------------------------------------------------


def test_unitati_pe_puncte_numerotate():
    text = "1. Autoritatea publică anunțul.\n2. Termenul este de 30 de zile."
    assert len(unitati(text)) == 2


def test_unitati_pe_paragrafe_cand_nu_sunt_puncte():
    text = "Primul paragraf despre ceva.\n\nAl doilea paragraf despre altceva."
    assert len(unitati(text)) == 2


def test_un_singur_bloc_este_o_unitate():
    assert len(unitati("O singură propoziție fără puncte.")) == 1


def test_text_gol_nu_are_unitati():
    assert unitati("   \n  ") == []


# --- the whole-project verdict ---------------------------------------------------------------


def test_proiect_coerent_intr_o_singura_norma():
    text = (
        "1. Autoritatea contractantă trebuie să publice anunțul în 30 de zile.\n"
        "2. Ofertantul are dreptul să conteste rezultatul în 10 zile."
    )
    c = coerenta(text)
    assert c.coerent
    assert c.dominanta == "nou"
    assert c.abateri == ()


def test_proiect_mixt_este_semnalat():
    text = (
        "1. Autoritatea contractantă trebuie să publice anunțul în 30 de zile.\n"
        "2. Ofertantul are dreptul să conteste rezultatul în 10 zile.\n"
        "3. Prezentul articol se modifică și va avea următorul cuprins."
    )
    c = coerenta(text)
    assert not c.coerent
    assert c.dominanta == "nou"
    assert len(c.abateri) == 1
    assert "se modifică" in c.abateri[0].text


def test_proiect_neutru_nu_este_semnalat_ca_mixt():
    c = coerenta("Anexa cuprinde lista.\n\nDocumentele sunt atașate.")
    assert c.coerent
    assert c.dominanta == "neutru"


def test_raportul_numeste_norma_si_abaterea():
    text = (
        "1. Autoritatea trebuie să publice anunțul în 30 de zile.\n"
        "2. Prezentul articol se modifică."
    )
    r = coerenta(text).raport()
    assert "mixt" in r.lower()
    assert "se modifică" in r
