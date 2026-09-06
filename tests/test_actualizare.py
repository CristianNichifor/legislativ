"""Tests for the daily refresh, offline.

The property that matters is that a refresh costs the new law and nothing else. A full rebuild
is right but unaffordable — two hours of collection, three minutes of dates, eleven of graph —
and a corpus nobody can afford to refresh quietly stops being true, which is this package's one
unforgivable failure arriving slowly instead of at once.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from scripts import depozit
from scripts.actualizare import _acte_atinse, actualizeaza
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare


def _rec(numar: str, text: str, portal: str | None = None) -> Inregistrare:
    return Inregistrare(
        titlu=f"LEGE nr. {numar}/2020",
        tip_act="LEGE",
        numar=numar,
        an=2020,
        data_vigoare=date(2020, 1, 1),
        emitent="Parlamentul",
        publicatie="MO",
        link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{portal or numar}",
        text=text,
    )


def test_only_the_acts_that_arrived_are_relinked(tmp_path):
    """`muchii` is keyed by `din_act`, so a new act's edges — including the inbound ones an old
    law gains — live on the new act's rows. Rebuilding the whole graph to place them would be
    eleven minutes to buy seconds."""
    db = tmp_path / "corpus.db"
    with depozit.deschide(db) as con:
        for i in ("1", "2"):
            r = _rec(i, f"LEGE nr. {i} din 2020 care modifică art. {i} din Legea nr. 98/2016.")
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        con.execute("UPDATE documente SET adus_la = '2020-01-01T00:00:00+00:00'")

    with depozit.deschide(db) as con:
        nou = _rec("3", "LEGE nr. 3 din 2020 care modifică art. 3 din Legea nr. 98/2016.")
        depozit.scrie_inregistrare(con, nou, act_din_inregistrare(nou))

    atinse = _acte_atinse(str(db), "2021-01-01T00:00:00+00:00")
    assert atinse == ["lege-3-2020"], atinse


def test_a_refresh_that_collects_nothing_relinks_nothing(tmp_path, monkeypatch):
    """The common case: run it daily, most days Parliament published nothing new."""
    db = tmp_path / "corpus.db"
    graf = tmp_path / "graf.db"
    with depozit.deschide(db) as con:
        r = _rec("1", "LEGE nr. 1 din 2020 care modifică art. 1 din Legea nr. 98/2016.")
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        depozit.pagina_terminata(con, 1, 1)
        con.execute("UPDATE documente SET adus_la = '2020-01-01T00:00:00+00:00'")

    # `actualizare` imports the collector inside the function, so patching the module attribute
    # is enough — no network, no service.
    from scripts import colector

    monkeypatch.setattr(
        colector,
        "actualizeaza",
        lambda *a, **k: colector.Actualizare(
            pagini=1, acte_scrise=0, acte_noi=0, ultima_veche=1, ultima_noua=1
        ),
    )

    r = actualizeaza(str(db), str(graf), lucratori=1, log=lambda *_: None)
    assert r.documente_noi == 0
    assert r.acte_cu_muchii == 0, "relinked acts that had not changed"
    assert r.muchii == 0


def test_the_result_reports_what_it_changed(tmp_path):
    """A refresh that cannot say what it did is a refresh nobody can audit."""
    from scripts.actualizare import Rezultat

    r = Rezultat(
        pagini=3,
        documente_noi=12,
        acte_noi=9,
        date_citite=11,
        lovituri=2,
        pagini_aduse=5,
        acte_structurate=4,
        acte_cu_muchii=9,
        muchii=140,
        secunde=42.0,
    )
    text = str(r)
    for asteptat in (
        "3 pagini",
        "12 documente noi",
        "9 acte noi",
        "2 lovituri",
        "5 pagini-sursă aduse",
        "4 acte structurate",
        "140 muchii",
        "42s",
    ):
        assert asteptat in text, text


def test_relinking_replaces_rather_than_doubles(tmp_path):
    """An act collected twice must not end up with its edges twice."""
    from scripts.graf import construieste

    db = tmp_path / "corpus.db"
    graf = tmp_path / "graf.db"
    with depozit.deschide(db) as con:
        r = _rec("7", "LEGE nr. 7 din 2020 care modifică art. 7 din Legea nr. 98/2016.")
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))

    construieste(str(db), str(graf), doar=["lege-7-2020"], log=lambda *_: None)
    con = sqlite3.connect(str(graf))
    intai = con.execute("SELECT count(*) FROM muchii").fetchone()[0]
    con.close()

    construieste(str(db), str(graf), doar=["lege-7-2020"], log=lambda *_: None)
    con = sqlite3.connect(str(graf))
    dupa = con.execute("SELECT count(*) FROM muchii").fetchone()[0]
    con.close()

    assert intai == dupa and intai > 0
