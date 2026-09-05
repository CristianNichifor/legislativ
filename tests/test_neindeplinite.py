"""Tests for the authority-list importer and the comparison against the derived gap report.

The committed sample (`data/neindeplinite_exemplu.csv`) exercises parsing; the comparison logic is
checked on hand-built findings so the coverage arithmetic — and its honest denominator — is pinned
without needing a live corpus.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.neindeplinite import (
    NormaNeindeplinita,
    _data,
    citeste,
    compara,
    importa,
)
from scripts.referinte import Act, Locator
from scripts.termene import Obligatie
from scripts.vid import Vid

EXEMPLU = Path(__file__).resolve().parent.parent / "data" / "neindeplinite_exemplu.csv"


def _vid(act_id: str) -> Vid:
    """A gap finding carrying only the host act — the field `compara` joins on."""
    tip, numar, an = act_id.split("-")
    ob = Obligatie(
        act=Act(tip, numar, int(an)),
        locator=Locator(),
        institutie=None,
        institutie_text=None,
        instrument="norme metodologice",
        tip_asteptat="hg",
        termen_zile=30,
        ancora="vigoare",
        data_limita=None,
        text="…",
    )
    return Vid(
        obligatie=ob,
        scadenta=None,
        zile_intarziere=None,
        cautat="",
        candidati=(),
        severitate="material",
        limitari=(),
    )


def test_citeste_maps_citations_to_corpus_keys_and_skips_comments():
    norme = citeste(EXEMPLU)
    ids = [n.act_id for n in norme]
    assert ids == ["lege-98-2016", "lege-196-2016", "oug-57-2019"]  # 3 rows, comments skipped
    assert all(n.sursa == "exemplu" for n in norme)


def test_citeste_parses_dates_and_maps_the_instrument_type():
    norme = citeste(EXEMPLU)
    by_act = {n.act_id: n for n in norme}
    assert by_act["lege-98-2016"].scadenta == date(2016, 6, 25)
    assert by_act["lege-98-2016"].tip_asteptat == "hg"  # norme metodologice -> hg
    assert by_act["oug-57-2019"].scadenta is None  # blank deadline stays None
    assert by_act["oug-57-2019"].tip_asteptat == "hg"  # hotărâre a Guvernului -> hg


def test_data_accepts_iso_and_dotted_but_refuses_a_two_digit_year():
    assert _data("2018-01-01") == date(2018, 1, 1)
    assert _data("01.01.2018") == date(2018, 1, 1)
    assert _data("") is None
    assert _data("01.01.18") is None  # too ambiguous to place
    assert _data("cândva") is None


def test_a_row_without_a_resolvable_act_keeps_none_and_is_not_dropped(tmp_path):
    f = tmp_path / "lista.csv"
    f.write_text(
        "act,instrument\n"
        '"un text fără citare de act","norme metodologice"\n'
        '"Legea nr. 98/2016","ordin"\n',
        encoding="utf-8",
    )
    norme = citeste(f)
    assert len(norme) == 2
    assert norme[0].act_id is None  # surfaced later as necunoscute, never silently dropped
    assert norme[1].act_id == "lege-98-2016"


def test_citeste_accepts_semicolons_and_header_aliases(tmp_path):
    f = tmp_path / "lista.csv"
    f.write_text(
        "lege;norma;termen\nLegea nr. 98/2016;norme metodologice;2016-06-25\n", encoding="utf-8"
    )
    norme = citeste(f)
    assert len(norme) == 1
    assert norme[0].act_id == "lege-98-2016" and norme[0].scadenta == date(2016, 6, 25)


def test_compara_scores_coverage_over_only_the_acts_the_corpus_holds():
    norme = [
        NormaNeindeplinita("lege-98-2016", "L98", "norme", "hg", None, "n", "x"),
        NormaNeindeplinita("lege-196-2016", "L196", "norme", "hg", None, "n", "x"),
        NormaNeindeplinita("oug-57-2019", "OUG57", "hotărâre", "hg", None, "n", "x"),
    ]
    vids = [_vid("lege-98-2016"), _vid("lege-200-2024")]

    # every authority act is in the corpus: coverage is agreement over all three
    cmp = compara(
        vids,
        norme,
        acte_in_corpus={"lege-98-2016", "lege-196-2016", "oug-57-2019", "lege-200-2024"},
    )
    assert cmp.acord == ("lege-98-2016",)
    assert cmp.doar_autoritate == ("lege-196-2016", "oug-57-2019")
    assert cmp.doar_tool == ("lege-200-2024",)
    assert cmp.necunoscute == ()
    assert abs(cmp.acoperire - 1 / 3) < 1e-9


def test_compara_keeps_acts_absent_from_the_corpus_out_of_the_denominator():
    norme = [
        NormaNeindeplinita("lege-98-2016", "L98", "norme", "hg", None, "n", "x"),
        NormaNeindeplinita("oug-57-2019", "OUG57", "hotărâre", "hg", None, "n", "x"),
    ]
    vids = [_vid("lege-98-2016")]
    # oug-57-2019 is not collected: it must not count as a miss, only as necunoscute
    cmp = compara(vids, norme, acte_in_corpus={"lege-98-2016"})
    assert cmp.acord == ("lege-98-2016",)
    assert cmp.doar_autoritate == ()
    assert cmp.necunoscute == ("oug-57-2019",)
    assert cmp.acoperire == 1.0  # 1 of 1 checkable, not 1 of 2


def test_importa_round_trips_through_the_store(tmp_path):
    db = tmp_path / "corpus.db"
    scrise = importa(EXEMPLU, db)
    assert scrise == 3
    with depozit.deschide(db, readonly=True) as con:
        assert depozit.rezumat(con)["neindeplinite"] == 3
        rows = con.execute(
            "SELECT act_id, tip_asteptat FROM neindeplinite ORDER BY act_id"
        ).fetchall()
    assert [r["act_id"] for r in rows] == ["lege-196-2016", "lege-98-2016", "oug-57-2019"]
