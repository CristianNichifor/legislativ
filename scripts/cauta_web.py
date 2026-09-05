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


async def _json(url: str):
    from pyodide.http import pyfetch  # browser only; lazy so CPython can import this module

    r = await pyfetch(url)
    if r.status != 200:
        return None
    return await r.json()


async def cauta(q: str, baza: str = "data", limita: int = 25) -> dict:
    """Answer a query from the shards, fetching only what the query's own tokens require.

    The result shape is the one the search UI already renders — `{results: [{act_id, locator,
    fragment, titlu, sursa_url}]}` — so this drops in where the SQLite `_cauta` sat, with no change
    above it.
    """
    toks = _tokenuri(q)
    if not toks:
        return {"results": []}

    scor: dict[int, int] = {}
    for t in toks:
        shard = await _json(f"{baza}/idx/{t[:2]}.json")
        for n in (shard or {}).get(t, []):
            scor[n] = scor.get(n, 0) + 1
    if not scor:
        return {"results": []}

    index = await _json(f"{baza}/index.json") or []
    # Most query-tokens matched wins; ties break on index order (builder writes it newest-first).
    top = sorted(scor, key=lambda n: (-scor[n], n))[:limita]
    rezultate = []
    for n in top:
        if n >= len(index):
            continue
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
            }
        )
    return {"results": rezultate}
