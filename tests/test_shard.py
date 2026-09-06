"""Tests for the search shards and their tokeniser.

The async fetch-on-demand search (`cauta_web.cauta`) needs a browser and is verified there; what is
tested here is everything pure: the tokeniser both sides share, the snippet cutter, and that the
builder writes an index and an inverted index a query can actually resolve against.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.cauta_web import _fragment, _tokenuri
from scripts.depozit import deschide, scrie_act
from scripts.parsare import din_fisier
from scripts.servicii import Stare, rezumat
from scripts.shard import construieste

SURSE = Path(__file__).resolve().parent.parent / "sources"


def _corpus(tmp: Path) -> str:
    cale = tmp / "c.db"
    with deschide(str(cale)) as con:
        scrie_act(con, din_fisier(SURSE / "decizie-815-2015.html.gz"))
        con.commit()
    return str(cale)


def test_the_tokeniser_folds_and_splits():
    assert _tokenuri("Autoritatea Contractantă!!!") == ["autoritatea", "contractanta"]
    # under three characters is not a token; diacritics and case are already gone by `cheie`.
    assert _tokenuri("a la ȚARĂ, în 2016") == ["tara", "2016"]


def test_the_builder_writes_an_index_and_a_resolvable_inverted_index(tmp_path):
    out = tmp_path / "out"
    manifest = construieste(_corpus(tmp_path), str(out), log=lambda *_: None)
    assert manifest["acte"] == 1 and manifest["tokeni"] > 0

    index = json.loads((out / "index.json").read_text())
    assert index[0]["id"] == "decizie-815-2015"

    # 'neconstituționalitate' folds to 'neconstitutionalitate'; its postings point back at act 0.
    shard = json.loads((out / "idx" / "ne.json").read_text())
    assert "neconstitutionalitate" in shard
    assert shard["neconstitutionalitate"] == [0]

    # the act's provisions were written out for snippeting.
    act = json.loads((out / "acte" / "decizie-815-2015.json").read_text())
    assert act["provizii"] and any("neconstituțional" in p["text"] for p in act["provizii"])


def test_the_snippet_keeps_the_original_diacritics_and_brackets_the_hit():
    act = {"provizii": [{"loc": "par1", "text": "Dispoziția este neconstituțională aici."}]}
    frag = _fragment(act, ["neconstitutional"])
    assert frag["locator"] == "par1"
    # located on a length-preserving fold, so the bracket lands on the real, diacritic'd word.
    assert "[neconstituțional]" in frag["fragment"]


def test_the_snippet_is_empty_handed_gracefully_when_nothing_matches():
    act = {"provizii": [{"loc": "par1", "text": "Un text fără termenul căutat."}]}
    frag = _fragment(act, ["inexistent"])
    assert frag["locator"] == "par1"  # falls back to the first provision rather than crashing


def test_a_shard_backed_stare_needs_no_corpus_db(tmp_path):
    """The engine-shard refactor: with `date_dir`, titles, counts and the dictionary come from the
    catalog. The shard output has no corpus.db in it at all — yet Stare answers everything, which
    is exactly the browser's situation, where the corpus is never downloaded."""
    corpus = tmp_path / "c.db"
    with deschide(str(corpus)) as con:
        scrie_act(con, din_fisier(SURSE / "decizie-815-2015.html.gz"))
        con.commit()
    out = tmp_path / "data"
    construieste(str(corpus), str(out), log=lambda *_: None)
    with deschide(str(out / "initiative.db")):  # empty initiatives db, as a real release may have
        pass
    assert not (out / "corpus.db").exists()  # the catalog carries no monolithic corpus

    st = Stare(
        str(out / "corpus.db"),  # a path that does not exist — and is never opened in shard mode
        str(out / "initiative.db"),
        str(out / "graf.db"),
        date_dir=str(out),
    )
    assert st.pe_shard
    assert st.titlu("decizie-815-2015").lower().startswith("decizie")
    assert st.cunoscut("decizie-815-2015") and not st.cunoscut("lege-1-1900")
    assert isinstance(st.termeni, list)
    r = rezumat(st)
    assert r["acte"] == 1 and r["provizii"] > 0 and r["initiative"] == 0

    # the act resolver (structured tip/număr/an → id + corpus membership + title)
    from scripts.servicii import _act

    gasit = _act({"tip": ["decizie"], "nr": ["815"], "an": ["2015"]}, st)
    assert gasit["act_id"] == "decizie-815-2015" and gasit["cunoscut"] and gasit["titlu"]
    lipsa = _act({"tip": ["lege"], "nr": ["1"], "an": ["1900"]}, st)
    assert lipsa["act_id"] == "lege-1-1900" and not lipsa["cunoscut"]
    assert _act({"tip": ["lege"], "nr": [""], "an": ["2016"]}, st)["act_id"] == ""  # incomplete


# --- republication dates reach the browser --------------------------------------------------
#
# `vigoare.py` decides whether a locator-level repeal predates a renumbering, which needs the act's
# republication date. On localhost that is a column; in the browser the only catalogue is
# index.json, so the date has to be carried there or the check silently never fires on the public
# build. These assert the same answer comes back from both backings.


def _cu_republicare(tmp: Path, cand: str | None) -> str:
    """A corpus whose single act carries (or does not carry) a republication date."""
    cale = _corpus(tmp)
    with deschide(cale) as con:
        con.execute("UPDATE acte SET republicat_din = ?", (cand,))
        con.commit()
    return cale


def test_the_shard_index_carries_republication_dates(tmp_path):
    corpus = _cu_republicare(tmp_path, "2015-03-11")
    construieste(corpus, str(tmp_path / "web"), log=lambda *a, **k: None)
    index = json.loads((tmp_path / "web" / "index.json").read_text(encoding="utf-8"))
    assert [a.get("republicat_din") for a in index] == ["2015-03-11"]


def test_an_act_with_no_republication_does_not_carry_the_key(tmp_path):
    """Absent for all but a handful of acts, so the key is omitted rather than written null."""
    corpus = _cu_republicare(tmp_path, None)
    construieste(corpus, str(tmp_path / "web"), log=lambda *a, **k: None)
    index = json.loads((tmp_path / "web" / "index.json").read_text(encoding="utf-8"))
    assert all("republicat_din" not in a for a in index)


def test_both_backings_report_the_same_republication_date(tmp_path):
    from datetime import date

    corpus = _cu_republicare(tmp_path, "2015-03-11")
    construieste(corpus, str(tmp_path / "web"), log=lambda *a, **k: None)
    index = json.loads((tmp_path / "web" / "index.json").read_text(encoding="utf-8"))
    act_id = index[0]["id"]

    pe_disc = Stare(corpus).republicari({act_id})
    pe_shard = Stare(date_dir=str(tmp_path / "web")).republicari({act_id})
    assert pe_disc == pe_shard == {act_id: date(2015, 3, 11)}
    # an act nobody asked about is not queried, and an empty request costs no read
    assert Stare(corpus).republicari(set()) == {}
