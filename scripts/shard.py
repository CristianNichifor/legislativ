"""Turn a corpus database into the fetch-on-demand shards the browser search reads.

`scripts/cauta_web.py` searches without holding the corpus; this is what it reads. From a corpus
`.db` it writes, under an output directory:

- `index.json` — one compact record per act (`id, tip, numar, an, titlu, url`), newest first. The
  inverted index refers to acts by their position here, so postings are small integers, not the
  long string ids.
- `idx/<prefix>.json` — the inverted index, sharded by the first two characters of each token:
  `{token: [act positions]}`. A query fetches only the shards its own tokens fall in.
- `acte/<id>.json` — one act's provisions (`{loc, text}`), fetched only to cut a snippet for a hit.
- `manifest.json` — the counts, so the size of what was built is visible, not guessed.

The tokeniser is `cauta_web._tokenuri`, imported rather than re-implemented, so the index is keyed
on exactly the tokens a query produces. Standard library only; the corpus is read `mode=ro`.

Run: `uv run python -m scripts.shard --corpus corpus.db --out web/data`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from scripts import depozit
from scripts.cauta_web import _PREFIX, _tokenuri

# Above this many acts, a token in more than this fraction of them is a near-stopword: it names no
# act in particular and its postings are the largest in the index, so it is dropped. Below the
# threshold (a demo corpus) nothing is dropped — every token still finds its act.
_PRAG_ACTE = 200
_FRACTIE_STOP = 0.4


def construieste(corpus_db: str, out: str, *, log=print) -> dict:
    """Read the corpus, write the shards, return the manifest. Idempotent: overwrites cleanly."""
    baza = Path(out)
    (baza / "idx").mkdir(parents=True, exist_ok=True)
    (baza / "acte").mkdir(parents=True, exist_ok=True)

    with depozit.deschide(corpus_db, readonly=True) as con:
        acte = con.execute(
            "SELECT id, tip, numar, an, titlu, sursa_url, id_act_portal, republicat_din FROM acte "
            "ORDER BY an DESC, numar"
        ).fetchall()
        index = [
            {
                "id": r["id"],
                "tip": r["tip"],
                "numar": r["numar"],
                "an": r["an"],
                "titlu": r["titlu"] or "",
                "url": depozit.url_document(r["sursa_url"], r["id_act_portal"]),
                # only for the few acts that carry one — `vigoare.py` needs it in the browser to
                # know whether a locator-level repeal predates a renumbering, and omitting the key
                # everywhere else keeps the index compact
                **({"republicat_din": r["republicat_din"]} if r["republicat_din"] else {}),
            }
            for r in acte
        ]
        (baza / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

        # token -> set of act positions, and one provisions file per act as we go.
        postari: dict[str, set[int]] = {}
        for n, r in enumerate(acte):
            act_id = r["id"]
            provizii = con.execute(
                "SELECT locator, text FROM provizii WHERE act_id = ? ORDER BY ord", (act_id,)
            ).fetchall()
            (baza / "acte" / f"{act_id}.json").write_text(
                json.dumps(
                    {
                        "id": act_id,
                        "titlu": r["titlu"] or "",
                        "url": depozit.url_document(r["sursa_url"], r["id_act_portal"]),
                        "provizii": [{"loc": p["locator"], "text": p["text"]} for p in provizii],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            text = " ".join(p["text"] for p in provizii)
            for t in _tokenuri(text):
                postari.setdefault(t, set()).add(n)

        n_provizii = con.execute("SELECT count(*) FROM provizii").fetchone()[0]
        # Acts with a real article tree, and the normative acts it is fair to measure them against
        # — a Curtea Constituțională decision has no articles to parse. Both counted here so the
        # browser reads them out of the manifest for nothing. See `depozit.rezumat`.
        n_structurate = depozit._structurate_normative(con)
        n_normative = con.execute(
            f"SELECT count(*) FROM acte WHERE tip IN ({depozit._MARCAJE_NORMATIV})"
        ).fetchone()[0]
        # The terminology dictionary, prebuilt here so the browser needs no corpus.db to run the
        # terminology check — the same bounded (recent-N) dictionary the localhost server computes
        # at startup, serialised. `jargon` matches on the term itself, so term + definition is all
        # it needs carried across.
        from scripts.analiza import termeni_corpus

        termeni = [
            {"termen": t.termen, "definitie": t.definitie} for t in termeni_corpus(con, limita=800)
        ]
        (baza / "termeni.json").write_text(
            json.dumps(termeni, ensure_ascii=False), encoding="utf-8"
        )

    n_acte = len(acte)
    prag = _FRACTIE_STOP * n_acte if n_acte > _PRAG_ACTE else n_acte + 1
    pastrate = {t: sorted(a) for t, a in postari.items() if len(a) <= prag}

    shards: dict[str, dict[str, list[int]]] = {}
    for t, posting in pastrate.items():
        shards.setdefault(t[:_PREFIX], {})[t] = posting
    for prefix, continut in shards.items():
        (baza / "idx" / f"{prefix}.json").write_text(
            json.dumps(continut, ensure_ascii=False), encoding="utf-8"
        )

    manifest = {
        "acte": n_acte,
        "provizii": n_provizii,
        "acte_structurate": n_structurate,
        "acte_normative": n_normative,
        "termeni": len(termeni),
        "tokeni": len(pastrate),
        "tokeni_scosi": len(postari) - len(pastrate),
        "shard_uri": len(shards),
    }
    (baza / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    log(
        f"  shard: {n_acte} acte, {len(pastrate)} tokeni în {len(shards)} shard-uri "
        f"({manifest['tokeni_scosi']} tokeni-stop scoși)"
    )
    return manifest


def _dimensiuni(out: str) -> str:
    baza = Path(out)
    mb = lambda b: b / 1e6  # noqa: E731
    total = sum(f.stat().st_size for f in baza.rglob("*.json"))
    idx = sum(f.stat().st_size for f in (baza / "idx").glob("*.json"))
    idx += (baza / "index.json").stat().st_size
    acte = sum(f.stat().st_size for f in (baza / "acte").glob("*.json"))
    return (
        f"  dimensiuni (necomprimat): index+idx {mb(idx):.2f} MB încărcat la nevoie, "
        f"acte {mb(acte):.1f} MB pe cerere, total {mb(total):.1f} MB"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Construiește shard-urile de căutare din corpus.")
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--out", default="web/data")
    a = ap.parse_args()
    construieste(a.corpus, a.out)
    print(_dimensiuni(a.out))


if __name__ == "__main__":
    main()


# ── Index-only build, for a corpus the browser mounts rather than downloads ──────────────────
#
# `construieste` also writes `acte/<id>.json` per act, so a hit can be given a snippet without a
# corpus. Over the whole corpus that is about **7,3 GB**, and it is redundant once the browser
# mounts `corpus.db`: titles and snippets become point lookups, which the mount is good at —
# 0,06 MB and 0,02 s for an act.
#
# What the mount is bad at is ranked full-text search. bm25 wants a document length per match, so
# ordering 6.478 hits meant ~1.000 scattered reads and 291 s over the network; even unranked, the
# intersection of two common terms cost 261. A single rare term costs 23. The inverted index is
# the structure that answers the common case in a couple of fetches, so: index here, hydrate from
# the corpus.

_LOT = 500_000


def _postari_felie(arg: tuple) -> str:
    """One core's share of the tokenising: the acts whose position satisfies `n % k == f`.

    Writes its own SQLite file and returns the path. Handing the pairs back through the pool would
    mean ~20 million tuples resident per worker, which is exactly what the on-disk accumulator
    exists to avoid.
    """
    import sqlite3

    corpus_db, f, k, pozitie, tinta = arg
    con = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    out = sqlite3.connect(tinta)
    out.execute("PRAGMA journal_mode=OFF")
    out.execute("PRAGMA synchronous=OFF")
    out.execute("CREATE TABLE p (token TEXT NOT NULL, n INTEGER NOT NULL)")
    try:
        lot: list[tuple[str, int]] = []
        for act_id, text in con.execute(
            "SELECT act_id, group_concat(text, ' ') FROM provizii GROUP BY act_id"
        ):
            n = pozitie.get(act_id)
            if n is None or n % k != f:
                continue
            lot.extend((t, n) for t in set(_tokenuri(text or "")))
            if len(lot) >= _LOT:
                out.executemany("INSERT INTO p VALUES (?,?)", lot)
                lot.clear()
        if lot:
            out.executemany("INSERT INTO p VALUES (?,?)", lot)
        out.commit()
        return tinta
    finally:
        con.close()
        out.close()


def construieste_index(corpus_db: str, out: str, *, log=print) -> dict:
    """Write `idx/`, a slim `index.json` and `termeni.json`. No per-act files."""
    import concurrent.futures as cf
    import os
    import sqlite3
    import tempfile

    baza = Path(out)
    (baza / "idx").mkdir(parents=True, exist_ok=True)

    with depozit.deschide(corpus_db, readonly=True) as con:
        acte = con.execute(
            "SELECT id, tip, numar, an, titlu, republicat_din FROM acte ORDER BY an DESC, numar"
        ).fetchall()
        # Slim on purpose: no titles, no URLs. Carrying those is what made the full index 91 MB on
        # every first visit, and the mounted corpus has them for the few acts a page shows.
        index = [
            {
                "id": r["id"],
                "tip": r["tip"],
                "numar": r["numar"],
                "an": r["an"],
                # Title length in tokens: two acts matching the same words are not equally about
                # them, and the shorter title is the more specific act.
                "lt": len(_tokenuri(r["titlu"] or "")),
                **({"republicat_din": r["republicat_din"]} if r["republicat_din"] else {}),
            }
            for r in acte
        ]
        (baza / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        n_acte = len(acte)
        log(f"  index slim: {n_acte} acte · {(baza / 'index.json').stat().st_size / 1e6:.1f} MB")

        from scripts.analiza import termeni_corpus

        termeni = [
            {"termen": t.termen, "definitie": t.definitie} for t in termeni_corpus(con, limita=800)
        ]
        (baza / "termeni.json").write_text(
            json.dumps(termeni, ensure_ascii=False), encoding="utf-8"
        )

    pozitie = {r["id"]: n for n, r in enumerate(acte)}
    lucru = Path(tempfile.mkdtemp(prefix="shard-"))
    acc = sqlite3.connect(lucru / "postari.db")
    acc.execute("PRAGMA journal_mode=OFF")
    acc.execute("PRAGMA synchronous=OFF")
    acc.execute("CREATE TABLE p (token TEXT NOT NULL, n INTEGER NOT NULL)")

    # Tokenising is the whole cost: folding diacritics and running the regex over every act
    # measured about nine acts a second, six hours for the corpus. Acts are independent, so the
    # work splits across cores; each worker reads its own slice, so no text crosses the pool.
    nuclee = max(1, (os.cpu_count() or 2) - 1)
    cereri = [(corpus_db, f, nuclee, pozitie, str(lucru / f"felie-{f}.db")) for f in range(nuclee)]
    total, gata = 0, 0
    with cf.ProcessPoolExecutor(max_workers=nuclee) as pool:
        for cale in pool.map(_postari_felie, cereri):
            acc.execute("ATTACH ? AS w", (cale,))
            acc.execute("INSERT INTO p SELECT token, n FROM w.p")
            acc.commit()
            acc.execute("DETACH w")
            Path(cale).unlink(missing_ok=True)
            gata += 1
            total = acc.execute("SELECT count(*) FROM p").fetchone()[0]
            log(f"  felia {gata}/{nuclee} · {total} postări")

    # A token in more than `_FRACTIE_STOP` of the acts names none of them and carries the largest
    # posting list in the index. Dropped here, in SQL, so the index is never resident.
    prag = int(_FRACTIE_STOP * n_acte) if n_acte > _PRAG_ACTE else n_acte + 1
    acc.execute("CREATE INDEX ip ON p(token)")
    acc.commit()

    scrise = pastrate = 0
    curent, continut = None, {}
    for token, postari in acc.execute(
        "SELECT token, group_concat(DISTINCT n) FROM p GROUP BY token ORDER BY token"
    ):
        lista = sorted({int(x) for x in postari.split(",")})
        if len(lista) > prag:
            continue
        pastrate += 1
        if token[:_PREFIX] != curent:
            if curent is not None:
                (baza / "idx" / f"{curent}.json").write_text(
                    json.dumps(continut, ensure_ascii=False), encoding="utf-8"
                )
                scrise += 1
            curent, continut = token[:_PREFIX], {}
        continut[token] = lista
    if curent is not None:
        (baza / "idx" / f"{curent}.json").write_text(
            json.dumps(continut, ensure_ascii=False), encoding="utf-8"
        )
        scrise += 1
    acc.close()
    shutil.rmtree(lucru, ignore_errors=True)

    octeti = sum(p.stat().st_size for p in (baza / "idx").glob("*.json"))
    log(f"  idx: {scrise} shard-uri · {pastrate} tokeni · {octeti / 1e6:.1f} MB")
    return {"acte": n_acte, "tokeni": pastrate, "shard_uri": scrise, "idx_octeti": octeti}
