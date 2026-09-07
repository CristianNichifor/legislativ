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


def _corpus_mic(tmp_path, n=6):
    """A small corpus whose acts cite each other, for incremental-build tests."""
    from scripts import depozit
    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    cale = tmp_path / "corpus.db"
    with depozit.deschide(cale) as con:
        for i in range(1, n + 1):
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
                    f"și art. 5 alin. (2) din Ordonanța de urgență a Guvernului nr. 57/2019."
                ),
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    return cale


def _muchii(cale):
    con = sqlite3.connect(str(cale))
    try:
        return sorted(
            con.execute("SELECT din_act, catre_act, locator, fel, incredere, de_la FROM muchii")
        )
    finally:
        con.close()


def test_building_only_named_acts_touches_only_those(tmp_path):
    """A daily update collects a handful of new acts; rebuilding all 152 079 to place them is
    eleven minutes of work to add seconds of edges.

    Edges are keyed by `din_act`, so this is not an approximation: a new act's edges — including
    the inbound ones an older law gains — all live on the new act's rows. Nothing already in the
    graph needs revisiting."""
    from scripts.graf import construieste

    corpus = _corpus_mic(tmp_path)
    intreg = tmp_path / "intreg.db"
    construieste(str(corpus), str(intreg), log=lambda *_: None)
    toate = _muchii(intreg)

    partial = tmp_path / "partial.db"
    construieste(str(corpus), str(partial), doar=["lege-2-2020"], log=lambda *_: None)
    doar_doi = _muchii(partial)

    assert doar_doi, "no edges were built"
    assert {m[0] for m in doar_doi} == {"lege-2-2020"}
    # and they are exactly the edges the full build produced for that act
    assert doar_doi == [m for m in toate if m[0] == "lege-2-2020"]


def test_an_incremental_build_adds_without_disturbing_what_is_there(tmp_path):
    from scripts.graf import construieste

    corpus = _corpus_mic(tmp_path)
    g = tmp_path / "g.db"
    construieste(str(corpus), str(g), doar=["lege-2-2020"], log=lambda *_: None)
    inainte = _muchii(g)
    construieste(str(corpus), str(g), doar=["lege-3-2020"], log=lambda *_: None)
    dupa = _muchii(g)

    assert [m for m in dupa if m[0] == "lege-2-2020"] == inainte
    assert {m[0] for m in dupa} == {"lege-2-2020", "lege-3-2020"}


def test_the_parallel_path_honours_the_same_filter(tmp_path):
    from scripts.graf import construieste

    corpus = _corpus_mic(tmp_path)
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    construieste(str(corpus), str(a), doar=["lege-4-2020"], lucratori=1, log=lambda *_: None)
    construieste(str(corpus), str(b), doar=["lege-4-2020"], lucratori=3, log=lambda *_: None)
    assert _muchii(a) == _muchii(b)


# --- de unde vine muchia -------------------------------------------------------------------------
#
# An edge used to say only that this act points at that one. With article trees in the corpus it
# can say which provision did the pointing, which is the difference between knowing that something
# breaks and knowing what.


def _corpus_structurat(tmp_path: Path, act_id: str, provizii: list[tuple[str, str]]) -> Path:
    """A corpus holding one act with a real article tree, written provision by provision."""
    db = tmp_path / "corpus.db"
    with depozit.deschide(db) as con:
        con.execute(
            "INSERT OR REPLACE INTO acte (id, tip, numar, an, titlu, publicat, citit_la)"
            " VALUES (?,?,?,?,?,?,?)",
            (act_id, "lege", "7", 2024, "LEGE nr. 7 din 2024", "2024-01-01", "2024-01-01"),
        )
        for ord_, (locator, text) in enumerate(provizii):
            con.execute(
                "INSERT INTO provizii (act_id, locator, ord, text) VALUES (?,?,?,?)",
                (act_id, locator, ord_, text),
            )
        con.commit()
    return db


def test_spans_survive_the_extractors_own_normalisation(tmp_path):
    """The load-bearing invariant. `referinte` and `amendamente` normalise the text they are given,
    so an offset measured against a string that normalising would change points at the wrong words
    — and every edge would be attributed to the wrong article, silently."""
    from scripts.graf import text_cu_spans
    from scripts.text import normalizeaza

    db = _corpus_structurat(
        tmp_path,
        "lege-7-2024",
        [
            ("art1", "Articolul 1  Se aplică   art. 5 din Legea nr. 98/2016."),
            ("art2", "Articolul 2\n\n\nSe abrogă art. 9 din Legea nr. 50/1991."),
        ],
    )
    with depozit.deschide(db, readonly=True) as con:
        text, spans = text_cu_spans(con, "lege-7-2024")
    assert normalizeaza(text) == text, "offsets would shift under the extractors' own pass"
    for inceput, sfarsit, locator in spans:
        assert text[inceput:sfarsit].strip(), locator


