"""Tests for the deterministic legislative matrix.

The matrix is not a subject classifier. It groups what the corpus can verify: issuing body,
instrument type and risk signals from already-built reports, the graph and live initiative targets.
"""

from __future__ import annotations

from pathlib import Path

from scripts import depozit
from scripts.cdep import Initiativa
from scripts.graf import _deschide_graf
from scripts.servicii import Stare, _matrice

EDGE_SQL = (
    "INSERT INTO muchii (din_act, din_locator, catre_act, locator, fel, incredere, de_la)"
    " VALUES (?,?,?,?,?,?,?)"
)


def _act(con, act_id, tip, numar, an, emitent, titlu="T"):
    con.execute(
        "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
        " id_portal, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            act_id,
            f"{tip}-{numar}-{an}",
            tip,
            numar,
            an,
            titlu,
            emitent,
            f"{an}-01-01",
            act_id,
            "x",
        ),
    )


def _ini(plx_id: str, stadiu: str = "pe ordinea de zi") -> Initiativa:
    return Initiativa(
        plx_id=plx_id,
        cam=2,
        idp=plx_id,
        senat_id=None,
        tip="propunere legislativa",
        titlu="Lege pentru modificarea Legii nr. 98/2016",
        obiect="modificarea articolului 7 din Legea nr. 98/2016",
        urgenta=False,
        stadiu=stadiu,
        camera_decizionala="Camera Deputaților",
        data_inreg="2024-01-01",
        sursa_url="",
    )


def _stare(tmp_path: Path, *, graf: bool = False, initiative: bool = False) -> Stare:
    corpus = tmp_path / "corpus.db"
    initiative_db = tmp_path / "initiative.db"
    graf_db = tmp_path / "graf.db"
    with depozit.deschide(corpus) as con:
        _act(
            con,
            "lege-98-2016",
            "lege",
            "98",
            2016,
            "Parlamentul",
            "Lege privind achizițiile publice",
        )
        _act(con, "hg-1-2017", "hg", "1", 2017, "Guvernul", "Hotărâre privind educația")
        con.commit()
    with depozit.deschide(initiative_db) as con:
        if initiative:
            depozit.scrie_initiativa(con, _ini("plx-1-2024"))
            depozit.scrie_initiativa(con, _ini("plx-dead-2024", stadiu="respins definitiv"))
            con.execute(
                "INSERT INTO initiative_tinta (plx_id, act_id, locator) VALUES (?,?,?)",
                ("plx-1-2024", "lege-98-2016", "art7"),
            )
            con.execute(
                "INSERT INTO initiative_tinta (plx_id, act_id, locator) VALUES (?,?,?)",
                ("plx-dead-2024", "lege-98-2016", "art8"),
            )
        con.commit()
    if graf:
        con = _deschide_graf(str(graf_db))
        try:
            con.execute(
                EDGE_SQL,
                (
                    "oug-1-2020",
                    "art1",
                    "lege-98-2016",
                    "art7",
                    "modifica",
                    "verbatim",
                    "2020-01-01",
                ),
            )
            con.execute(
                EDGE_SQL,
                (
                    "oug-2-2021",
                    "art2",
                    "lege-98-2016",
                    "art8",
                    "abroga",
                    "verbatim",
                    "2021-01-01",
                ),
            )
            con.execute(
                EDGE_SQL,
                (
                    "ordin-1-2022",
                    "art1",
                    "lege-98-2016",
                    "art9",
                    "refera",
                    "verbatim",
                    "2022-01-01",
                ),
            )
            con.commit()
        finally:
            con.close()
    return Stare(str(corpus), str(initiative_db), str(graf_db))


