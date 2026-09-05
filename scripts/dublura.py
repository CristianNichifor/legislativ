"""Does a new draft repeat a bill already moving through Parliament.

The linter asks whether a draft fights the law that exists. This asks the cheaper, earlier
question a drafter should ask first: is someone already doing this — should I amend their bill
rather than file a second one that duplicates it. Two initiatives that both amend article 7 of
Legea 98/2016 are not two ideas; they are one idea filed twice, and Parliament ends up
reconciling them by hand months later.

**The strong signal is the shared target, and it is deterministic.** `amendamente.py` already
reads what a text sets out to change — the act and the article. Run it over the new draft and
over each pending initiative's title and *obiect de reglementare*, and an overlap of targets is
the finding: not "these sound similar" but "both change art. 7 of the same law". That is
explainable, quotable, and needs no model — the property this whole package is built on.

**The weak signal is wording, and it is a fallback.** Two drafts can aim at the same problem
without citing the same article yet — one describes the mischief, the other the fix. Full-text
overlap on the *obiect* catches those, ranked below a target match and never presented as more
than a lead. It runs over the initiative FTS the collector already built.

**A dead bill is not a duplicate.** An initiative rejected or lapsed is history, not a conflict,
so `stadiu` is carried into every result and a caller filters on it: the point is to redirect a
drafter to a *live* bill to amend, not to a closed one to mourn.

Read-only throughout. This opens the corpus `mode=ro`, so it runs while the collectors are still
filling it — the duplicate-check is useful on the initiatives already landed and only gets more
complete as more arrive.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from scripts.amendamente import amendamente
from scripts.referinte import Act, referinte
from scripts.text import cheie

# Stages that mean a bill is no longer in play. Matched loosely because the portal phrases them
# in prose ("respins definitiv", "lege promulgată", "clasat").
STADII_MOARTE = ("respins", "clasat", "retras", "promulg", "caduc")

_CUVINTE_GOALE = frozenset(
    [
        "de",
        "la",
        "si",
        "in",
        "pe",
        "cu",
        "care",
        "sau",
        "al",
        "ale",
        "a",
        "un",
        "o",
        "prin",
        "din",
        "pentru",
        "privind",
        "modificarea",
        "completarea",
        "lege",
        "legea",
        "proiect",
        "propunere",
        "ordonanta",
        "hotarare",
    ]
)


@dataclass(frozen=True)
class Tinta:
    """One provision a text sets out to change: the act and, where given, the article."""

    act_id: str
    locator: str  # '' means the act as a whole

    def __str__(self) -> str:
        return f"{self.act_id} {self.locator}".strip()


@dataclass(frozen=True)
class Potrivire:
    """One pending initiative that may duplicate the draft, and why it matched."""

    plx_id: str
    senat_id: str | None
    titlu: str
    stadiu: str
    tinte_comune: tuple[str, ...]
    acte_comune: tuple[str, ...]
    scor_text: float
    in_viata: bool

    @property
    def motiv(self) -> str:
        if self.tinte_comune:
            return f"aceeași prevedere: {', '.join(self.tinte_comune)}"
        if self.acte_comune:
            return f"același act: {', '.join(self.acte_comune)}"
        return f"asemănare de text ({self.scor_text:.0%})"

    @property
    def increderea(self) -> str:
        """A shared provision is a verbatim fact about both texts; a shared act only, or a
        wording match, is derived — they touch the same law, perhaps not the same article."""
        return "verbatim" if self.tinte_comune else "derived"


def tinte(text: str, act_gazda: Act | None = None) -> set[str]:
    """Every provision a text sets out to change, as `act_id locator` strings.

    Amendments give the act and article directly; a bare reference to an act (no verb) is added
    as a whole-act target, because a draft that cites a law heavily is plausibly about that law
    even where the phrasing did not trip the amendment patterns.
    """
    gasite: set[str] = set()
    for a in amendamente(text, act_gazda=act_gazda):
        if a.act_tinta:
            gasite.add(str(Tinta(a.act_tinta.id, a.locator.id)))
    for r in referinte(text):
        if r.act is not None:
            gasite.add(str(Tinta(r.act.id, r.locator.id)))
    return gasite


def _termeni_cheie(text: str, maxim: int = 12) -> list[str]:
    """The content words of a title, for an FTS prefilter. Stopwords and short tokens dropped."""
    import re

    vazute: list[str] = []
    for cuvant in re.findall(r"[a-z0-9]+", cheie(text)):
        # Content words, plus the numeric tokens that carry the strongest signal an act number
        # and year — "98", "2016" — which split out of "98/2016" and match the same digits in a
        # candidate's obiect even when every surrounding word is phrased differently.
        cuvant_bun = (len(cuvant) > 3 and cuvant not in _CUVINTE_GOALE) or (
            cuvant.isdigit() and len(cuvant) >= 2
        )
        if cuvant_bun and cuvant not in vazute:
            vazute.append(cuvant)
    return vazute[:maxim]


def _candidate(con: sqlite3.Connection, draft: str) -> list[sqlite3.Row]:
    """Initiatives worth scoring: those sharing a content word with the draft, via FTS.

    A prefilter, not the answer — it narrows thousands of initiatives to a handful before the
    exact target comparison runs on each. An FTS OR-query over the draft's key terms.
    """
    termeni = _termeni_cheie(draft)
    if not termeni:
        return []
    # Each term is double-quoted so FTS reads it as a literal, not syntax: an act number like
    # "98/2016" carries a slash the FTS grammar would otherwise choke on.
    interogare = " OR ".join(f'"{t}"' for t in termeni)
    return con.execute(
        "SELECT i.plx_id, i.senat_id, i.titlu, i.obiect, i.stadiu"
        " FROM initiative_fts f JOIN initiative i ON i.plx_id = f.plx_id"
        " WHERE initiative_fts MATCH ? ORDER BY rank LIMIT 40",
        (interogare,),
    ).fetchall()


def _acte_din(tinte_set: set[str]) -> set[str]:
    """The act ids inside a set of `act_id locator` targets, dropping the locator."""
    return {t.split(" ")[0] for t in tinte_set}


def _viu(stadiu: str) -> bool:
    return not any(m in cheie(stadiu) for m in STADII_MOARTE)


def _scor_text(a: set[str], b: set[str]) -> float:
    """Jaccard over content words — a cheap, symmetric wording-overlap in [0, 1]."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dubluri(
    draft: str,
    con: sqlite3.Connection,
    *,
    act_gazda: Act | None = None,
    prag_text: float = 0.18,
    doar_vii: bool = True,
) -> list[Potrivire]:
    """Pending initiatives that may duplicate the draft, target matches first.

    A candidate surfaces if it shares a target with the draft (strong) or its wording overlaps
    above `prag_text` (weak). Target matches are ranked above wording matches, and both above
    nothing. `doar_vii` drops initiatives no longer in play, which is the default because the
    question is what to amend, not what to mourn.
    """
    tinte_draft = tinte(draft, act_gazda=act_gazda)
    cuvinte_draft = {w for w in cheie(draft).split() if len(w) > 3 and w not in _CUVINTE_GOALE}

    rezultate: list[Potrivire] = []
    for rand in _candidate(con, draft):
        viu = _viu(rand["stadiu"] or "")
        if doar_vii and not viu:
            continue
        text_cand = f"{rand['titlu']} {rand['obiect'] or ''}"
        tinte_cand = tinte(text_cand)
        comune = sorted(tinte_draft & tinte_cand)
        # Act-level overlap catches the common case the exact match misses: a draft amending
        # art. 7 of a law and an initiative amending the same law more broadly touch the same
        # act without sharing a locator. Ranked below an exact provision match, above wording.
        acte_comune = sorted(_acte_din(tinte_draft) & _acte_din(tinte_cand)) if not comune else []
        cuvinte_cand = {
            w for w in cheie(text_cand).split() if len(w) > 3 and w not in _CUVINTE_GOALE
        }
        scor = _scor_text(cuvinte_draft, cuvinte_cand)
        if not comune and not acte_comune and scor < prag_text:
            continue
        rezultate.append(
            Potrivire(
                plx_id=rand["plx_id"],
                senat_id=rand["senat_id"],
                titlu=rand["titlu"],
                stadiu=rand["stadiu"] or "",
                tinte_comune=tuple(comune),
                acte_comune=tuple(acte_comune),
                scor_text=round(scor, 3),
                in_viata=viu,
            )
        )
    # Exact provision first, then shared act, then wording. Each tier beats the next entirely.
    rezultate.sort(
        key=lambda p: (len(p.tinte_comune), len(p.acte_comune), p.scor_text), reverse=True
    )
    return rezultate


def raport(potriviri: list[Potrivire]) -> str:
    """The answer as a drafter reads it: amend one of these instead of filing anew."""
    if not potriviri:
        return "Nicio inițiativă în lucru nu pare să acopere acest proiect."
    linii = [f"{len(potriviri)} inițiativă(e) în lucru ar putea acoperi acest proiect:"]
    for p in potriviri:
        senat = f" · Senat {p.senat_id}" if p.senat_id else ""
        linii.append(f"  • {p.plx_id}{senat} — {p.motiv}")
        linii.append(f'      „{p.titlu[:90]}"')
        linii.append(f"      stadiu: {p.stadiu[:70]}")
    return "\n".join(linii)
