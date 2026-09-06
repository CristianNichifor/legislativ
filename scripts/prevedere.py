"""The text of a struck provision — what the Court actually removed from the law.

`lovituri` records *which* provision a decision struck, as a citation: `art. 5 alin. (7) din Legea
nr. 59/1993`, median 24 characters. That is enough to check whether a draft touches the same
place (`coliziune.py`), and nowhere near enough to check whether a draft **re-enacts the same
norm** — which is the question article 147 (4) actually poses, since the Court's rulings bind
identical provisions and not merely identical citations. For that, the words are needed.

The corpus does not hold them at article grain. Every collected document is one `provizii` row
with `locator = 'text'`: 152 079 whole documents, no article tree. The tree exists in the portal's
HTML (`parsare.py` reads its `S_ART`/`S_ALN`/`S_LIT` markers) but the collector stored the SOAP
service's plain text, which has none. So the text of a struck provision has to be recovered from
the containing act, and this module is that recovery — with the emphasis on what it refuses to do.

**Codes are keyed by version, and a strike belongs to the version then in force.** A decision from
1994 striking `art. 81 alin. 4 din Codul penal` is about the 1968 code, not the 2009 one. The
corpus keys those as `codul-penal-0-1969`, `codul-penal-0-1997`, `codul-penal-0-2004`,
`codul-penal-0-2014` — one per (re)publication — while `decizii.py` reads the citation as the
bare `cod-penal`. Resolution is therefore by date: the latest version published no later than the
strike. This alone takes the acts that resolve from 134 to 243 of 300.

**Pre-2000 alineate are gone from the stored text and are not guessed.** Older drafting numbers
alineate implicitly — `alin. 4` means the fourth paragraph, with no `(4)` marker — and the SOAP
text arrives with the paragraph breaks flattened away, so article 81 of the Penal Code is one
continuous string in which alineat 2 begins mid-sentence with no signal at all. Recovering `alin.
4` from that means guessing sentence boundaries, and a wrong guess publishes a fabricated
quotation attributed to a ruling of the Constitutional Court. So it is not attempted. Where the
alineat cannot be cut, the **containing article** is returned with `granularitate =
'articol'`, and every caller is expected to say which it got — a broader quotation honestly
labelled is useful; a precise-looking wrong one is not.

Coverage today, over the 300 distinct struck provisions that carry both an act and a locator:

    106  exact           — the cited unit itself
     98  articol         — the article around it; the alineat is not recoverable
     39  articol-negăsit — the act resolved, the article did not (renumbering, republication)
     57  act-negăsit     — no version of the act is in the corpus
    ---
    204  citable, of 300 (68%). Without the dated alias it is 47 (16%).

Exactness, not coverage, is what `surse.py` bought: storing the portal's own pages for the struck
acts moved 24 provisions from `articol` to `exact` while total coverage rose by six. A quotation of
the right paragraph is a different thing from a quotation of the article around it.

`acoperire()` recomputes this against whatever corpus it is given, because the numbers move as the
collection grows and a figure quoted from a docstring is a figure nobody rechecked.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from typing import Final

from scripts.parsare_text import parseaza_text

# `codul-penal-0-1997` — the corpus keys each (re)publication of a code as its own act, with the
# year of that publication in the id. The `0` is the (absent) number.
_VERSIUNE: Final[re.Pattern[str]] = re.compile(r"^(.*)-0-(\d{4})$")

_NIVELE: Final[tuple[str, ...]] = ("art", "alin", "lit", "pct")


@dataclass(frozen=True)
class Prevedere:
    """The recovered text of a struck provision, and how precisely it was recovered."""

    act_cerut: str
    act_gasit: str
    locator: str
    locator_gasit: str
    text: str
    cum: str  # direct | alias-datat
    granularitate: str  # exact | articol

    @property
    def este_exacta(self) -> bool:
        return self.granularitate == "exact"

    @property
    def nota(self) -> str:
        """What a reader has to be told before they quote this."""
        parti = []
        if self.cum == "alias-datat":
            parti.append(
                f"«{self.act_cerut}» a fost rezolvat, după data loviturii, la versiunea "
                f"{self.act_gasit}"
            )
        if self.granularitate == "articol":
            parti.append(
                f"textul este al articolului întreg ({self.locator_gasit}), nu al unității citate "
                f"({self.locator}): alineatele acestui act nu sunt marcate în textul colectat și "
                "nu se ghicesc"
            )
        return "; ".join(parti)


@dataclass(frozen=True)
class Neregasita:
    """A strike whose text the corpus cannot produce, and the reason — never a silent miss."""

    act_cerut: str
    locator: str
    motiv: str  # act-negasit | act-fara-text | articol-negasit | locator-nevalid

    @property
    def explicatie(self) -> str:
        return {
            "act-negasit": f"actul «{self.act_cerut}» nu este în corpus sub nicio versiune",
            "act-fara-text": f"actul «{self.act_cerut}» este în corpus, dar fără text",
            "articol-negasit": (
                f"articolul din «{self.locator}» nu se găsește în textul colectat al actului "
                "(renumerotare după republicare, ori structură nerecuperabilă din text)"
            ),
            "locator-nevalid": f"locatorul «{self.locator}» nu are o formă interpretabilă",
        }.get(self.motiv, self.motiv)


def versiuni(con: sqlite3.Connection) -> dict[str, list[tuple[int, str]]]:
    """Act ids grouped by their versionless prefix, ascending by year.

    Built once per run rather than queried per strike: it is one pass over `acte.id` against 300
    lookups, and the per-strike alternative was a `LIKE` scan of a quarter-million rows.
    """
    pe_prefix: dict[str, list[tuple[int, str]]] = {}
    for (cheie,) in con.execute("SELECT id FROM acte"):
        m = _VERSIUNE.match(cheie)
        if m:
            pe_prefix.setdefault(m.group(1), []).append((int(m.group(2)), cheie))
    for lista in pe_prefix.values():
        lista.sort()
    return pe_prefix


def _prefixe_posibile(act: str) -> list[str]:
    """How a code cited as `cod-penal` might be keyed in the corpus.

    `decizii.py` normalises every code citation to `cod-<nume>`; the corpus keys them as the
    portal titles them — `codul-penal`, `codul-de-procedura-penala`. Both spellings are tried, the
    fuller one first, and a non-code act produces nothing: an ordinary law is keyed by number and
    year and needs no alias.
    """
    if not act.startswith("cod-"):
        return []
    rest = act[len("cod-") :]
    candidati = [f"codul-{rest}", f"cod-{rest}"]
    if rest.startswith("procedura-"):
        candidati = [f"codul-de-{rest}", f"cod-de-{rest}", *candidati]
    return candidati


def rezolva_act(
    con: sqlite3.Connection, index: dict[str, list[tuple[int, str]]], act: str, an: int | None
) -> tuple[str | None, str]:
    """Which act in the corpus a strike's citation names, at the time of the strike."""
    if con.execute("SELECT 1 FROM acte WHERE id = ?", (act,)).fetchone():
        return act, "direct"
    for prefix in _prefixe_posibile(act):
        lista = index.get(prefix)
        if not lista:
            continue
        if an is None:
            # No date on the decision — the latest version is the least-bad guess, and `cum`
            # records that this was an alias so the caller can say so.
            return lista[-1][1], "alias-datat"
        anterioare = [cheie for anul, cheie in lista if anul <= an]
        # A strike predating every collected version still belongs to the earliest one: the code
        # existed, only its republications postdate the ruling.
        return (anterioare[-1] if anterioare else lista[0][1]), "alias-datat"
    return None, ""


