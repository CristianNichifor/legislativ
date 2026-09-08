"""The title band: the acts a query names, above the acts that merely mention it.

Pagefind ranks the body and cannot be told that a title weighs more, so with 20.367 acts mentioning
public procurement somewhere, Legea 98/2016 came back at #172. The band answers the other question —
which act is this about — from the title index that `shard.py` already builds and publishes.

`cauta_web._json` is a browser fetch; here it reads the files the builder just wrote, which are the
same ones uploaded to the object store.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts import cauta_web
from scripts.depozit import deschide, scrie_act
from scripts.parsare import din_fisier
from scripts.shard import construieste_index, construieste_index_titluri

SURSE = Path(__file__).resolve().parent.parent / "sources"


def _pregateste(tmp: Path) -> tuple[str, str]:
    """A one-act corpus with its two indexes, and `_json` pointed at them."""
    corpus = tmp / "c.db"
    with deschide(str(corpus)) as con:
        scrie_act(con, din_fisier(SURSE / "decizie-815-2015.html.gz"))
        con.commit()
    out = tmp / "idx"
    tacut = lambda *_: None  # noqa: E731
    construieste_index(str(corpus), str(out), log=tacut)
    construieste_index_titluri(str(corpus), str(out), log=tacut)

    async def _local(url: str):
        cale = Path(url)
        return json.loads(cale.read_text(encoding="utf-8")) if cale.is_file() else None

    cauta_web._json = _local
    cauta_web._CACHE.clear()
    return str(out), str(corpus)


def _cuvinte(corpus: str) -> tuple[str, str]:
    """One word from the act's title, and one that appears only in its body."""
    import sqlite3

    con = sqlite3.connect(corpus)
    try:
        titlu = con.execute("SELECT titlu FROM acte").fetchone()[0]
        texte = " ".join(t for (t,) in con.execute("SELECT text FROM provizii"))
    finally:
        con.close()
    din_titlu = cauta_web._tokenuri(titlu)
    doar_corp = [t for t in cauta_web._tokenuri(texte) if t not in set(din_titlu)]
    assert din_titlu and doar_corp, "fixtura nu separă titlul de corp"
    return din_titlu[0], doar_corp[0]


def test_the_band_returns_the_act_its_title_names(tmp_path):
    baza, corpus = _pregateste(tmp_path)
    cuvant, _ = _cuvinte(corpus)
    r = asyncio.run(cauta_web.cauta_montat(cuvant, baza, corpus, 8, doar_titluri=True))
    assert [x["act_id"] for x in r["results"]] == ["decizie-815-2015"]


def test_the_band_ignores_an_act_that_only_mentions_the_word(tmp_path):
    baza, corpus = _pregateste(tmp_path)
    _, doar_corp = _cuvinte(corpus)
    # The word is in the act — full search finds it — but not in its title, so the band is silent.
    # This is the whole point: a band that answered here would be the body ranking again.
    intreg = asyncio.run(cauta_web.cauta_montat(doar_corp, baza, corpus, 8))
    banda = asyncio.run(cauta_web.cauta_montat(doar_corp, baza, corpus, 8, doar_titluri=True))
    assert intreg["total"] == 1
    assert banda["total"] == 0 and banda["results"] == []


def test_the_band_costs_no_quotation(tmp_path):
    """The band names acts; quoting is what makes a result expensive, so it does not quote."""
    baza, corpus = _pregateste(tmp_path)
    cuvant, _ = _cuvinte(corpus)
    r = asyncio.run(cauta_web.cauta_montat(cuvant, baza, corpus, 8, doar_titluri=True))
    assert r["results"][0]["titlu"]
    assert r["results"][0]["fragment"] == "" and r["results"][0]["locator"] == ""
