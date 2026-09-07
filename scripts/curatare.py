"""One-off repairs to text already collected.

New collection is clean at the point of writing; this is for the corpus that already exists. Kept
as its own command rather than folded into the daily refresh, because a migration that runs itself
on a schedule is one nobody can decide not to run.

**The service's block separator.** The SOAP endpoint marks a boundary with a lone `+` on its own
line — after the header, before `Articolul UNIC`, after the enacting formula. 125 669 of the
151 947 documents carry at least one, and it is the only single-character line the service emits;
the HTML the portal serves for the same document has none, which is what identified it as an
artifact of the transport rather than part of the law. Left in, it renders inside quotations as
though the Monitorul Oficial had printed a `+`, and it goes into the context a model is asked to
quote from verbatim.

Only the derived copy is touched. `documente.text` keeps exactly what the service returned, because
a marker deleted from the archive could not be recovered, and the archive is the one thing in this
package that has to stay re-readable.

**The byte-order mark in titles.** 91 650 of 152 079 titles — 60% — begin with U+FEFF and a space.
It is not whitespace to Python, so `.strip()` walks up to it and stops, and the title sorts ahead
of every clean one and renders indented. `normalizeaza` now removes it, so new collection is clean;
`titluri` is for what is already written, and decodes the 179 titles carrying raw HTML entities in
the same pass.
"""

from __future__ import annotations

import argparse
import gzip
import html
import re
import time
from dataclasses import dataclass

from scripts import depozit
from scripts.text import cheie, fara_separatoare, normalizeaza


@dataclass(frozen=True)
class Curatare:
    examinate: int
    schimbate: int
    secunde: float
    subiect: str = "provizii"

    def __str__(self) -> str:
        return (
            f"{self.examinate} {self.subiect} examinate · {self.schimbate} curățate · "
            f"{self.secunde:.0f}s"
        )


def separatoare(cale_db: str = "corpus.db", *, lot: int = 5000, log=print) -> Curatare:
    """Remove the service's block markers from the provisions derived from its text.

    Only `locator = 'text'` rows: those are the ones the SOAP endpoint produced. Provisions parsed
    from the portal's HTML (`surse.imbogateste`) never carried the marker — 0 of 44 059 — so
    touching them would be a rewrite with nothing to fix.

    The index is rebuilt once at the end rather than row by row. `provizii_fts` is external
    content, so each edit would otherwise be a withdraw-and-reinsert against the old values, and
    125 669 of those cost more than reading the table again.
    """
    t0 = time.monotonic()
    examinate = schimbate = 0
    with depozit.deschide(cale_db) as con:
        # Row ids first, text in batches. A document runs to tens of kilobytes and 125 669 of them
        # are affected, so selecting `text` for all of them at once is several gigabytes resident
        # before a single row is written — a corpus-wide `fetchall` has cost this project 4.36 GB
        # once already.
        ids = [
            r[0]
            for r in con.execute(
                "SELECT rowid FROM provizii WHERE locator = 'text'"
                " AND text LIKE '%' || char(10) || '+%'"
            )
        ]
        log(f"{len(ids)} provizii cu marcaj de separator")
        for start in range(0, len(ids), lot):
            felie = ids[start : start + lot]
            semne = ",".join("?" * len(felie))
            for rowid, text in con.execute(
                f"SELECT rowid, text FROM provizii WHERE rowid IN ({semne})", felie
            ).fetchall():
                examinate += 1
                curatat = fara_separatoare(text)
                if curatat != text:
                    con.execute("UPDATE provizii SET text = ? WHERE rowid = ?", (curatat, rowid))
                    schimbate += 1
            con.commit()
            log(f"  {examinate}/{len(ids)} · {schimbate} curățate")
        if schimbate:
            log("reconstruiesc indexul de căutare…")
            con.execute("INSERT INTO provizii_fts(provizii_fts) VALUES('rebuild')")
            con.commit()
    return Curatare(examinate, schimbate, time.monotonic() - t0)


