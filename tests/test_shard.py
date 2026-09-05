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
