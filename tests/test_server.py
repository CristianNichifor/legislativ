"""Tests for the backend wiring.

The server adds no logic — it routes to the engines — so the tests exercise the routing
functions directly over small temporary corpora rather than a live socket, which keeps them fast
and deterministic. The one thing worth asserting is that `lint` returns all three sections from
the two databases at once, and that search reaches the corpus FTS.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.cdep import Initiativa
from scripts.colector import act_din_inregistrare
from scripts.graf import construieste
from scripts.server import Stare, _cauta, _lint, _redacteaza, _repealed, _targets, _vecini


def _build(tmp_path: Path) -> Stare:
    corpus = tmp_path / "corpus.db"
    initiative = tmp_path / "initiative.db"
    rec = Inregistrare(
        titlu="LEGE nr. 98 din 2016",
        tip_act="LEGE",
        numar="98",
        an=None,
        data_vigoare=date(2016, 5, 26),
        emitent="PARLAMENTUL",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/178667",
        text="Art. 3. - În sensul prezentei legi, termenii de mai jos au următoarele "
        "semnificații:\na) achiziție publică - achiziția de lucrări sau servicii;",
    )
    with depozit.deschide(corpus) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    ini = Initiativa(
        plx_id="plx-1-2024",
        cam=2,
        idp="1",
        senat_id="L5/2024",
        tip="propunere legislativa",
        titlu="Lege pentru modificarea Legii nr. 98/2016",
        obiect="modificarea articolului 7 din Legea nr. 98/2016",
        urgenta=False,
        stadiu="pe ordinea de zi",
        camera_decizionala="Camera Deputaților",
        data_inreg="2024-01-01",
        sursa_url="",
    )
    with depozit.deschide(initiative) as con:
        depozit.scrie_initiativa(con, ini)
    return Stare(str(corpus), str(initiative))


def test_lint_returns_all_three_sections_from_both_databases(tmp_path):
    stare = _build(tmp_path)
    draft = (
        "La articolul 7 din Legea nr. 98/2016 privind achizițiile publice se modifică. "
        "În termen de 30 de zile de la intrarea în vigoare, Guvernul aprobă normele metodologice. "
        "Prezenta reglementează achizițiile de stat."
    )
    out = _lint(draft, stare)
    assert any(d["termen_zile"] == 30 for d in out["deadlines"])
    assert any(t["regula"] == "categorie-paralela" for t in out["terminology"])  # achiziții de stat
    assert out["duplicates"] and out["duplicates"][0]["plx_id"] == "plx-1-2024"
    assert out["duplicates"][0]["senat_id"] == "L5/2024"


def test_search_reaches_the_corpus_fts(tmp_path):
    stare = _build(tmp_path)
    assert _cauta("achizitie", stare)["results"]  # diacritic-folded
    assert _cauta("", stare)["results"] == []


def test_the_terminology_dictionary_is_built_from_the_corpus(tmp_path):
    stare = _build(tmp_path)
    assert any(t.termen == "achiziție publică" for t in stare.termeni)


def test_targets_report_how_amended_each_touched_act_is(tmp_path):
    """The graph turns "you amend Legea X" into "Legea X is on its Nth revision" — the fact most
    worth surfacing to someone about to patch it."""
    stare = _build(tmp_path)
    # build a graph where one act amends Legea 98/2016
    corpus2 = tmp_path / "corpus.db"
    from datetime import date

    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    with depozit.deschide(corpus2) as con:
        rec = Inregistrare(
            titlu="LEGE nr. 200 din 2024",
            tip_act="LEGE",
            numar="200",
            an=None,
            data_vigoare=date(2024, 1, 1),
            emitent="X",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/2000",
            text="Articolul 7 din Legea nr. 98/2016 se modifică.",
        )
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus2), str(graf_db))
    stare.graf = str(graf_db)

    out = _targets("Propunere pentru modificarea Legii nr. 98/2016.", stare)
    l98 = next((t for t in out if t["act_id"] == "lege-98-2016"), None)
    assert l98 and l98["amendat_de"] >= 1


def test_targets_are_empty_without_a_graph(tmp_path):
    stare = _build(tmp_path)
    stare.graf = str(tmp_path / "nonexistent.db")
    assert _targets("modificarea Legii nr. 98/2016", stare) == []


def test_lint_flags_a_citation_to_a_repealed_article(tmp_path):
    """The highest-severity thing the linter says: do not build on law that is gone."""
    from scripts.graf import construieste

    stare = _build(tmp_path)
    corpus2 = tmp_path / "corpus.db"
    from datetime import date

    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    with depozit.deschide(corpus2) as con:
        rec = Inregistrare(
            titlu="LEGE nr. 200",
            tip_act="LEGE",
            numar="200",
            an=None,
            data_vigoare=date(2024, 1, 1),
            emitent="X",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/2000",
            text="Articolul 7 din Legea nr. 98/2016 se abrogă.",
        )
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus2), str(graf_db))
    stare.graf = str(graf_db)

    out = _repealed("Se aplică art. 7 din Legea nr. 98/2016.", stare)
    assert out and out[0]["act_id"] == "lege-98-2016" and "abrogat" in out[0]["motiv"]
    # and it rides in the full lint answer
    assert "repealed" in _lint("Se aplică art. 7 din Legea nr. 98/2016.", stare)


def test_vecini_returns_deduped_neighbours(tmp_path):
    """Click-to-explore: one act's amenders and targets, one node per act even when it amends
    several of its articles."""
    from datetime import date

    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare
    from scripts.graf import construieste

    stare = _build(tmp_path)
    corpus2 = tmp_path / "corpus.db"
    with depozit.deschide(corpus2) as con:
        for numar, text in [
            (
                "200",
                "Articolul 7 din Legea nr. 98/2016 se modifică. "
                "Articolul 8 din Legea nr. 98/2016 se modifică.",
            ),
            ("201", "Se abrogă Legea nr. 98/2016."),
        ]:
            rec = Inregistrare(
                titlu=f"LEGE nr. {numar}",
                tip_act="LEGE",
                numar=numar,
                an=None,
                data_vigoare=date(2024, 1, 1),
                emitent="X",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}0",
                text=text,
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus2), str(graf_db))
    stare.graf = str(graf_db)

    v = _vecini("lege-98-2016", stare)
    ids = [m["act_id"] for m in v["inbound"]]
    assert "lege-200-2024" in ids and "lege-201-2024" in ids
    assert ids.count("lege-200-2024") == 1  # deduped despite two amended articles


def test_lint_flags_non_standard_drafting(tmp_path):
    """A draft that says the right thing the wrong way — the drafting-technique pass."""
    stare = _build(tmp_path)
    out = _lint("Articolul 7 din Legea nr. 98/2016 se schimbă.", stare)
    assert "drafting" in out
    assert out["drafting"] and out["drafting"][0]["operatie"] == "modifica"


def test_redacteaza_generates_mandated_form():
    """The draft assistant: a structured intent to the phrasing Legea 24/2000 requires. Pure —
    no corpus needed."""
    out = _redacteaza(
        {
            "op": ["modifica"],
            "act": ["Legea nr. 98/2016"],
            "articol": ["7"],
            "alineat": ["2"],
            "text": ["Autoritatea publică decide."],
        }
    )
    assert out["text"].startswith("La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică")
    assert "va avea următorul cuprins" in out["text"]
    assert out["titlu"] == "Lege pentru modificarea art. 7 din Legea nr. 98/2016"