def test_an_edge_carries_the_provision_it_was_read_from(tmp_path):
    db = _corpus_structurat(
        tmp_path,
        "lege-7-2024",
        [
            ("art1", "Articolul 1 Se aplică art. 5 din Legea nr. 98/2016."),
            ("art2", "Articolul 2 Se aplică art. 9 din Legea nr. 50/1991."),
        ],
    )
    graf = tmp_path / "graf.db"
    construieste(str(db), str(graf), log=lambda *_: None)
    con = _deschide_graf(str(graf), readonly=True)
    try:
        randuri = {
            (r["din_locator"], r["catre_act"])
            for r in con.execute("SELECT din_locator, catre_act FROM muchii")
        }
    finally:
        con.close()
    assert ("art1", "lege-98-2016") in randuri
    assert ("art2", "lege-50-1991") in randuri


def test_two_articles_citing_one_act_are_two_edges(tmp_path):
    """The reason `din_locator` is in the primary key. Without it the second article's citation
    replaces the first's and the graph reports one source where the act has two."""
    db = _corpus_structurat(
        tmp_path,
        "lege-7-2024",
        [
            ("art1", "Articolul 1 Se aplică art. 5 din Legea nr. 98/2016."),
            ("art2", "Articolul 2 Se aplică tot art. 5 din Legea nr. 98/2016."),
        ],
    )
    graf = tmp_path / "graf.db"
    construieste(str(db), str(graf), log=lambda *_: None)
    con = _deschide_graf(str(graf), readonly=True)
    try:
        surse = sorted(
            r["din_locator"]
            for r in con.execute("SELECT din_locator FROM muchii WHERE catre_act = 'lege-98-2016'")
        )
    finally:
        con.close()
    assert surse == ["art1", "art2"]


def test_a_chapeau_still_carries_its_target_across_provisions(tmp_path):
    """Why the text is joined rather than read provision by provision. A Romanian amending act
    names its target once and lists the changes under it; extracting each provision alone would
    lose the target of every amendment after the first."""
    db = _corpus_structurat(
        tmp_path,
        "lege-7-2024",
        [
            (
                "art1",
                "Articolul 1 Legea nr. 98/2016 se modifică și se completează după cum urmează:",
            ),
            ("art1.pct1", "1. La articolul 5, alineatul (2) se modifică."),
            ("art1.pct2", "2. La articolul 9, alineatul (1) se modifică."),
        ],
    )
    graf = tmp_path / "graf.db"
    construieste(str(db), str(graf), log=lambda *_: None)
    con = _deschide_graf(str(graf), readonly=True)
    try:
        tinte = {r["catre_act"] for r in con.execute("SELECT catre_act FROM muchii")}
    finally:
        con.close()
    assert tinte == {"lege-98-2016"}, "the chapeau's target was lost"


def test_an_old_graph_without_the_column_is_rebuilt_not_patched(tmp_path):
    """`din_locator` belongs in the key, so it cannot be added by `ALTER TABLE`. The old rows have
    no source to migrate to and are recomputable from the corpus, so they go."""
    graf = tmp_path / "vechi.db"
    con = sqlite3.connect(graf)
    con.executescript(
        "CREATE TABLE muchii (din_act TEXT NOT NULL, catre_act TEXT NOT NULL, locator TEXT,"
        " fel TEXT NOT NULL, incredere TEXT NOT NULL, de_la TEXT,"
        " PRIMARY KEY (din_act, catre_act, locator, fel));"
    )
    con.execute("INSERT INTO muchii VALUES ('a','b','art1','refera','derived',NULL)")
    con.commit()
    con.close()

    nou = _deschide_graf(str(graf))
    try:
        coloane = {r[1] for r in nou.execute("PRAGMA table_info(muchii)")}
        (n,) = nou.execute("SELECT count(*) FROM muchii").fetchone()
    finally:
        nou.close()
    assert "din_locator" in coloane
    assert n == 0


def test_the_read_api_carries_the_source_provision(tmp_path):
    """`inbound`/`outbound` select `*` and build a `Muchie`; a mapper that dropped the column
    would hand every consumer `None` and the graph would look as it did before."""
    from scripts.graf import outbound

    db = _corpus_structurat(
        tmp_path,
        "lege-7-2024",
        [("art1", "Articolul 1 Se aplică art. 5 din Legea nr. 98/2016.")],
    )
    graf = tmp_path / "graf.db"
    construieste(str(db), str(graf), log=lambda *_: None)
    con = _deschide_graf(str(graf), readonly=True)
    try:
        muchii = outbound(con, "lege-7-2024")
    finally:
        con.close()
    assert muchii and muchii[0].din_locator == "art1"


def test_a_reader_on_a_pre_migration_graph_still_answers(tmp_path):
    """A read-only connection never runs the migration, so the mapper must tolerate the column's
    absence rather than raise on a graph someone has not rebuilt yet."""
    from scripts.graf import outbound

    graf = tmp_path / "vechi.db"
    con = sqlite3.connect(graf)
    con.executescript(
        "CREATE TABLE muchii (din_act TEXT NOT NULL, catre_act TEXT NOT NULL, locator TEXT,"
        " fel TEXT NOT NULL, incredere TEXT NOT NULL, de_la TEXT);"
    )
    con.execute("INSERT INTO muchii VALUES ('a','b','art1','refera','derived',NULL)")
    con.commit()
    con.close()

    ro = _deschide_graf(str(graf), readonly=True)
    try:
        (m,) = outbound(ro, "a")
    finally:
        ro.close()
    assert m.catre_act == "b" and m.din_locator is None
