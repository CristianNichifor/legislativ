"""Raza de impact: measuring an amendment's downstream reach, and the trojan-horse signal."""

from __future__ import annotations

from scripts.impact import raza_de_impact

# a small amendment that redefines a term and cites nothing heavy on its face
_MIC_DAR_LARG = (
    "La articolul 3 din Legea nr. 98/2016 privind achizițiile publice, litera a) se modifică și "
    "va avea următorul cuprins: «a) autoritate contractantă - orice entitate publică sau privată;»"
)


def _citari(mapare):
    return lambda act_id: mapare.get(act_id, (0, 0))


def test_structural_reach_counts_inbound_references():
    d = "La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică."
    r = raza_de_impact(d, citari_fn=_citari({"lege-98-2016": (83, 12)}))
    assert r["tinte"][0]["act_id"] == "lege-98-2016"
    assert r["tinte"][0]["citari"] == 83
    assert r["tinte"][0]["citari_amendatoare"] == 12


def test_a_redefinition_is_detected_and_carries_its_usage_count():
    r = raza_de_impact(
        _MIC_DAR_LARG,
        citari_fn=_citari({"lege-98-2016": (5, 1)}),
        numara_termen=lambda t: 240 if "autoritate" in t else 0,
    )
    termeni = {t["termen"]: t["utilizari"] for t in r["termeni_redefiniti"]}
    assert any("autoritate" in k for k in termeni)
    assert max(termeni.values()) == 240


def test_the_trojan_flag_fires_on_a_small_payload_with_large_reach():
    # tiny replacement text, but the redefined term is used in hundreds of provisions
    r = raza_de_impact(
        _MIC_DAR_LARG,
        citari_fn=_citari({"lege-98-2016": (10, 2)}),
        numara_termen=lambda t: 300,
    )
    assert r["scor"]["troian"] is True
    assert r["scor"]["nivel"] == "ridicat"


def test_a_plain_small_change_with_no_reach_is_not_flagged():
    d = "La articolul 7 din Legea nr. 500/2002, alineatul (1) se modifică."
    r = raza_de_impact(d, citari_fn=_citari({}))
    assert r["scor"]["troian"] is False
    assert r["scor"]["nivel"] == "neutru"


def test_a_repeal_counts_toward_reach():
    d = "Articolul 12 din Legea nr. 98/2016 se abrogă."
    r = raza_de_impact(d, citari_fn=_citari({"lege-98-2016": (0, 0)}))
    assert r["tinte"][0]["abrogari"] == ["art12"]
    # the abrogation contributes to the reach even with zero citations
    assert r["scor"]["raza"] >= 5


def test_missing_corpus_leaves_the_usage_count_null_not_zero():
    r = raza_de_impact(_MIC_DAR_LARG, citari_fn=_citari({"lege-98-2016": (1, 0)}))
    assert all(t["utilizari"] is None for t in r["termeni_redefiniti"])


_ORIGINAL_CU_RAPORT = (
    "Autoritatea publică anunțul de participare. "
    "Autoritatea transmite raportul în termen de 30 de zile de la încheiere."
)


def test_a_modification_that_drops_an_obligation_flags_it_removed():
    # the new text keeps the publishing sentence but silently drops the reporting duty
    d = (
        "La articolul 5 din Legea nr. 98/2016, alineatul (2) se modifică și va avea următorul "
        "cuprins: «Autoritatea publică anunțul de participare.»"
    )
    r = raza_de_impact(
        d,
        citari_fn=_citari({}),
        text_original=lambda act, loc: _ORIGINAL_CU_RAPORT,
    )
    assert any(o["termen_zile"] == 30 for o in r["obligatii_eliminate"])
    # a removed accountability duty pushes the reach up
    assert r["scor"]["raza"] >= 5


def test_a_repeal_removes_every_obligation_the_provision_held():
    d = "Articolul 5 din Legea nr. 98/2016 se abrogă."
    r = raza_de_impact(d, citari_fn=_citari({}), text_original=lambda act, loc: _ORIGINAL_CU_RAPORT)
    assert any(o["termen_zile"] == 30 for o in r["obligatii_eliminate"])


def test_a_kept_obligation_is_not_reported_removed():
    # the new text carries the reporting duty forward verbatim — nothing was dropped
    d = (
        "La articolul 5 din Legea nr. 98/2016, alineatul (2) se modifică și va avea următorul "
        "cuprins: «Autoritatea transmite raportul în termen de 30 de zile de la încheiere.»"
    )
    r = raza_de_impact(d, citari_fn=_citari({}), text_original=lambda act, loc: _ORIGINAL_CU_RAPORT)
    assert r["obligatii_eliminate"] == []


def test_without_the_original_text_no_removals_are_claimed():
    d = "Articolul 5 din Legea nr. 98/2016 se abrogă."
    r = raza_de_impact(d, citari_fn=_citari({}))
    assert r["obligatii_eliminate"] == []


def test_new_obligations_in_the_payload_are_listed():
    d = (
        "La articolul 5 din Legea nr. 98/2016, se introduce alineatul (3) cu următorul cuprins: "
        "«(3) Autoritatea publică raportul în termen de 30 de zile de la încheiere.»"
    )
    r = raza_de_impact(d, citari_fn=_citari({"lege-98-2016": (2, 1)}))
    assert any(o["termen_zile"] == 30 for o in r["obligatii_noi"])
