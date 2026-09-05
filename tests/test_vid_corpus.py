"""Tests for the gap report wired to the graph.

This is where the graph, the extractors and vid's severity logic meet, so the tests assert the
join: an obligation is a gap when the graph shows no implementing act, it is not a gap when the
graph shows one, and the completeness dial turns a blocking finding into a material one exactly
when the corpus is declared complete for the instrument. Built on a small corpus + graph so the
assertions do not move with the collection.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.graf import construieste
from scripts.vid_corpus import raport_vid


def _setup(tmp_path: Path, acts: list[tuple[str, str, str, str]]):
    """acts = [(tip, numar, publicat_iso, text)] -> (corpus_db, graf_db)."""
    corpus = tmp_path / "corpus.db"
    with depozit.deschide(corpus) as con:
        for tip, numar, pub, text in acts:
            rec = Inregistrare(
                titlu=f"{tip} nr. {numar}",
                tip_act=tip,
                numar=numar,
                an=None,
                data_vigoare=date.fromisoformat(pub),
                emitent="X",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}0",
                text=text,
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf = tmp_path / "graf.db"
    construieste(str(corpus), str(graf))
    return str(corpus), str(graf)


LAW_WITH_DEADLINE = (
    "LEGE",
    "10",
    "2020-01-01",
    "În termen de 30 de zile de la intrarea în vigoare, Guvernul aprobă normele metodologice.",
)


def test_an_obligation_with_no_implementing_act_is_a_gap(tmp_path):
    corpus, graf = _setup(tmp_path, [LAW_WITH_DEADLINE])
    vids = raport_vid(corpus, graf, la_data=date(2026, 1, 1))
    assert len(vids) == 1
    assert vids[0].obligatie.act.id == "lege-10-2020"
    assert vids[0].zile_intarziere and vids[0].zile_intarziere > 2000


def test_an_obligation_the_graph_can_discharge_is_not_a_gap(tmp_path):
    corpus, graf = _setup(
        tmp_path,
        [
            LAW_WITH_DEADLINE,
            (
                "HOTARARE",
                "395",
                "2020-02-01",
                "Prezenta hotărâre aprobă normele metodologice de aplicare a Legii nr. 10/2020.",
            ),
        ],
    )
    vids = raport_vid(corpus, graf, complet_pentru=frozenset({"hg"}), la_data=date(2026, 1, 1))
    # the HG references Legea 10/2020 and is an 'hg', the expected instrument -> discharged
    assert all(v.obligatie.act.id != "lege-10-2020" for v in vids)


def test_the_completeness_dial_turns_blocking_into_material(tmp_path):
    corpus, graf = _setup(tmp_path, [LAW_WITH_DEADLINE])
    fara = raport_vid(corpus, graf, la_data=date(2026, 1, 1))
    cu = raport_vid(corpus, graf, complet_pentru=frozenset({"hg"}), la_data=date(2026, 1, 1))
    assert fara[0].severitate == "blocking"  # cannot tell missing from uncollected
    assert cu[0].severitate == "material"  # corpus vouches for hg -> a real gap


def test_procedural_deadlines_are_filtered_by_default(tmp_path):
    """ "cu recurs în termen de 10 zile" is an appeal clock, not a delegation; it names no
    instrument, so the default report leaves it out and the noise stays down."""
    corpus, graf = _setup(
        tmp_path,
        [
            ("DECIZIE", "137", "2020-01-01", "Cu recurs în termen de 10 zile de la comunicare."),
        ],
    )
    assert raport_vid(corpus, graf, la_data=date(2026, 1, 1)) == []
    assert raport_vid(corpus, graf, la_data=date(2026, 1, 1), doar_cu_instrument=False)
