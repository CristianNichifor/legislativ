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
from pathlib import Path

from scripts import depozit
from scripts.cauta_web import _tokenuri

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
            "SELECT id, tip, numar, an, titlu, sursa_url FROM acte ORDER BY an DESC, numar"
        ).fetchall()
        index = [
            {
                "id": r["id"],
                "tip": r["tip"],
                "numar": r["numar"],
                "an": r["an"],
                "titlu": r["titlu"] or "",
                "url": r["sursa_url"] or "",
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
                        "url": r["sursa_url"] or "",
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
        shards.setdefault(t[:2], {})[t] = posting
    for prefix, continut in shards.items():
        (baza / "idx" / f"{prefix}.json").write_text(
            json.dumps(continut, ensure_ascii=False), encoding="utf-8"
        )

    manifest = {
        "acte": n_acte,
        "provizii": n_provizii,
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