def titluri(cale_db: str = "corpus.db", *, lot: int = 20000, log=print) -> Curatare:
    """Re-normalise stored titles: strip the byte-order mark, decode the HTML entities.

    Two defects, one pass. `normalizeaza` now removes U+FEFF, so new collection is clean; this is
    for the 91 650 titles — 60% of the corpus — already written with one. They render with a
    leading space and sort ahead of every clean title, because a BOM is not whitespace and
    `.strip()` stops at it.

    **The entities are decoded here and not in `normalizeaza`.** 179 titles carry raw markup —
    `&#9675;DECRET nr. 784`, `&nbsp;`, `&lt;` — and `html.unescape` is not idempotent: applied
    twice, `&amp;lt;` becomes `<` where once it gives `&lt;`. `normalizeaza` is documented as safe
    to run twice, and text passes through it on the way in *and* on the way into a matcher, so
    putting a one-way transform inside it would corrupt any title that legitimately spells an
    ampersand. A migration runs once by construction, which is where a one-way fix belongs.

    Both `acte` and `documente` are updated. `acte` is what a reader sees; `documente` is what
    `nomenclator.alias_an` reads titles from to confirm an act's year, and leaving it dirty would
    keep that check comparing against a string the rest of the corpus no longer uses.

    No index maintenance: `provizii_fts` indexes provision text, and titles are not in it.
    """
    t0 = time.monotonic()
    examinate = schimbate = 0
    with depozit.deschide(cale_db) as con:
        for tabel, cheie in (("acte", "id"), ("documente", "id_portal")):
            ids = [
                r[0]
                for r in con.execute(
                    f"SELECT {cheie} FROM {tabel} WHERE titlu LIKE char(65279) || '%'"
                    " OR titlu LIKE '%&' || '#%;%' OR titlu LIKE '%&' || 'nbsp;%'"
                    " OR titlu LIKE '%&' || 'amp;%' OR titlu LIKE '%&' || 'lt;%'"
                    " OR titlu LIKE '%&' || 'gt;%' OR titlu LIKE '%&' || 'quot;%'"
                )
            ]
            log(f"{tabel}: {len(ids)} titluri de curățat")
            for start in range(0, len(ids), lot):
                felie = ids[start : start + lot]
                semne = ",".join("?" * len(felie))
                for id_, titlu in con.execute(
                    f"SELECT {cheie}, titlu FROM {tabel} WHERE {cheie} IN ({semne})", felie
                ).fetchall():
                    examinate += 1
                    curatat = normalizeaza(html.unescape(titlu or ""))
                    if curatat and curatat != titlu:
                        con.execute(
                            f"UPDATE {tabel} SET titlu = ? WHERE {cheie} = ?", (curatat, id_)
                        )
                        schimbate += 1
                con.commit()
                log(f"  {examinate} examinate · {schimbate} curățate")
    return Curatare(examinate, schimbate, time.monotonic() - t0, "titluri")


_EMT_BDY = re.compile(r'class="S_EMT_BDY"[^>]*>(.*?)</span>', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _emitent_din_pagina(pagina: str) -> str | None:
    m = _EMT_BDY.search(pagina)
    return " ".join(normalizeaza(_TAG.sub(" ", m.group(1))).split()) if m else None


def repara_emitent(stricat: str, curat: str) -> str | None:
    """`stricat` with each `?` replaced by the letter the page has in that position.

    Word by word rather than over the whole string, because the two spellings differ in more than
    the lost letters: the page writes `AGENŢIA NAŢIONALA DE PRIVATIZARE` where the service returns
    `Agen?ia Na?ională de Privatizare`, upper case and missing a diacritic of its own. Each damaged
    word is matched against the page's words diacritic-folded, with `?` standing for any character,
    and only the `?` positions are taken from the match — so the service's own capitalisation
    survives and nothing else about the name is rewritten.

    `None` where any damaged word finds no match, which is the answer for a page that names a
    different body: `Agen?ia Na?ională a Func?ionarilor Publici` is published on a page headed
    `MINISTERUL ADMINISTRAȚIEI ȘI INTERNELOR-AGENTIA NAȚIONALĂ...`, and half a repair is worse than
    none.

    **The case of a destroyed first letter cannot be recovered** and is not guessed at: a word
    starting `?` takes the lower-case letter unless the whole word is capitals or it follows a
    hyphen inside a capitalised name. That is right for the common case by a wide margin — the
    conjunction `și` is the most frequent word-initial `?` in the corpus — and wrong for a handful
    of proper names such as `Academia de ?tiin?e`, which come back with a lower-case `ș`.
    """
    cuvinte_curate = curat.split()
    iesire: list[str] = []
    for cuv in stricat.split():
        if "?" not in cuv:
            iesire.append(cuv)
            continue
        tipar = re.compile("^" + re.escape(cheie(cuv)).replace(r"\?", ".") + "$")
        gasit = next((c for c in cuvinte_curate if tipar.match(cheie(c))), None)
        if not gasit or len(gasit) != len(cuv):
            return None
        litere = []
        for i, ch in enumerate(cuv):
            if ch != "?":
                litere.append(ch)
                continue
            sus = cuv.isupper() or (i > 0 and cuv[i - 1] == "-" and cuv[:i].istitle())
            litere.append(gasit[i].upper() if sus else gasit[i].lower())
        iesire.append("".join(litere))
    reparat = " ".join(iesire)
    return reparat if "?" not in reparat else None


def emitenti(cale_db: str = "corpus.db", *, log=print) -> Curatare:
    """Put the `ș` and `ț` back into the issuer names the service could not spell.

    The API encodes its responses in a charset that has no comma-below letters and emits a literal
    `?` for each — not U+FFFD, so nothing downstream can tell it from a question mark somebody
    typed. 113 910 documents carry an issuer damaged that way, 55% of the corpus, across 344 of the
    488 distinct names: `Ministerul Sănătă?ii`, `Pre?edintele României`, `Curtea Constitu?ională`.

    The repair is read, not inferred. Each damaged name is matched against the `S_EMT_BDY` heading
    of a page belonging to that issuer, which the portal serves in a charset that can spell it. An
    issuer with no stored page keeps its damaged name and is counted as unrepaired, because there
    is nothing to read it from.

    Measured on the collected corpus: 221 of the 344 names repair, covering 110 044 of the 113 910
    damaged documents — 96,6%. The 123 that do not are mostly issuers whose every document predates
    the HTML collection.

    Both `acte` and `documente` are updated, and the act ids are deliberately untouched: they carry
    the portal's document id rather than a slug of the name, precisely so that this pass cannot
    make a stored reference dangle.
    """
    t0 = time.monotonic()
    examinate = schimbate = 0
    with depozit.deschide(cale_db) as con:
        stricati = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT emitent FROM documente WHERE emitent LIKE ?", ("%?%",)
            )
        ]
        log(f"{len(stricati)} emitenți stricați")
        for em in stricati:
            examinate += 1
            rand = con.execute(
                "SELECT s.html FROM documente d JOIN surse s ON s.id_portal = d.id_portal"
                " WHERE d.emitent = ? AND s.html IS NOT NULL LIMIT 1",
                (em,),
            ).fetchone()
            if not rand:
                continue
            curat = _emitent_din_pagina(gzip.decompress(rand[0]).decode("utf-8", "replace"))
            reparat = repara_emitent(em, curat) if curat else None
            if not reparat or reparat == em:
                continue
            con.execute("UPDATE documente SET emitent = ? WHERE emitent = ?", (reparat, em))
            con.execute("UPDATE acte SET emitent = ? WHERE emitent = ?", (reparat, em))
            schimbate += 1
            if schimbate % 25 == 0:
                con.commit()
                log(f"  {examinate}/{len(stricati)} · {schimbate} reparați")
        con.commit()
    log(f"gata: {schimbate} din {examinate} emitenți reparați")
    return Curatare(examinate, schimbate, time.monotonic() - t0, "emitenti")


