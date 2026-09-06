"""Tests for the derived amendment graph.

The graph's whole value is that its edges are ours — extracted from text by the measured
patterns, not scraped from a panel — so the tests assert exactly that: an amending act produces
an outbound edge, the amended act sees it inbound, and a plain reference is kept distinct from an
amendment. Built on a small corpus so the assertions do not drift with the collection.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.graf import _deschide_graf, construieste, inbound, outbound


def _corpus(tmp_path: Path, acts: list[tuple[str, str, str]]) -> Path:
    """acts = [(tip, numar, text)] → a corpus.db."""
    db = tmp_path / "corpus.db"
    with depozit.deschide(db) as con:
        for tip, numar, text in acts:
            rec = Inregistrare(
                titlu=f"{tip} nr. {numar} din 2024",
                tip_act=tip,
                numar=numar,
                an=None,
                data_vigoare=date(2024, 1, 1),
                emitent="X",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}0",
                text=text,
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    return db


def test_an_amendment_becomes_an_edge_both_ways(tmp_path):
    corpus = _corpus(
        tmp_path,
        [
            (
                "LEGE",
                "200",
                "La articolul 7 din Legea nr. 98/2016 privind achizițiile publice, "
                "alineatul (2) se modifică.",
            ),
        ],
    )
    graf_db = tmp_path / "graf.db"
    n = construieste(str(corpus), str(graf_db))
    assert n >= 1
    graf = _deschide_graf(str(graf_db))
    try:
        out = outbound(graf, "lege-200-2024")
        assert any(m.catre_act == "lege-98-2016" and m.fel == "modifica" for m in out)
        inn = inbound(graf, "lege-98-2016", doar_amendamente=True)
        assert [m.din_act for m in inn] == ["lege-200-2024"]
        assert inn[0].locator == "art7"
    finally:
        graf.close()


def test_a_reference_is_kept_distinct_from_an_amendment(tmp_path):
    corpus = _corpus(
        tmp_path,
        [
            (
                "HOTARARE",
                "395",
                "Prezenta hotărâre se adoptă în aplicarea Legii nr. 98/2016 "
                "privind achizițiile publice.",
            ),
        ],
    )
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus), str(graf_db))
    graf = _deschide_graf(str(graf_db))
    try:
        inn = inbound(graf, "lege-98-2016")
        assert inn and inn[0].fel == "refera"
        assert inbound(graf, "lege-98-2016", doar_amendamente=True) == []  # not an amendment
    finally:
        graf.close()


def test_an_act_does_not_edge_to_itself(tmp_path):
    corpus = _corpus(
        tmp_path,
        [
            ("LEGE", "98", "Articolul 15 se abrogă. Prezenta lege reglementează achizițiile."),
        ],
    )
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus), str(graf_db))
    graf = _deschide_graf(str(graf_db))
    try:
        assert all(m.catre_act != "lege-98-2024" for m in outbound(graf, "lege-98-2024"))
    finally:
        graf.close()


def test_rebuilding_replaces_rather_than_doubles(tmp_path):
    corpus = _corpus(
        tmp_path,
        [
            ("LEGE", "200", "Articolul 7 din Legea nr. 98/2016 se modifică."),
        ],
    )
    graf_db = tmp_path / "graf.db"
    n1 = construieste(str(corpus), str(graf_db))
    n2 = construieste(str(corpus), str(graf_db))
    assert n1 == n2
    graf = _deschide_graf(str(graf_db))
    try:
        assert graf.execute("SELECT count(*) FROM muchii").fetchone()[0] == n1
    finally:
        graf.close()


def test_parallel_extraction_gives_the_same_graph_as_sequential(tmp_path):
    """Extraction is 93% of the build and pure CPU, so it is fanned out across processes.

    The only thing that makes that safe is that it produces exactly the same edges — workers
    read their own text and the parent stays the sole writer, so nothing about the result may
    depend on how the work was divided.
    """
    from scripts import depozit
    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare
    from scripts.graf import construieste

    corpus = tmp_path / "corpus.db"
    with depozit.deschide(corpus) as con:
        for i in range(1, 25):
            rec = Inregistrare(
                titlu=f"LEGE nr. {i}/2020",
                tip_act="LEGE",
                numar=str(i),
                an=2020,
                data_vigoare=None,
                emitent="Parlamentul",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{i}",
                text=(
                    f"LEGE nr. {i} din 2020. Se modifică art. {i} din Legea nr. 98/2016 "
                    f"și art. II din Legea nr. 249/2006, potrivit art. 5 alin. (2) "
                    f"din Ordonanța de urgență a Guvernului nr. 57/2019."
                ),
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))

    secvential = tmp_path / "secv.db"
    paralel = tmp_path / "paral.db"
    n1 = construieste(str(corpus), str(secvential), lucratori=1, log=lambda *_: None)
    n2 = construieste(str(corpus), str(paralel), lucratori=4, log=lambda *_: None)
    assert n1 == n2 and n1 > 0

    def muchii(cale):
        con = sqlite3.connect(cale)
        try:
            return sorted(
                con.execute("SELECT din_act, catre_act, locator, fel, incredere, de_la FROM muchii")
            )
        finally:
            con.close()

    assert muchii(str(secvential)) == muchii(str(paralel))
