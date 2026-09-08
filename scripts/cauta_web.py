"""Sharded, fetch-on-demand full-text search — the browser's way past the payload ceiling.

The localhost search runs SQLite FTS over the whole corpus, which the browser cannot hold. This
searches the same corpus without shipping it: `scripts/shard.py` builds, ahead of time, a compact
act index, a prefix-sharded inverted index (token → the acts that contain it), and one small file
of provisions per act. A query here fetches only the index-shards for its own tokens, ranks the
acts those postings name, and fetches the provision files of just the top few to cut snippets.

So a search touches a few kilobytes even when the corpus behind it is the whole body of law: the
coverage is the corpus's, the download is the query's. This is the shape a hosted, re-syncable
dataset takes on a static host — the direction the product was already headed.

**One tokeniser, both sides.** The builder and this searcher fold and split identically
(`_tokenuri` over `text.cheie`), so a token in a query is the token the index was keyed on — the
same parity `parsare` and `referinte` keep, applied to search. `pyodide.http.pyfetch` is imported
lazily, inside the fetch, so importing this module under CPython (the builder does) needs no
browser. Snippets are located on a length-preserving fold so their offsets map back to the
original, diacritics and all.
"""

from __future__ import annotations

import re

from scripts.text import cheie, fara_diacritice

# A search token: a run of at least three ascii-alphanumerics in the folded text. Folding first
# (via `cheie`) means diacritics and case are already gone, so the class is deliberately plain.
_TOKEN = re.compile(r"[a-z0-9]{3,}")


# How many leading characters name a shard. Two put 1,6 million tokens into 1.292 files and
# left `co.json` at 34 MB — a query for two common words pulled 18 MB. Three splits the same
# index into far smaller buckets; object storage does not care how many files there are.
_PREFIX = 3


def _tokenuri(text: str) -> list[str]:
    """The tokens of a passage, deduplicated, in first-seen order. Shared with the builder."""
    return list(dict.fromkeys(_TOKEN.findall(cheie(text))))


def _fragment(act: dict, toks: list[str]) -> dict:
    """The first provision of `act` that carries a query token, as a bracketed snippet.

    Located on `fara_diacritice(text).lower()`, which folds character-for-character and so keeps
    the same length as the original — the match offset therefore indexes straight back into the
    original text, so the quoted fragment keeps its diacritics and its exact wording.
    """
    for p in act.get("provizii", []):
        text = p.get("text", "")
        jos = fara_diacritice(text).lower()
        pozitii = [(jos.find(t), t) for t in toks]
        pozitii = [(i, t) for i, t in pozitii if i >= 0]
        if not pozitii:
            continue
        i, tok = min(pozitii)
        s, e = max(0, i - 50), min(len(text), i + len(tok) + 60)
        frag = text[s:i] + "[" + text[i : i + len(tok)] + "]" + text[i + len(tok) : e]
        if s > 0:
            frag = "…" + frag
        if e < len(text):
            frag = frag + "…"
        return {"locator": p.get("loc", ""), "fragment": frag}
    prima = (act.get("provizii") or [{}])[0]
    return {"locator": prima.get("loc", ""), "fragment": prima.get("text", "")[:140]}


# Shards are immutable — they live under a dated prefix and a republish writes a new one — so a
# shard fetched once is good for the rest of the session. Without this every query re-downloaded
# the same index files, which is most of what a search spends its time on.
_CACHE: dict[str, object] = {}


async def _json(url: str):
    if url in _CACHE:
        return _CACHE[url]
    from pyodide.http import pyfetch  # browser only; lazy so CPython can import this module

    r = await pyfetch(url)
    _CACHE[url] = None if r.status != 200 else await r.json()
    return _CACHE[url]


def _trece_filtru(meta: dict, tip: str | None, an_min: int | None, an_max: int | None) -> bool:
    """Whether an act passes the type/year filters, from its `index.json` record."""
    if tip and meta.get("tip") != tip:
        return False
    an = meta.get("an")
    if an_min is not None and (an is None or an < an_min):
        return False
    return not (an_max is not None and (an is None or an > an_max))