def _parti(locator: str) -> list[tuple[str, str]] | None:
    """`art5.alin7.litd` → [('art','5'), ('alin','7'), ('lit','d')]."""
    iesire: list[tuple[str, str]] = []
    for parte in locator.split("."):
        for nivel in _NIVELE:
            if parte.startswith(nivel):
                iesire.append((nivel, parte[len(nivel) :]))
                break
        else:
            return None
    return iesire or None


def _text_complet(nod: dict) -> str:
    """A unit's whole text: its own words plus those of everything under it.

    `parsare_text` puts an article's lead-in in `text` and its alineate in `copii`, so a modern
    article — where every word lives in an alineat — has an empty `text` of its own. Reading that
    as "not found" reported the article missing from an act that plainly contains it; reading it as
    the empty string quoted nothing. The text of article 5 is article 5, paragraphs included.
    """
    parti = [(nod.get("text") or "").strip()]
    parti += [_text_complet(c) for c in nod.get("copii", ())]
    return "\n".join(p for p in parti if p)


def _intregul(randuri: list[str]) -> str:
    """The whole unit, where several rows carry its locator.

    `parsare.py` files an `S_ART` and each of its `S_ALN` children under the same locator, so
    `art3` arrives as three rows: alineat (1), alineat (2), and the article containing both. The
    longest is the one that contains the others — and picking the *first* instead, as this did
    before it was measured, returns alineat (1)'s words under the article's name, which is the one
    thing this module exists not to do.
    """
    return max(randuri, key=len)


