"""Tests for the deterministic legislative matrix.

The matrix is not a subject classifier. It groups what the corpus can verify: issuing body,
instrument type and risk signals from already-built reports, the graph and live initiative targets.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import depozit
from scripts.cdep import Initiativa
from scripts.graf import _deschide_graf
from scripts.servicii import (
    Stare,
    _fisa_act,
    _matrice,
    _matrice_acte,
    _matrice_contradictii,
    _matrice_dosar,
    _matrice_graf,
    _supraveghere,
)

EDGE_SQL = (
    "INSERT INTO muchii (din_act, din_locator, catre_act, locator, fel, incredere, de_la)"
    " VALUES (?,?,?,?,?,?,?)"
)


def test_contradictii_definitions_evidence_filters_and_dossier(tmp_path):
    stare = _stare(tmp_path)
    with depozit.deschide(stare.corpus) as con:
        _act(con, "lege-2-2020", "lege", "2", 2020, "Parlamentul", "Achiziții publice")
        for act, text in [
            ("lege-98-2016", "Prin furnizor se înțelege persoana fizică"),
            ("lege-2-2020", "Prin furnizor se înțelege persoana juridică"),
            ("hg-1-2017", "Prin furnizor se înțelege orice instituție"),
        ]:
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, 'art1', 1, ?)",
                (act, text),
            )
        con.commit()
    qs = {"emitent": ["Parlamentul"]}
    out = _matrice_contradictii(qs, stare)
    assert len(out["candidati"]) == 1
    c = out["candidati"][0]
    assert c["status"] == "candidat_neconfirmat"
    assert {c["a"]["act_id"], c["b"]["act_id"]} == {"lege-98-2016", "lege-2-2020"}
    assert c["a"]["locator"] == "art1"
    assert c["a"]["actiuni"]
    assert not out["trunchiat"]
    assert not _matrice_contradictii({**qs, "tip": ["hg"]}, stare)["candidati"]
    assert not _matrice_contradictii({}, stare)["candidati"]
    dosar = _matrice_dosar(qs, stare)
    assert dosar["contradictii"]["candidati"] == out["candidati"]
    assert "persoana juridică" in dosar["markdown"]
    assert "art1" in dosar["markdown"]


def test_contradictii_skip_equal_unknown_and_same_act(tmp_path):
    stare = _stare(tmp_path)
    with depozit.deschide(stare.corpus) as con:
        _act(con, "lege-2-2020", "lege", "2", 2020, "Parlamentul", "Achiziții publice")
        _act(con, "lege-3-2020", "lege", "3", 2020, "Parlamentul", "Titlu necunoscut")
        for act, ordine, text in [
            ("lege-98-2016", 1, "Prin furnizor se înțelege persoana fizică"),
            ("lege-2-2020", 1, "Prin furnizor se înțelege PERSOANA FIZICA"),
            ("lege-3-2020", 1, "Prin furnizor se înțelege orice instituție"),
            ("lege-98-2016", 2, "Prin beneficiar se înțelege persoana fizică"),
            ("lege-98-2016", 3, "Prin beneficiar se înțelege persoana juridică"),
        ]:
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, ?, ?, ?)",
                (act, f"art{ordine}", ordine, text),
            )
        con.commit()
    assert not _matrice_contradictii({"emitent": ["Parlamentul"]}, stare)["candidati"]


def test_contradictii_marks_limit_and_different_domains(tmp_path):
    stare = _stare(tmp_path)
    with depozit.deschide(stare.corpus) as con:
        for i, titlu in [(2, "Achiziții publice"), (3, "Achiziții publice"), (4, "Educația")]:
            act = f"lege-{i}-2020"
            _act(con, act, "lege", str(i), 2020, "Parlamentul", titlu)
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, 'art1', 1, ?)",
                (act, f"Prin furnizor se înțelege categoria numărul {i}"),
            )
        con.commit()
    qs = {"emitent": ["Parlamentul"], "limita": ["1"]}
    out = _matrice_contradictii(qs, stare)
    assert len(out["candidati"]) == 1
    assert not out["trunchiat"]
    with depozit.deschide(stare.corpus) as con:
        con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, 'art1', 1, ?)",
            ("lege-98-2016", "Prin furnizor se înțelege toate persoanele"),
        )
        con.commit()
    assert _matrice_contradictii(qs, stare)["trunchiat"]


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


def test_deadline_candidates_share_matrix_filters_limits_and_export(tmp_path):
    stare = _stare(tmp_path)
    texte = [
        "Autoritatea contractantă comunică decizia în termen de 30 zile de la primirea cererii.",
        "Autoritatea contractantă comunică decizia în termen de 60 zile de la primirea cererii.",
        "Autoritatea contractantă comunică decizia în termen de 90 zile de la primirea cererii.",
    ]
    with depozit.deschide(stare.corpus) as con:
        for i, text in enumerate(texte, 2):
            act_id = f"lege-{i}-2020"
            _act(con, act_id, "lege", str(i), 2020, "Parlamentul", "Achiziții publice")
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, 'art1', 1, ?)",
                (act_id, text),
            )
        con.commit()
    qs = {"emitent": ["Parlamentul"]}
    out = _matrice_contradictii(qs, stare)
    assert len(out["candidati"]) == 3
    assert out["termene_analizate"] == 3
    for c in out["candidati"]:
        assert c["tip"] == "termen_divergent"
        assert c["status"] == "candidat_neconfirmat"
        assert c["verificari"]
        assert c["a"]["text"] in texte and c["b"]["text"] in texte
        assert c["a"]["act_id"] != c["b"]["act_id"]
        assert c["a"]["actiuni"][0]["locator"] == "art1"
    partial = _matrice_contradictii({**qs, "limita": ["1"]}, stare)
    assert partial["trunchiat"] and len(partial["candidati"]) == 1
    assert not _matrice_contradictii({**qs, "tip": ["hg"]}, stare)["candidati"]
    assert not _matrice_contradictii({**qs, "domeniu": ["educatie"]}, stare)["candidati"]
    dosar = _matrice_dosar(qs, stare)
    assert dosar["contradictii"]["candidati"] == out["candidati"]
    assert texte[0] in dosar["markdown"]
    assert "Termen: în termen de 60 zile" in dosar["markdown"]
    assert "Verifică sfera" in dosar["markdown"]


def test_deadline_candidates_exclude_same_act_unknown_and_other_domain(tmp_path):
    stare = _stare(tmp_path)
    with depozit.deschide(stare.corpus) as con:
        for act_id, titlu in [("lege-2-2020", "Educația"), ("lege-3-2020", "Alte reguli")]:
            _act(con, act_id, "lege", "2", 2020, "Parlamentul", titlu)
        for i, act_id in enumerate(
            ["lege-98-2016", "lege-98-2016", "lege-2-2020", "lege-3-2020"], 1
        ):
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, ?, ?, ?)",
                (
                    act_id,
                    f"art{i}",
                    i,
                    "Autoritatea contractantă comunică decizia în termen de "
                    f"{i * 30} zile de la primirea cererii.",
                ),
            )
        con.commit()
    assert not _matrice_contradictii({"emitent": ["Parlamentul"]}, stare)["candidati"]


def test_authority_overlaps_evidence_dossier_and_shared_limit(tmp_path):
    stare = _stare(tmp_path)
    with depozit.deschide(stare.corpus) as con:
        for i, autoritate in enumerate(
            ["Ministerul Mediului", "Agenția Națională pentru Mediu", "Oficiul pentru Mediu"], 2
        ):
            act_id = f"lege-{i}-2020"
            _act(con, act_id, "lege", str(i), 2020, "Parlamentul", "Achiziții publice")
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, 'art1', 1, ?)",
                (act_id, f"{autoritate} emite autorizațiile de mediu."),
            )
        con.commit()
    qs = {"emitent": ["Parlamentul"]}
    out = _matrice_contradictii(qs, stare)
    assert out["atributii_analizate"] == 3
    assert len(out["candidati"]) == 3
    for c in out["candidati"]:
        assert c["tip"] == "competenta_suprapusa"
        assert c["status"] == "candidat_neconfirmat"
        assert c["a"]["autoritate"] != c["b"]["autoritate"]
        assert c["a"]["actiuni"][0]["locator"] == "art1"
        assert c["verificari"]
    partial = _matrice_contradictii({**qs, "limita": ["1"]}, stare)
    assert partial["trunchiat"] and len(partial["candidati"]) == 1
    assert not _matrice_contradictii({**qs, "tip": ["hg"]}, stare)["candidati"]
    dosar = _matrice_dosar(qs, stare)
    assert dosar["contradictii"]["candidati"] == out["candidati"]
    assert "Autoritate: ministerul mediului" in dosar["markdown"]
    assert "Ministerul Mediului emite autorizațiile de mediu." in dosar["markdown"]


def test_authority_overlaps_exclude_same_authority_act_and_other_domains(tmp_path):
    stare = _stare(tmp_path)
    with depozit.deschide(stare.corpus) as con:
        for i, titlu in [(2, "Achiziții publice"), (3, "Educația"), (4, "Alte reguli")]:
            _act(con, f"lege-{i}-2020", "lege", str(i), 2020, "Parlamentul", titlu)
        for act, ord, autoritate, obiect in [
            ("lege-98-2016", 1, "Ministerul Mediului", "autorizațiile de mediu"),
            ("lege-2-2020", 1, "Ministerul Mediului", "autorizațiile de mediu"),
            ("lege-3-2020", 1, "Ministerul Economiei", "autorizațiile de mediu"),
            ("lege-4-2020", 1, "Ministerul Economiei", "autorizațiile de mediu"),
            ("lege-98-2016", 2, "Ministerul Mediului", "licențele pentru instalații"),
            ("lege-98-2016", 3, "Ministerul Economiei", "licențele pentru instalații"),
        ]:
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?, ?, ?, ?)",
                (act, f"art{ord}", ord, f"{autoritate} emite {obiect}."),
            )
        con.commit()
    assert not _matrice_contradictii({"emitent": ["Parlamentul"]}, stare)["candidati"]


def test_draft_comparison_validates_metadata_and_exports_evidence(tmp_path, monkeypatch):
    from scripts.servicii import _conflicte_proiecte, _matrice_proiecte

    stare = _stare(tmp_path)
    with depozit.deschide(stare.initiative) as con:
        for id, status in [
            ("plx-a", "pe ordinea de zi"),
            ("plx-b", "raport depus"),
            ("plx-rejected", "respins definitiv"),
            ("plx-withdrawn", "retras"),
            ("plx-unknown", "necunoscut"),
            ("plx-empty", " "),
        ]:
            depozit.scrie_initiativa(con, _ini(id, status))
            con.execute(
                "INSERT INTO initiative_tinta VALUES (?, ?, ?)", (id, "lege-98-2016", "art7")
            )
        con.commit()
    qs = {"emitent": ["Parlamentul"]}
    assert {i["plx_id"] for i in _matrice_proiecte(qs, stare)["initiative"]} == {"plx-a", "plx-b"}
    req = {
        "emitent": "Parlamentul",
        "plx_a": "plx-a",
        "plx_b": "plx-b",
        "text_a": "Articolul 7 din Legea nr. 98/2016 se abrogă.",
        "text_b": "Articolul 7 din Legea nr. 98/2016 se modifică și va avea "
        + 'următorul cuprins: "Text nou."',
    }
    out = _conflicte_proiecte(req, stare)
    assert out["gasit"]
    c = out["conflicte_proiecte"]["candidati"][0]
    assert c["tip"] == "abrogare_modificare"
    assert c["a"]["act_id"] == "plx-a" and c["b"]["stadiu"] == "raport depus"
    assert c["tinta"]["actiuni"]
    assert "plx-a" in out["markdown"] and "Text nou." in out["markdown"]
    for changes in [
        {"plx_b": "plx-rejected"},
        {"plx_b": "plx-withdrawn"},
        {"plx_b": "plx-unknown"},
        {"plx_b": "plx-empty"},
        {"plx_b": "plx-a"},
        {"emitent": "Guvernul"},
        {"text_a": "x" * 60001},
        {"text_a": []},
    ]:
        assert "error" in _conflicte_proiecte({**req, **changes}, stare)
    assert "error" in _conflicte_proiecte([], stare)
    from scripts import documente_proiecte as dp
    from scripts.fisiere import catre_docx

    url = "https://www.cdep.ro/proiecte/test.docx"
    monkeypatch.setattr(dp, "lista", lambda *args: {"documente": [{"url": url, "label": "Draft"}]})
    monkeypatch.setattr(dp, "descarca", lambda *args: catre_docx("", req["text_a"]))
    doc = dp.importa(stare, "plx-a", url)
    imported = _conflicte_proiecte({**req, "text_a": "tampered", "versiune_a": doc["id"]}, stare)
    assert imported["conflicte_proiecte"]["candidati"][0]["a"]["text"] == req["text_a"]
    assert doc["sha256"] in imported["markdown"]
    assert "error" in _conflicte_proiecte({**req, "versiune_b": doc["id"]}, stare)
    with sqlite3.connect(dp.cale_store(stare)) as con:
        con.execute("UPDATE documente SET status='ocr_necesar'")
    assert "error" in _conflicte_proiecte({**req, "versiune_a": doc["id"]}, stare)


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


def test_watch_state_exposes_project_targets_and_source_status(tmp_path):
    stare = _stare(tmp_path, graf=True, initiative=True)
    with depozit.deschide(stare.initiative) as con:
        depozit.scrie_initiativa(con, _ini("plx-2-2024", stadiu="raport depus"))
        con.execute(
            "INSERT INTO initiative_tinta (plx_id, act_id, locator) VALUES (?,?,?)",
            ("plx-2-2024", "lege-98-2016", "art9"),
        )
    out = _supraveghere("lege-98-2016", stare)

    assert out["initiative_status"] == "ok"
    assert out["citari"] == 3
    assert out["amendat"] == 2
    assert {i["plx_id"] for i in out["initiative"]} == {"plx-1-2024", "plx-2-2024"}
    first = next(i for i in out["initiative"] if i["plx_id"] == "plx-1-2024")
    assert first["locatoare"] == ["art7"]
    assert first["tinte"] == 1
    assert first["lifecycle"]["key"] == "plenary_scheduled"

    absent_dir = tmp_path / "absent"
    absent_dir.mkdir()
    absent = _stare(absent_dir)
    Path(absent.initiative).unlink()
    missing = _supraveghere("lege-98-2016", absent)
    assert missing["initiative_status"] == "surse_indisponibile"
    assert missing["initiative"] == []


def test_law_workbench_collects_act_scoped_next_actions(tmp_path):
    stare = _stare(tmp_path, graf=True, initiative=True)
    with depozit.deschide(stare.corpus) as con:
        con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?,?,?,?)",
            (
                "lege-98-2016",
                "art7",
                1,
                "Se aplică Directiva 2014/24/UE privind achizițiile publice.",
            ),
        )
        con.commit()
    stare.vid = [
        {
            "act_id": "lege-98-2016",
            "locator": "art7",
            "text": "Guvernul aprobă normele metodologice.",
            "instrument": "hg",
            "severitate": "blocking",
        }
    ]
    stare.neconstitutional = [
        {
            "act_id": "lege-98-2016",
            "locator": "art5.alin7",
            "text": "Normă lovită și nereparată.",
            "decizie": "decizie-9-1994",
            "severitate": "blocking",
        }
    ]

    out = _fisa_act({"act": ["lege-98-2016"]}, stare)

    assert out["gasit"] is True
    assert out["act_id"] == "lege-98-2016"
    assert out["tip_dosar"] == "fisa-act"
    assert out["rand"]["exemple"]["viduri"][0]["act_id"] == "lege-98-2016"
    assert "# Fișă de lucru: lege-98-2016" in out["markdown"]
    assert out["viduri"][0]["actiuni"][0]["eticheta"] == "vezi prevederea"
    assert out["neconstitutionale"][0]["decizie"] == "decizie-9-1994"
    assert out["initiative"][0]["plx_id"] == "plx-1-2024"
    assert out["initiative"][0]["lifecycle"]["known"] is True
    assert out["referinte_ue"][0]["celex"] == "32014L0024"
    assert any("nu este verdict juridic" in x for x in out["limitari"])
    assert any("compară proiectele pendinte" in x for x in out["pasi"])


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


def test_matrix_source_acts_use_the_same_filters(tmp_path):
    stare = _stare(tmp_path)

    out = _matrice_acte(
        {"emitent": ["Parlamentul"], "domeniu": ["achizitii-publice"], "rang": ["primar"]},
        stare,
    )

    assert out["total"] == 1
    assert out["acte"][0]["cheie_citare"] == "lege-98-2016"
    assert out["acte"][0]["rang"]["categorie"] == "primar"
    assert out["acte"][0]["domeniu"]["cheie"] == "achizitii-publice"
    assert out["acte"][0]["domeniu"]["dovezi"] == ["titlu: achizițiile publice"]

    assert _matrice_acte({"emitent": ["Parlamentul"], "domeniu": ["educatie"]}, stare)["total"] == 0
    assert _matrice_acte({"emitent": ["Guvernul"], "rang": ["primar"]}, stare)["total"] == 0


def test_matrix_graph_scaffold_exposes_candidate_edges_and_source_state(tmp_path):
    stare = _stare(tmp_path, graf=True)
    from scripts import source_registry

    lege = source_registry.executa(
        stare,
        {
            "family": "legislatie_ro",
            "identifier": "lege-98-2016",
            "url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
        },
    )
    source_registry.executa(stare, {"action": "queue", "id": lege["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": lege["id"],
            "state": "unavailable",
            "error_category": "source_unavailable",
        },
    )

    out = _matrice_graf({"emitent": ["Parlamentul"], "domeniu": ["achizitii-publice"]}, stare)

    assert out["contract"] == "matrice-graf-v1"
    assert out["status"] == "scaffold_neconfirmat"
    assert out["graph_state"] == "ok"
    assert out["acte_selectate"] == 1
    assert out["nodes"][0]["act_id"] == "lege-98-2016"
    assert out["nodes"][0]["source_quality"]["cheie"] == "reviewable"
    assert out["nodes"][0]["source_quality"]["legacy_cheie"] == "attention"
    assert out["nodes"][0]["source_quality"]["source_state"] == "unavailable"
    assert {e["fel"] for e in out["edges"]} == {"modifica", "abroga", "refera"}
    assert all(e["status"] == "relatie_candidata_neconfirmata" for e in out["edges"])
    assert out["edges"][0]["evidence"]["tip"] == "muchie_graf"
    assert out["edges"][0]["to"]["actiuni"]
    assert any("nu verdict juridic" in x for x in out["limitari"])

    fara_graf_dir = tmp_path / "fara_graf"
    fara_graf_dir.mkdir()
    fara_graf = _matrice_graf(
        {"emitent": ["Parlamentul"], "domeniu": ["achizitii-publice"]},
        _stare(fara_graf_dir),
    )
    assert fara_graf["graph_state"] == "indisponibil"
    assert fara_graf["edges"] == []


def test_matrix_exposes_source_quality_filter(tmp_path):
    stare = _stare(tmp_path)
    from scripts import source_registry

    lege = source_registry.executa(
        stare,
        {
            "family": "legislatie_ro",
            "identifier": "lege-98-2016",
            "url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
        },
    )
    source_registry.executa(stare, {"action": "queue", "id": lege["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": lege["id"],
            "state": "failed",
            "error_category": "fetch_failed",
        },
    )

    out = _matrice({}, stare)
    parlament = next(r for r in out["randuri"] if r["emitent"] == "Parlamentul")
    guvern = next(r for r in out["randuri"] if r["emitent"] == "Guvernul")

    assert parlament["source_quality"]["reviewable"] == 1
    assert parlament["source_quality"]["attention"] == 1
    assert guvern["source_quality"]["missing"] == 1
    assert out["rezumat"]["surse_revizuibile"] == 1
    assert out["rezumat"]["surse_atentie"] == 1
    assert out["rezumat"]["surse_lipsa"] == 1

    assert [
        r["emitent"] for r in _matrice({"source_quality": ["reviewable"]}, stare)["randuri"]
    ] == ["Parlamentul"]
    assert [
        r["emitent"] for r in _matrice({"source_quality": ["attention"]}, stare)["randuri"]
    ] == ["Parlamentul"]
    acte = _matrice_acte(
        {"emitent": ["Parlamentul"], "source_quality": ["reviewable"]},
        stare,
    )
    assert acte["total"] == 1
    assert acte["acte"][0]["source_quality"]["cheie"] == "reviewable"
    dosar = _matrice_dosar(
        {"emitent": ["Parlamentul"], "source_quality": ["reviewable"]},
        stare,
    )
    assert dosar["acte"]["total"] == 1
    assert dosar["acte"]["acte"][0]["source_quality"]["cheie"] == "reviewable"
    assert (
        _matrice_acte(
            {"emitent": ["Parlamentul"], "source_quality": ["missing"]},
            stare,
        )["acte"]
        == []
    )


def test_matrix_distinguishes_loaded_stale_partial_and_reviewable_sources(tmp_path):
    stare = _stare(tmp_path)
    from scripts import source_registry

    with depozit.deschide(stare.corpus) as con:
        _act(con, "lege-2-2020", "lege", "2", 2020, "Parlamentul", "Achiziții publice")
        _act(con, "lege-3-2020", "lege", "3", 2020, "Parlamentul", "Achiziții publice")
        _act(con, "lege-4-2020", "lege", "4", 2020, "Parlamentul", "Achiziții publice")
        con.commit()

    states = {
        "lege-98-2016": "fetched",
        "lege-2-2020": "changed",
        "lege-3-2020": "queued",
        "lege-4-2020": "needs_review",
    }
    for act_id, state in states.items():
        row = source_registry.executa(
            stare,
            {
                "family": "legislatie_ro",
                "identifier": act_id,
                "url": f"https://legislatie.just.ro/Public/DetaliiDocument/{act_id}",
            },
        )
        if state == "queued":
            source_registry.executa(stare, {"action": "queue", "id": row["id"]})
        elif state == "changed":
            source_registry.executa(stare, {"action": "queue", "id": row["id"]})
            source_registry.executa(
                stare,
                {
                    "action": "record",
                    "id": row["id"],
                    "state": "fetched",
                    "content_hash": "a" * 64,
                },
            )
            source_registry.executa(
                stare,
                {
                    "action": "record",
                    "id": row["id"],
                    "state": "changed",
                    "content_hash": "b" * 64,
                },
            )
        else:
            source_registry.executa(stare, {"action": "queue", "id": row["id"]})
            source_registry.executa(
                stare,
                {
                    "action": "record",
                    "id": row["id"],
                    "state": state,
                    "content_hash": "a" * 64,
                },
            )

    out = _matrice({"emitent": ["Parlamentul"]}, stare)
    rand = next(r for r in out["randuri"] if r["emitent"] == "Parlamentul")

    assert rand["source_quality"]["loaded"] == 1
    assert rand["source_quality"]["stale"] == 1
    assert rand["source_quality"]["partial"] == 1
    assert rand["source_quality"]["reviewable"] == 1
    assert rand["source_quality"]["current"] == 1
    assert rand["source_quality"]["queued"] == 1
    assert rand["source_quality"]["attention"] == 2
    assert out["rezumat"]["surse_incarcate"] == 1
    assert out["rezumat"]["surse_stale"] == 1
    assert out["rezumat"]["surse_partiale"] == 1
    assert out["rezumat"]["surse_revizuibile"] == 1

    assert _matrice({"source_quality": ["loaded"]}, stare)["randuri"][0]["emitent"] == "Parlamentul"
    assert _matrice({"source_quality": ["stale"]}, stare)["randuri"][0]["emitent"] == "Parlamentul"
    assert (
        _matrice({"source_quality": ["partial"]}, stare)["randuri"][0]["emitent"] == "Parlamentul"
    )
    assert (
        _matrice({"source_quality": ["reviewable"]}, stare)["randuri"][0]["emitent"]
        == "Parlamentul"
    )


def test_matrix_problem_filter_turns_rows_into_a_work_queue(tmp_path):
    stare = _stare(tmp_path, graf=True, initiative=True)
    stare.vid = [
        {
            "act_id": "lege-98-2016",
            "locator": "art7",
            "text": "Guvernul aprobă normele metodologice.",
            "instrument": "hg",
            "severitate": "blocking",
        }
    ]
    stare.neconstitutional = [
        {
            "act_id": "lege-98-2016",
            "locator": "art5.alin7",
            "text": "Normă lovită și nereparată.",
            "decizie": "decizie-9-1994",
            "severitate": "blocking",
        }
    ]

    out = _matrice({"problema": ["semnale"]}, stare)

    assert out["problema"] == "semnale"
    assert {p["cheie"] for p in out["probleme"]} >= {
        "viduri",
        "viduri_blocking",
        "neconstitutionale",
        "initiative",
        "amendamente",
    }
    assert [r["emitent"] for r in out["randuri"]] == ["Parlamentul"]

    for problema, camp, asteptat in [
        ("viduri", "viduri", 1),
        ("viduri_blocking", "viduri_blocking", 1),
        ("neconstitutionale", "neconstitutionale", 1),
        ("initiative", "initiative_in_lucru", 1),
        ("amendamente", "amendamente_primite", 2),
    ]:
        out = _matrice({"problema": [problema]}, stare)
        assert [r["emitent"] for r in out["randuri"]] == ["Parlamentul"]
        assert out["randuri"][0]["semnale"][camp] == asteptat

    fara_neconst = tmp_path / "fara_neconst"
    fara_neconst.mkdir()
    assert _matrice({"problema": ["neconstitutionale"]}, _stare(fara_neconst))["randuri"] == []


def test_matrix_workspace_summarizes_daily_work_queues(tmp_path):
    stare = _stare(tmp_path, graf=True, initiative=True)
    from scripts import dosare, note_manuale, source_registry, tracker_events

    dossier = dosare.creeaza(
        dosare.cale(stare),
        {"id": "a" * 32, "titlu": "Dosar achiziții", "intrebare": "", "domeniu": ""},
    )
    note_manuale.salveaza(
        dosare.cale(stare),
        {
            "id": "b" * 32,
            "dosar_id": dossier["id"],
            "revizie": 0,
            "title": "Lacună cu dovezi",
            "type": "lacuna",
            "act_id": "lege-98-2016",
            "locator": "art7",
            "evidence_quote": "Guvernul aprobă normele.",
            "source_url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
            "source_hash": "c" * 64,
            "reasoning": "Necesită verificare.",
            "status": "ready_for_review",
        },
    )
    lege = source_registry.executa(
        stare,
        {
            "family": "legislatie_ro",
            "identifier": "lege-98-2016",
            "url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
        },
    )
    source_registry.executa(stare, {"action": "queue", "id": lege["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": lege["id"],
            "state": "needs_review",
            "content_hash": "d" * 64,
        },
    )
    tracker_events.adauga(
        stare,
        {
            "event_type": "published_in_monitor",
            "project_id": "lege-98-2016",
            "source_family": "monitorul_oficial_pi",
            "source_id": "mo-390",
            "source_url": "https://monitoruloficial.ro/",
            "title": "Publicare MO",
            "occurred_at": "2016-05-23",
            "content_hash": "e" * 64,
            "payload": {"number": 390},
        },
    )

    out = _matrice(
        {
            "review_state": ["ready_for_review"],
            "source_family": ["monitorul_oficial_pi"],
            "lifecycle_state": ["published_monitor"],
        },
        stare,
    )

    workspace = out["workspace"]
    assert workspace["contract"] == "law-matrix-workspace-v1"
    assert workspace["not_legal_verdict"] is True
    assert workspace["active_filters"] == {
        "review_state": "ready_for_review",
        "source_family": "monitorul_oficial_pi",
        "lifecycle_state": "published_monitor",
    }
    assert workspace["summary"]["manual_notes"] == 1
    assert workspace["summary"]["tracker_events"] == 1
    assert workspace["summary"]["tracker_unreviewed"] == 1
    assert workspace["manual_notes"]["notes_by_type"] == {"lacuna": 1}
    assert workspace["tracker"]["by_type"] == {"published_in_monitor": 1}
    assert any(action["kind"] == "filter_tracker" for action in workspace["actions"])


def test_matrix_dossier_bundles_the_row_evidence(tmp_path):
    stare = _stare(tmp_path, graf=True, initiative=True)
    from scripts import source_registry

    lege = source_registry.executa(
        stare,
        {
            "family": "legislatie_ro",
            "identifier": "lege-98-2016",
            "url": "https://legislatie.just.ro/Public/DetaliiDocument/178667",
        },
    )
    source_registry.executa(stare, {"action": "queue", "id": lege["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": lege["id"],
            "state": "fetched",
            "content_hash": "a" * 64,
            "parser_version": "legislatie_ro.v1",
        },
    )
    with depozit.deschide(stare.corpus) as con:
        con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?,?,?,?)",
            (
                "lege-98-2016",
                "art7",
                1,
                "Se aplică Directiva 2014/24/UE privind achizițiile publice.",
            ),
        )
        con.commit()
    stare.vid = [
        {
            "act_id": "lege-98-2016",
            "locator": "art7",
            "text": "Guvernul aprobă normele metodologice.",
            "instrument": "hg",
            "severitate": "blocking",
        }
    ]
    stare.neconstitutional = [
        {
            "act_id": "lege-98-2016",
            "locator": "art5.alin7",
            "text": "Normă lovită și nereparată.",
            "decizie": "decizie-9-1994",
            "severitate": "blocking",
        }
    ]

    out = _matrice_dosar({"emitent": ["Parlamentul"], "problema": ["semnale"]}, stare)

    assert out["gasit"] is True
    assert out["emitent"] == "Parlamentul"
    assert out["problema"] == "semnale"
    assert out["rand"]["semnale"]["viduri"] == 1
    assert out["acte"]["total"] == 1
    assert out["acte"]["acte"][0]["act_id"] == "lege-98-2016"
    assert out["referinte_ue"][0]["celex"] == "32014L0024"
    assert out["proiecte"]["initiative"][0]["plx_id"] == "plx-1-2024"
    assert out["drilldown"]["contract"] == "matrice-drilldown-v1"
    assert out["drilldown"]["summary"]["prevederi"] == 2
    assert out["drilldown"]["summary"]["proiecte"] == 1
    assert out["drilldown"]["prevederi"][0]["kind"] == "lacuna"
    assert out["drilldown"]["prevederi"][1]["kind"] == "constitutionalitate"
    assert out["drilldown"]["proiecte"][0]["plx_id"] == "plx-1-2024"
    assert out["drilldown"]["referinte_ue"][0]["celex"] == "32014L0024"
    assert out["drilldown"]["surse"][0]["act_id"] == "lege-98-2016"
    workspace = out["drilldown"]["workspace"]
    assert workspace["contract"] == "law-matrix-workspace-row-v1"
    assert workspace["status"] == "reviewable_candidate"
    assert workspace["stage"] == "gata de lucru juridic"
    assert workspace["primary_problem"]["cheie"] == "lacuna"
    assert workspace["source_state"]["cheie"] == "source_backed"
    assert workspace["evidence_counts"]["prevederi"] == 2
    assert workspace["evidence_counts"]["referinte_ue"] == 1
    assert {a["kind"] for a in workspace["actions"]} >= {
        "create_note",
        "draft_amendment",
        "open_graph",
    }
    assert workspace["not_legal_verdict"] is True
    assert any("proiectele pendinte" in action for action in workspace["next_actions"])
    readiness = out["drilldown"]["readiness"]
    assert readiness["contract"] == "matrice-readiness-v1"
    assert readiness["status"] == "reviewable_candidate"
    assert readiness["not_legal_verdict"] is True
    assert readiness["axes"]["domain"]["cheie"] == "necunoscut"
    assert readiness["axes"]["legal_rank"][0]["categorie"] == "primar"
    assert {i["cheie"] for i in readiness["axes"]["issue_type"]} >= {
        "lacuna",
        "constitutionalitate",
        "initiative",
        "amendamente",
    }
    assert readiness["axes"]["source_quality"]["loaded"] == 1
    assert readiness["reviewability"]["checks"]["exact_provisions"] is True
    assert readiness["reviewability"]["checks"]["source_snapshots"] is True
    assert readiness["drilldown_pointers"]["provisions"][0]["locator"] == "art7"
    assert readiness["drilldown_pointers"]["sources"][0]["content_hash"] == "a" * 64
    assert readiness["drilldown_pointers"]["sources"][0]["parser_version"] == "legislatie_ro.v1"
    assert {e["kind"] for e in out["drilldown"]["entry_points"]} >= {
        "manual_note",
        "proposal_drafting",
        "project_compare",
        "rule_candidate",
    }
    assert out["pasi"]
    assert "Dosar matrice: Parlamentul" in out["markdown"]
    assert "32014L0024" in out["markdown"]


def test_matrix_dossier_says_when_the_row_is_not_in_the_current_queue(tmp_path):
    stare = _stare(tmp_path)

    out = _matrice_dosar({"emitent": ["Parlamentul"], "problema": ["neconstitutionale"]}, stare)

    assert out["gasit"] is False
    assert out["rand"] is None
    assert out["acte"]["acte"] == []
    assert out["limitari"][0] == "Rândul nu există pentru filtrele curente."


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