async def cauta(
    q: str,
    baza: str = "data",
    limita: int = 25,
    *,
    offset: int = 0,
    tip: str | None = None,
    an_min: int | None = None,
    an_max: int | None = None,
) -> dict:
    """Answer a query from the shards, fetching only what the query's own tokens require.

    Filtered by act type/year and paged, mirroring the localhost `_cauta`; `total` is the count of
    matching acts behind the page, so the UI can say how much it is not yet showing. The result
    shape is the one the search UI renders — `{results, total, offset, limita}`.
    """
    empty = {"results": [], "total": 0, "offset": offset, "limita": limita}
    toks = _tokenuri(q)
    if not toks:
        return empty

    scor: dict[int, int] = {}
    for t in toks:
        shard = await _json(f"{baza}/idx/{t[:_PREFIX]}.json")
        for n in (shard or {}).get(t, []):
            scor[n] = scor.get(n, 0) + 1
    if not scor:
        return empty

    index = await _json(f"{baza}/index.json") or []
    # Most query-tokens matched wins; ties break on index order (builder writes it newest-first).
    ordonate = [
        n
        for n in sorted(scor, key=lambda n: (-scor[n], n))
        if n < len(index) and _trece_filtru(index[n], tip, an_min, an_max)
    ]
    total = len(ordonate)
    rezultate = []
    for n in ordonate[offset : offset + limita]:
        meta = index[n]
        act = await _json(f"{baza}/acte/{meta['id']}.json")
        frag = _fragment(act, toks) if act else {"locator": "", "fragment": ""}
        rezultate.append(
            {
                "act_id": meta["id"],
                "locator": frag["locator"],
                "fragment": frag["fragment"],
                "titlu": meta.get("titlu", ""),
                "sursa_url": meta.get("url", ""),
                "tip": meta.get("tip", ""),
                "an": meta.get("an"),
            }
        )
    return {"results": rezultate, "total": total, "offset": offset, "limita": limita}


# Romanian inflects, and the index stores whatever the text said. Legea 98/2016 is titled
# "privind achiziţiile publice", which folds to the token `achizitiile`; someone searching
# `achizitii` matches none of it, and the only title token left is `publice` — which thousands of
# unrelated decisions also carry. Exact matching therefore ranked 2026 decisions above the
# procurement law itself. Matching a query token against the tokens it prefixes fixes that without
# a stemmer: `achizitii` reaches `achizitiile` and `achizitiilor`, `cod` reaches `codul`.
# Three, not four: the shortest token the tokeniser emits is three characters, and `cod` reaching
# `codul` is the difference between finding Codul civil and finding a 1950 decree that mentions it.
_MIN_PREFIX = 3

# What a reader means by "the law on public procurement" is Legea 98/2016, not one of the 42.143
# ordins that cite it. Ranking had no way to know that: acts matching the same title tokens tied,
# and the tie broke on index order, which is newest-first — so 2026 decisions sat above the law
# they apply. Rank by what an act *is*, before falling back to recency.
_RANG_TIP = {
    "lege": 0,
    "oug": 1,
    "og": 1,
    "cod": 0,
    "decret": 2,
    "hg": 3,
    "regulament": 3,
    "norma": 4,
    "metodologie": 4,
    "procedura": 4,
    "ordin": 5,
    "decizie": 6,
}
_RANG_ALT = 7


def _postari(shard: dict | None, t: str) -> list[int]:
    """The postings for `t` and for every indexed token it is a prefix of."""
    if not shard:
        return []
    exact = shard.get(t) or []
    if len(t) < _MIN_PREFIX:
        return exact
    iesire = set(exact)
    for cheie_t, postari in shard.items():
        if cheie_t != t and cheie_t.startswith(t):
            iesire.update(postari)
    return sorted(iesire)