def _alineatul(randuri: list[str], coada: str) -> str | None:
    """The row that is the cited alineat, identified by the `(N)` marker it opens with."""
    m = re.fullmatch(r"alin(\d+)", coada)
    if not m:
        return None
    inceput = re.compile(rf"^\s*\(\s*{re.escape(m.group(1))}\s*\)")
    potrivite = [r for r in randuri if inceput.match(r)]
    # Exactly one row may claim it. Two would mean the article repeats a paragraph number, which
    # is a parse fault, and choosing between them would be a guess.
    return potrivite[0] if len(potrivite) == 1 else None


def _descinde(noduri: list[dict], parti: list[tuple[str, str]]) -> tuple[str | None, list[str]]:
    """Walk as far down a node list as the locator's parts actually go."""
    text, atins = None, []
    for nivel, numar in parti:
        gasit = next(
            (n for n in noduri if n["nivel"] == nivel and n["numar"].lower() == numar.lower()),
            None,
        )
        if gasit is None:
            break
        text, noduri = _text_complet(gasit), gasit["copii"]
        atins.append(f"{nivel}{numar}")
    return text, atins


def _mai_adanc(text: str, parti: list[tuple[str, str]]) -> str | None:
    """Cut deeper inside a unit's own text, when the structured tree stops above it.

    The two sources fail in opposite places. The portal's markup marks articles for acts whose
    alineate it does not mark; the flattened SOAP text lost the articles but kept the `(2)` a
    drafter typed. So an article that came from `S_ART` with no `S_ALN` children can still yield
    its alineat by reading its own words — which is exactly what `parsare_text` is for. Without
    this, structuring an act would trade an exact quotation for a broader one, and an upgrade that
    loses precision on any provision is not an upgrade.
    """
    arbore = parseaza_text(text)
    # `parseaza_text` wraps a headingless body in one unnamed article; the units are its children.
    for radacina in (arbore["noduri"], *(n["copii"] for n in arbore["noduri"])):
        sub, atins = _descinde(radacina, parti)
        if sub and len(atins) == len(parti):
            return sub
    return None


def taie(arbore: dict, locator: str) -> tuple[str | None, str, str]:
    """Cut a locator out of a parsed act. Returns (text, locator reached, granularity).

    Descends as far as the tree actually goes and stops rather than inventing: an article whose
    alineate were flattened out of the source has no children, so `art5.alin7` yields the article's
    text at `art5` and says `articol`. It never returns text from a different unit than the one it
    names.
    """
    parti = _parti(locator)
    if parti is None:
        return None, "", ""

    noduri, text, atins = arbore["noduri"], None, []
    for nivel, numar in parti:
        gasit = next(
            (n for n in noduri if n["nivel"] == nivel and n["numar"].lower() == numar.lower()),
            None,
        )
        if gasit is None:
            break
        text, noduri = _text_complet(gasit), gasit["copii"]
        atins.append(f"{nivel}{numar}")

    if not atins or not (text or "").strip():
        return None, "", ""
    return text, ".".join(atins), ("exact" if len(atins) == len(parti) else "articol")