def test_matrix_groups_gap_reports_by_issuer(tmp_path):
    stare = _stare(tmp_path)
    stare.vid = [
        {
            "act_id": "lege-98-2016",
            "locator": "art7",
            "text": "Guvernul aprobă normele metodologice.",
            "instrument": "hg",
            "scadenta": "2016-06-25",
            "zile_intarziere": 100,
            "severitate": "blocking",
        }
    ]
    stare.neconstitutional = [
        {
            "act_id": "lege-98-2016",
            "locator": "art5.alin7",
            "text": "Normă lovită și nereparată.",
            "decizie": "decizie-9-1994",
            "termen": "1995-01-09",
            "zile_de_la_termen": 50,
            "severitate": "blocking",
        }
    ]

    out = _matrice({}, stare)

    rand = next(r for r in out["randuri"] if r["emitent"] == "Parlamentul")
    assert rand["semnale"]["viduri"] == 1
    assert rand["semnale"]["neconstitutionale"] == 1
    assert rand["nivel"] == "blocking"
    assert rand["ranguri"] == [
        {
            "categorie": "primar",
            "eticheta": "rang primar",
            "rang": 1,
            "acte": 1,
            "note": ["organic/ordinar neprecizat în corpus"],
        }
    ]
    assert rand["exemple"]["viduri"][0]["act_id"] == "lege-98-2016"
    assert rand["exemple"]["viduri"][0]["actiuni"] == [
        {
            "fel": "prevedere",
            "eticheta": "vezi prevederea",
            "act_id": "lege-98-2016",
            "locator": "art7",
        }
    ]
    assert rand["exemple"]["neconstitutionale"][0]["actiuni"][0] == {
        "fel": "prevedere",
        "eticheta": "vezi prevederea",
        "act_id": "lege-98-2016",
        "locator": "art5.alin7",
    }
    assert out["limitari"]


def test_matrix_type_filter_applies_to_counts_and_report_rows(tmp_path):
    stare = _stare(tmp_path)
    stare.vid = [{"act_id": "lege-98-2016", "severitate": "blocking"}]

    out = _matrice({"tip": ["hg"]}, stare)

    assert [r["emitent"] for r in out["randuri"]] == ["Guvernul"]
    assert out["rezumat"]["acte"] == 1
    assert out["rezumat"]["viduri"] == 0
    assert out["randuri"][0]["tipuri"] == [{"tip": "hg", "acte": 1}]
    assert out["randuri"][0]["ranguri"][0]["categorie"] == "secundar"


def test_matrix_rank_filter_applies_to_counts_and_report_rows(tmp_path):
    stare = _stare(tmp_path)
    stare.vid = [{"act_id": "lege-98-2016", "severitate": "blocking"}]

    out = _matrice({"rang": ["primar"]}, stare)

    assert out["rang"] == "primar"
    assert [r["emitent"] for r in out["randuri"]] == ["Parlamentul"]
    assert out["rezumat"]["acte"] == 1
    assert out["rezumat"]["viduri"] == 1
    assert out["rezumat"]["ranguri"][0]["categorie"] == "primar"

    out = _matrice({"rang": ["secundar"]}, stare)

    assert [r["emitent"] for r in out["randuri"]] == ["Guvernul"]
    assert out["rezumat"]["viduri"] == 0


def test_matrix_domain_filter_applies_to_counts_and_report_rows(tmp_path):
    stare = _stare(tmp_path)
    stare.vid = [{"act_id": "lege-98-2016", "severitate": "blocking"}]

    out = _matrice({"domeniu": ["achizitii-publice"]}, stare)

    assert out["domeniu"] == "achizitii-publice"
    assert [r["emitent"] for r in out["randuri"]] == ["Parlamentul"]
    assert out["rezumat"]["acte"] == 1
    assert out["rezumat"]["viduri"] == 1
    assert out["randuri"][0]["domeniu"]["eticheta"] == "achiziții publice"
    assert out["randuri"][0]["domeniu_exemple"][0]["dovezi"] == ["titlu: achizițiile publice"]

    out = _matrice({"domeniu": ["educatie"]}, stare)

    assert [r["emitent"] for r in out["randuri"]] == ["Guvernul"]
    assert out["rezumat"]["viduri"] == 0


def test_matrix_counts_amendment_pressure_and_live_initiatives(tmp_path):
    stare = _stare(tmp_path, graf=True, initiative=True)

    out = _matrice({"sort": ["amendamente"]}, stare)

    rand = next(r for r in out["randuri"] if r["emitent"] == "Parlamentul")
    assert rand["semnale"]["amendamente_primite"] == 2
    assert rand["semnale"]["acte_amendate"] == 1
    assert rand["semnale"]["initiative_in_lucru"] == 1


def test_matrix_ignores_missing_optional_graph_tables(tmp_path):
    corpus = tmp_path / "corpus.db"
    initiative_db = tmp_path / "initiative.db"
    graf_db = tmp_path / "not-a-graph.db"
    with depozit.deschide(corpus) as con:
        _act(con, "lege-98-2016", "lege", "98", 2016, "Parlamentul")
        con.commit()
    with depozit.deschide(initiative_db):
        pass
    graf_db.write_text("", encoding="utf-8")

    out = _matrice({}, Stare(str(corpus), str(initiative_db), str(graf_db)))

    assert out["rezumat"]["amendamente_primite"] == 0
