from scripts.triage_ue import (
    aplica_triere,
    aplica_triere_lipsa,
    semnale_draft,
    triere_rezultat,
)


def test_triere_rezultat_distinge_referinta_de_materie():
    exact = triere_rezultat({"potrivire": "referinta"})
    text = triere_rezultat({"potrivire": "text"})

    assert exact["nivel"] == "referinta"
    assert exact["eticheta"] == "referință UE citată"
    assert text["nivel"] == "materie"
    assert text["eticheta"] == "aceeași materie"


def test_triere_lipsa_marcheaza_celex_neimportat():
    refs = [{"celex": "32014L0024", "text": "Directiva 2014/24/UE"}]

    aplica_triere_lipsa(refs)

    assert refs[0]["triere"]["nivel"] == "neimportat"
    assert "32014L0024" in refs[0]["triere"]["explicatie"]


def test_semnale_draft_detecteaza_derogare_fara_verdict():
    refs = [{"celex": "32018R1805"}, {"celex": "32014L0024"}]

    semnale = semnale_draft("Prin excepție de la Directiva 2014/24/UE, nu se aplică art. 7.", refs)

    assert semnale == [
        {
            "nivel": "posibila_derogare",
            "eticheta": "posibilă derogare de la drept UE",
            "explicatie": (
                "Textul folosește formulări de derogare sau excepție; verifică manual actele UE "
                "citate ori candidate."
            ),
            "expresii": ["nu se aplică", "excepție de la"],
            "referinte": ["32014L0024", "32018R1805"],
        }
    ]


def test_semnale_draft_ramane_tacut_fara_derogare():
    assert semnale_draft("Se aplică Directiva 2014/24/UE.", [{"celex": "32014L0024"}]) == []


def test_aplica_triere_ataseaza_etichete_pe_randuri():
    randuri = [{"potrivire": "referinta"}, {"potrivire": "text"}]

    assert aplica_triere(randuri) is randuri
    assert [r["triere"]["nivel"] for r in randuri] == ["referinta", "materie"]