def textul(
    con: sqlite3.Connection,
    act: str,
    locator: str,
    an: int | None,
    index: dict[str, list[tuple[int, str]]] | None = None,
) -> Prevedere | Neregasita:
    """The text of one struck provision, or a stated reason why the corpus cannot give it."""
    index = versiuni(con) if index is None else index
    if _parti(locator) is None:
        return Neregasita(act, locator, "locator-nevalid")

    gasit, cum = rezolva_act(con, index, act, an)
    if gasit is None:
        return Neregasita(act, locator, "act-negasit")

    # An act whose page was stored (`surse.py`) has its real tree in `provizii`, read from the
    # portal's own `S_ART`/`S_ALN`/`S_LIT` markers. Ask for the unit directly: one indexed lookup
    # instead of parsing a megabyte of flattened text, and right rather than recovered. Acts still
    # on the SOAP text fall through to the parse below.
    randuri = [
        r[0]
        for r in con.execute(
            "SELECT text FROM provizii WHERE act_id = ? AND locator = ? ORDER BY ord",
            (gasit, locator),
        )
        if (r[0] or "").strip()
    ]
    if randuri:
        return Prevedere(act, gasit, locator, locator, _intregul(randuri), cum, "exact")

    rand = con.execute(
        "SELECT text FROM provizii WHERE act_id = ? AND locator = 'text' LIMIT 1", (gasit,)
    ).fetchone()
    if rand is None or not (rand[0] or "").strip():
        # Structured but without this unit: the act has an article tree and the cited locator is
        # not in it. Widening to the containing article is still honest and still useful.
        parinte = locator.rsplit(".", 1)[0] if "." in locator else ""
        if parinte:
            sus = [
                r[0]
                for r in con.execute(
                    "SELECT text FROM provizii WHERE act_id = ? AND locator = ? ORDER BY ord",
                    (gasit, parinte),
                )
                if (r[0] or "").strip()
            ]
            if sus:
                coada = locator[len(parinte) + 1 :]
                # The alineate are present, just not separately addressed: `parsare.py` files each
                # `S_ALN` under its article's locator, so `art3` holds alineat (1), alineat (2) and
                # the whole article as three rows. The `(N)` a drafter typed is on the front of the
                # right one, which makes the exact unit recoverable rather than approximated.
                exact = _alineatul(sus, coada) or _mai_adanc(_intregul(sus), _parti(coada) or [])
                if exact:
                    return Prevedere(act, gasit, locator, locator, exact, cum, "exact")
                return Prevedere(act, gasit, locator, parinte, _intregul(sus), cum, "articol")
        # No flattened row means the act was structured from its page, so its tree is authoritative:
        # a locator missing from it is a missing article, not a missing act. Only an act carrying no
        # provisions at all has no text.
        are_ceva = con.execute(
            "SELECT 1 FROM provizii WHERE act_id = ? LIMIT 1", (gasit,)
        ).fetchone()
        return Neregasita(act, locator, "articol-negasit" if are_ceva else "act-fara-text")

    text, atins, granularitate = taie(parseaza_text(rand[0]), locator)
    if text is None:
        return Neregasita(act, locator, "articol-negasit")
    return Prevedere(act, gasit, locator, atins, text, cum, granularitate)


def acoperire(cale_db: str = "corpus.db", *, log=print) -> dict:
    """What share of the register the corpus can actually quote, recomputed rather than quoted.

    The figures move as the collection grows, and a coverage number copied into prose is a number
    nobody rechecks. Every report that leans on this text should be able to print this.
    """
    cx = sqlite3.connect(f"file:{cale_db}?mode=ro", uri=True)
    try:
        index = versiuni(cx)
        randuri = cx.execute(
            "SELECT DISTINCT act, locator, publicat FROM lovituri "
            "WHERE act IS NOT NULL AND locator != ''"
        ).fetchall()
        numar = {"total": len(randuri), "exact": 0, "articol": 0}
        for act, locator, publicat in randuri:
            an = int(publicat[:4]) if publicat else None
            r = textul(cx, act, locator, an, index)
            cheie = r.granularitate if isinstance(r, Prevedere) else r.motiv
            numar[cheie] = numar.get(cheie, 0) + 1
        citabile = numar["exact"] + numar["articol"]
        numar["citabile"] = citabile
        numar["procent_citabile"] = round(100 * citabile / max(numar["total"], 1))
        log(
            f"{numar['total']} prevederi lovite distincte · {citabile} citabile "
            f"({numar['procent_citabile']}%): {numar['exact']} exact, {numar['articol']} la articol"
        )
        return numar
    finally:
        cx.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--act", help="o singură prevedere: cheia actului, ex. cod-penal")
    ap.add_argument("--locator", help="ex. art81.alin4")
    ap.add_argument("--an", type=int, help="anul loviturii, pentru versiunea corectă a codului")
    args = ap.parse_args()

    if args.act and args.locator:
        cx = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            r = textul(cx, args.act, args.locator, args.an)
        finally:
            cx.close()
        if isinstance(r, Neregasita):
            print(f"negăsită: {r.explicatie}")
            return 1
        print(f"{r.act_gasit} {r.locator_gasit} [{r.granularitate}]")
        if r.nota:
            print(f"⚠ {r.nota}")
        print(f"\n{r.text.strip()[:1500]}")
        return 0

    numar = acoperire(args.db)
    for cheie in ("act-negasit", "act-fara-text", "articol-negasit", "locator-nevalid"):
        if numar.get(cheie):
            print(f"  {cheie}: {numar[cheie]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
