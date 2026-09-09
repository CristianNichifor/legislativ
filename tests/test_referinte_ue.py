from scripts.referinte_ue import referinte_dict


def test_parseaza_regulament_ue_an_numar():
    refs = referinte_dict("Potrivit Regulamentului (UE) 2018/1805, măsura se execută.")

    assert refs == [
        {
            "celex": "32018R1805",
            "fel": "regulament",
            "an": 2018,
            "numar": "1805",
            "text": "Regulamentului (UE) 2018/1805",
            "start": 9,
            "end": 38,
            "sursa": "citare",
        }
    ]


def test_parseaza_regulament_ce_numar_an():
    refs = referinte_dict("Se aplică Regulamentul (CE) nr. 261/2004.")

    assert refs[0]["celex"] == "32004R0261"
    assert refs[0]["fel"] == "regulament"
    assert refs[0]["an"] == 2004
    assert refs[0]["numar"] == "261"


def test_parseaza_directiva_cu_an_scurt_si_marker_la_final():
    refs = referinte_dict("Trimiterea este la Directiva 89/665/CEE.")

    assert refs[0]["celex"] == "31989L0665"
    assert refs[0]["fel"] == "directiva"


def test_parseaza_decizie_si_url_celex():
    refs = referinte_dict(
        "A se vedea Decizia (UE) 2022/1925 și "
        "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32018R1805."
    )

    assert [r["celex"] for r in refs] == ["32022D1925", "32018R1805"]
    assert refs[1]["sursa"] == "celex"


def test_parseaza_citare_ue_in_engleza():
    refs = referinte_dict("See Regulation (EU) 2016/679.")

    assert refs[0]["celex"] == "32016R0679"
    assert refs[0]["fel"] == "regulament"


def test_ignora_citari_nationale_fara_marker_ue():
    refs = referinte_dict("Legea nr. 98/2016 și Hotărârea nr. 1/2024 nu sunt acte UE.")

    assert refs == []