def restaureaza_text(cale_db: str = "corpus.db", *, prag: float = 0.98, lot: int = 500, log=print):
    """Put back the text an over-eager enrichment threw away.

    `surse.imbogateste` replaced an act's flattened row with whatever its HTML page parsed to, and
    guarded that with `len(provizii) <= 1` — a count, not a measurement. A page yielding three
    empty preamble paragraphs passes a count check, so the Codul vamal went from 79 865 characters
    to 95: `privind Codul vamal al României` and two more header fragments. Measured after the
    first full run, 54% of enriched acts held less text than the archive.

    Recovery is possible only because `documente.text` is never rewritten. That is the whole point
    of keeping the archive separate from the derived copy, and this is the first time it has had to
    pay for itself.

    An act whose provisions total less than `prag` of its archived text is put back the way
    collection wrote it: one row, `locator = 'text'`, the archive with the service's block markers
    removed. That is not a repair to the article tree — the tree is simply gone for those acts and
    a corrected `imbogateste` run has to rebuild it — but it restores every act to searchable,
    quotable text, which is strictly better than the fragments it holds now.
    """
    from scripts.parsare import Provizie

    t0 = time.monotonic()
    examinate = schimbate = 0
    with depozit.deschide(cale_db) as con:
        # One scan, then repair by id. The comparison is a correlated aggregate per act, so it is
        # done once for the whole corpus rather than per candidate inside the repair loop.
        stricate = [
            r[0]
            for r in con.execute(
                "SELECT a.id FROM acte a JOIN documente d ON d.id_portal = a.id_portal"
                " WHERE d.text IS NOT NULL AND length(d.text) > 0"
                " AND (SELECT sum(length(p.text)) FROM provizii p WHERE p.act_id = a.id)"
                "     < length(d.text) * ?",
                (prag,),
            )
        ]
        log(f"{len(stricate)} acte cu mai puțin text decât arhiva")
        for start in range(0, len(stricate), lot):
            for act_id in stricate[start : start + lot]:
                examinate += 1
                rand = con.execute(
                    "SELECT d.text FROM documente d JOIN acte a ON a.id_portal = d.id_portal"
                    " WHERE a.id = ?",
                    (act_id,),
                ).fetchone()
                if not rand or not rand[0]:
                    continue
                depozit.scrie_provizii(con, act_id, [Provizie("text", fara_separatoare(rand[0]))])
                schimbate += 1
            con.commit()
            log(f"  {examinate}/{len(stricate)} · {schimbate} restaurate")
    return Curatare(examinate, schimbate, time.monotonic() - t0, "acte")


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument(
        "--restaureaza-text",
        action="store_true",
        help="pune la loc textul actelor pe care îmbogățirea l-a pierdut (din arhiva documente)",
    )
    ap.add_argument(
        "--titluri",
        action="store_true",
        help="curăță titlurile (BOM, entități HTML) în loc de separatoarele din provizii",
    )
    ap.add_argument(
        "--emitenti",
        action="store_true",
        help="pune la loc ș și ț în numele emitenților, citite din paginile lor",
    )
    a = ap.parse_args()
    if a.restaureaza_text:
        print(f"\ngata: {restaureaza_text(a.db)}")
    elif a.emitenti:
        print(f"\ngata: {emitenti(a.db)}")
    else:
        print(f"\ngata: {titluri(a.db) if a.titluri else separatoare(a.db)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
