from __future__ import annotations

from pathlib import Path

from scripts import cellar, depozit
from scripts.acoperire_ue import raport


def _act_cu_referinte(cale: Path) -> None:
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
            " id_portal, id_act_portal, sursa_url, citit_la)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "lege-1-2024",
                "lege-1-2024",
                "lege",
                "1",
                2024,
                "Lege privind aplicarea Regulamentului (UE) 2018/1805",
                "Parlamentul",
                "2024-01-01",
                "1",
                "1",
                "",
                "2024-01-01",
            ),
        )
        con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?,?,?,?)",
            (
                "lege-1-2024",
                "art1",
                1,
                "Potrivit Regulamentului (UE) 2018/1805 și Directivei 2014/24/UE, "
                "autoritățile transmit datele.",
            ),
        )


def _initiativa_cu_referinta(cale: Path) -> None:
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO initiative (plx_id, cam, idp, senat_id, tip, titlu, obiect, urgenta,"
            " stadiu, camera_decizionala, data_inreg, sursa_url, citit_la)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "plx-10-2025",
                2,
                "10",
                "L10/2025",
                "proiect de lege",
                "Lege pentru punerea în aplicare a Regulation (EU) 2016/679",
                "măsuri de aplicare GDPR",
                0,
                "în lucru",
                "Camera Deputaților",
                "2025-01-01",
                "https://cdep.ro/plx10",
                "2025-01-02",
            ),
        )


def _eu_importat(cale: Path) -> None:
    m = cellar.ManifestareUE(
        celex="32018R1805",
        work_uri="http://publications.europa.eu/resource/cellar/work",
        expression_uri="http://publications.europa.eu/resource/cellar/work.0020",
        manifestation_uri="http://publications.europa.eu/resource/cellar/work.0020.xhtml",
        limba="RON",
        format="xhtml",
        item_url="https://cellar/ron.xhtml",
        titlu="Română",
        data_document="2018-11-14",
        tip_uri="http://publications.europa.eu/type/regulation",
        in_vigoare=True,
    )
    with cellar.deschide(str(cale)) as con:
        cellar.scrie_celex(
            con, "32018R1805", [m], m, "REGULAMENTUL (UE) 2018/1805\nArticolul 1\nText."
        )


def test_raport_acoperire_ue_grupeaza_importate_si_lipsa(tmp_path):
    corpus, initiative, eu = tmp_path / "corpus.db", tmp_path / "initiative.db", tmp_path / "eu.db"
    _act_cu_referinte(corpus)
    _initiativa_cu_referinta(initiative)
    _eu_importat(eu)

    out = raport(corpus, initiative, eu, limita=10)
    rows = {r["celex"]: r for r in out["referinte"]}

    assert out["total"] == 3
    assert out["importate"] == 1
    assert out["neimportate"] == 2
    assert rows["32018R1805"]["importat"] is True
    assert rows["32014L0024"]["importat"] is False
    assert rows["32016R0679"]["surse"] == {"initiative": 1}
    assert out["surse"]["corpus"]["documente"] == 1
    assert out["surse"]["initiative"]["mentionari"] == 1