async def cauta_montat(
    q: str,
    baza: str,
    corpus: str,
    limita: int = 25,
    *,
    offset: int = 0,
    tip: str | None = None,
    an_min: int | None = None,
    an_max: int | None = None,
    doar_titluri: bool = False,
) -> dict:
    """Search when the browser has the corpus mounted: postings from the shards, text from SQLite.

    The two halves are good at opposite things. Ranked full-text search over a mounted corpus means
    bm25 wants a document length per match, so ordering 6.478 hits took ~1.000 scattered reads and
    291 s over the network. The inverted index answers that in a couple of fetches. But the index
    used to carry titles, URLs and every act's provisions so it could stand alone — 91 MB on first
    visit and 7,3 GB of per-act files — and none of that is needed once the corpus is one range
    request away.

    So: the shards say *which* acts and in what order, and the corpus is asked only about the acts
    on the page actually being shown.
    """
    import sqlite3

    empty = {"results": [], "total": 0, "offset": offset, "limita": limita}
    toks = _tokenuri(q)
    if not toks:
        return empty

    # Two indexes, and the title one decides the order. A law about public procurement says so in
    # its title, and "achiziții publice" appears *somewhere* in 78.274 acts — matching the body
    # tells you almost nothing, matching the title tells you almost everything. Ranking on body
    # hits alone put three miscellaneous 2026 documents above Legea 98/2016.
    corp: dict[int, int] = {}
    titlu: dict[int, int] = {}
    for t in toks:
        shard = await _json(f"{baza}/idx/{t[:_PREFIX]}.json")
        for n in _postari(shard, t):
            corp[n] = corp.get(n, 0) + 1
        cap = await _json(f"{baza}/idx-titlu/{t[:_PREFIX]}.json")
        # Every matched query token counts once, whether the title said the word or an inflection
        # of it. Scoring the exact form higher looked principled and was backwards: Legea 98/2016
        # is titled "privind achiziţiile publice", so a search for `achizitii publice` scored it
        # *below* laws that happen to use the bare form — the canonical act, demoted for grammar.
        for n in _postari(cap, t):
            titlu[n] = titlu.get(n, 0) + 1
    # `doar_titluri` is the band the page puts above full-text search: only acts whose *title*
    # matched, which is the question "which act is this about" rather than "where is this phrase".
    # It exists because Pagefind ranks the body and cannot be told that a title is worth more —
    # with 20.367 acts mentioning public procurement somewhere, Legea 98/2016 lands at #172.
    scor = set(titlu) if doar_titluri else set(corp) | set(titlu)
    if not scor:
        return empty

    index = await _json(f"{baza}/index.json") or []
    # Every title token beats any number of body tokens; ties fall back to the index order, which
    # the builder writes newest-first.
    ordonate = [
        n
        for n in sorted(
            scor,
            # Then: what the act is, then how much of the rest of the corpus relies on it. How
            # often an act is cited is the closest thing here to "which one did they mean" —
            # Codul civil is cited 2.180 times, Legea 33/1994 on expropriation 209, and the 1932
            # and 1941 expropriation laws never. Title length only breaks what citations tie:
            # "LEGE … privind achiziţiile publice" over "LEGE … pentru aprobarea Ordonanţei …".
            key=lambda n: (
                -titlu.get(n, 0),
                _RANG_TIP.get((index[n].get("tip") if n < len(index) else "") or "", _RANG_ALT),
                -(index[n].get("c", 0) if n < len(index) else 0),
                index[n].get("lt", 999) if n < len(index) else 999,
                -corp.get(n, 0),
                n,
            ),
        )
        if n < len(index) and _trece_filtru(index[n], tip, an_min, an_max)
    ]
    total = len(ordonate)

    con = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rezultate = []
        for n in ordonate[offset : offset + limita]:
            meta = index[n]
            act = con.execute(
                "SELECT titlu, sursa_url, id_act_portal FROM acte WHERE id = ?", (meta["id"],)
            ).fetchone()
            # Bounded hard, because this is per result and each read is a round trip: at 200
            # provisions a page of three cost 23 s, almost all of it here. Forty finds the quote
            # in nearly every act, and the ones it misses simply show no quote.
            #
            # The title band skips it altogether. Its whole point is to name the act, and the
            # quotation is what makes a result expensive — dropping it is what lets a band of
            # eight arrive in a fraction of the time a page of full results takes.
            if doar_titluri:
                frag = {"locator": "", "fragment": ""}
            else:
                provizii = con.execute(
                    "SELECT locator, text FROM provizii WHERE act_id = ? ORDER BY ord LIMIT 40",
                    (meta["id"],),
                ).fetchall()
                frag = _fragment(
                    {"provizii": [{"loc": p["locator"], "text": p["text"]} for p in provizii]}, toks
                )
            # `_fragment` falls back to the act's first provision when it finds no token, and that
            # fallback reads as evidence: quoting "1.1. VALOAREA CREDITULUI" under a search for
            # public procurement claims a match that does not exist. The brackets are the marker
            # that a token was actually located, so without them the result carries no quote.
            if "[" not in frag.get("fragment", ""):
                frag = {"locator": "", "fragment": ""}
            rezultate.append(
                {
                    "act_id": meta["id"],
                    "locator": frag["locator"],
                    "fragment": frag["fragment"],
                    "titlu": (act["titlu"] if act else "") or "",
                    "sursa_url": (
                        depozit_url(act["sursa_url"], act["id_act_portal"]) if act else ""
                    ),
                    "tip": meta.get("tip", ""),
                    "an": meta.get("an"),
                }
            )
    finally:
        con.close()
    return {"results": rezultate, "total": total, "offset": offset, "limita": limita}


def depozit_url(sursa_url: str | None, id_act_portal: str | None) -> str:
    """`depozit.url_document`, imported lazily so this module imports without the corpus."""
    from scripts.depozit import url_document

    return url_document(sursa_url, id_act_portal)
