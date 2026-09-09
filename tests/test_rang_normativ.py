from scripts import rang_normativ


def test_rang_normativ_eticheteaza_ierarhia_pe_tip():
    assert rang_normativ.info("lege") == {
        "tip": "lege",
        "rang": 1,
        "categorie": "primar",
        "eticheta": "rang primar",
        "nota": "organic/ordinar neprecizat în corpus",
    }
    assert rang_normativ.info("hg") == {
        "tip": "hg",
        "rang": 3,
        "categorie": "secundar",
        "eticheta": "rang secundar",
    }
    assert rang_normativ.info("ordin")["categorie"] == "administrativ"
    assert rang_normativ.info("necunoscut")["categorie"] == "necunoscut"


def test_rang_normativ_verifica_daca_un_tip_poate_modifica_altul():
    assert rang_normativ.poate_modifica("oug", "lege") is True
    assert rang_normativ.poate_modifica("hg", "lege") is False
    assert rang_normativ.poate_modifica("ordin", "hg") is False
    assert rang_normativ.poate_modifica("lege", "ordin") is True
