"""Obligations a law places on someone, with a clock attached.

Romanian primary legislation habitually delegates its own operation: the law sets the rule and
then instructs the Government or a minister to issue the norms that make it work, within a
stated number of days. That sentence is the most mechanically checkable thing in the entire
corpus. It names an institution, an instrument and a deadline, and whether the instrument was
ever issued is a fact about the corpus rather than a judgement about it.

**This is why the linter's best output needs no model at all.** A contradiction between two
articles is an interpretation, and interpretations from a small language model over legal
Romanian are the least trustworthy thing this package could emit. An implementing act that a
law required within 30 days and that does not exist eight years later is arithmetic — it can be
put in front of a committee with the article number, the date and the search that failed, and
argued with on those terms. `vid.py` does that arithmetic; this module reads the sentences.

**The deadline runs from an anchor, and the anchor is not always the same date.** `de la data
intrării în vigoare` and `de la data publicării în Monitorul Oficial` differ by however long the
act's own vacatio legis is — three days by default under the Constitution, but frequently a
named later date, and for some acts the two are months apart. Recording which anchor was
written, rather than collapsing both to publication, is the difference between an overdue
finding that survives being checked and one that does not.

**What is deliberately not inferred: whether an obligation was discharged.** This module reports
that Legea X, article 12, required norms within 30 days of entry into force. It does not decide
that they never came — the corpus does, in `vid.py`, and only for the acts actually loaded. An
absent implementing act and an implementing act nobody has ingested look identical from inside
the graph, and conflating them would let the linter announce a legislative gap that is really a
gap in the scrape. That distinction is carried explicitly, as a limitation, all the way to the
finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from scripts.referinte import Act, Locator
from scripts.text import cheie, normalizeaza

LUNI: Final[dict[str, int]] = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

# Small numbers are written out as often as they are typed as digits, and `un an` has no digit
# at all. The map stops where legal drafting stops using words.
NUMERALE: Final[dict[str, int]] = {
    "un": 1,
    "una": 1,
    "o": 1,
    "doi": 2,
    "două": 2,
    "doua": 2,
    "trei": 3,
    "patru": 4,
    "cinci": 5,
    "șase": 6,
    "sase": 6,
    "șapte": 7,
    "sapte": 7,
    "opt": 8,
    "nouă": 9,
    "noua": 9,
    "zece": 10,
    "cincisprezece": 15,
    "douăzeci": 20,
    "douazeci": 20,
    "treizeci": 30,
    "șaizeci": 60,
    "saizeci": 60,
    "nouăzeci": 90,
    "nouazeci": 90,
}

# Months are 30 days and a year is 365. Declared rather than calendar-exact: a deadline stated
# in months is administrative, and the arithmetic is reported as derived wherever it is shown.
ZILE_PE_UNITATE: Final[dict[str, int]] = {
    "zi": 1,
    "zile": 1,
    "luna": 30,
    "luni": 30,
    "an": 365,
    "ani": 365,
}

_CANTITATE = (
    r"(?P<cantitate>\d{1,4}|[a-zăâîșț]+)\s*(?:de\s+)?"
    r"(?P<unitate>zile|zi|luni|lun(?:ă|a)|ani|an)\b"
)
_TERMEN = re.compile(rf"(?:în|in)\s+termen\s+de\s+{_CANTITATE}", re.IGNORECASE)
_CEL_TARZIU = re.compile(
    r"(?:cel\s+(?:mai\s+)?t(?:â|a)rziu\s+)?p(?:â|a)n(?:ă|a)\s+la\s+(?:data\s+de\s+)?"
    r"(?P<zi>\d{1,2})\s+(?P<luna>[a-zăâîșț]+)\s+(?P<an>(?:19|20)\d{2})",
    re.IGNORECASE,
)

ANCORE: Final[list[tuple[str, str]]] = [
    ("vigoare", r"(?:de\s+la\s+)?(?:data\s+)?intr(?:ă|a)rii\s+(?:în|in)\s+vigoare"),
    (
        "publicare",
        r"(?:de\s+la\s+)?(?:data\s+)?public(?:ă|a)rii"
        r"(?:\s+(?:în|in)\s+Monitorul\s+Oficial)?",
    ),
]
_ANCORE = re.compile("|".join(rf"(?P<{n}>{s})" for n, s in ANCORE), re.IGNORECASE)

INSTRUMENTE: Final[list[tuple[str, str, str]]] = [
    ("norme-metodologice", "hg", r"norm(?:e|ele)\s+metodologice"),
    ("hotarare", "hg", r"hot(?:ă|a)r(?:â|a)re\s+a\s+Guvernului|hot(?:ă|a)r(?:â|a)rea\s+Guvernului"),
    # The lookahead separates an order being *required* from an order being *cited*: an
    # obligation says `emite ordinul de aplicare`, a citation says `Ordinul ... nr. 1.802/2014`.
    # Without it every sentence that merely mentions an existing order acquires a fake deadline.
    ("ordin", "ordin", r"ordin(?:ul|e|ele)?\b(?![^.\n]{0,60}\bnr\.)"),
    ("regulament", "hg", r"regulament(?:ul)?\s+de\s+(?:aplicare|organizare)"),
    ("procedura", "ordin", r"procedur(?:a|ă)\s+de\s+(?:aplicare|punere\s+(?:în|in)\s+aplicare)"),
    ("metodologie", "hg", r"metodologi(?:a|e)\s+de\s+(?:aplicare|calcul)"),
]
_INSTRUMENTE = re.compile(
    "|".join(rf"(?P<{n.replace('-', '_')}>{s})" for n, _, s in INSTRUMENTE), re.IGNORECASE
)

INSTITUTII: Final[list[tuple[str, str]]] = [
    ("guvern", r"Guvernul(?:\s+Rom(?:â|a)niei)?"),
    ("minister", r"Ministerul\s+[A-ZĂÂÎȘȚ][^,;.\n]{2,60}"),
    ("ministru", r"ministrul\s+[a-zăâîșț][^,;.\n]{2,60}"),
    (
        "autoritate",
        r"(?:Autoritatea|Agenția|Agentia|Oficiul|Institutul|Casa)\s+[A-ZĂÂÎȘȚ][^,;.\n]{2,60}",
    ),
    ("consilii-locale", r"consiliile\s+(?:locale|jude(?:ț|t)ene)"),
]
_INSTITUTII = re.compile("|".join(rf"(?P<{n.replace('-', '_')}>{s})" for n, s in INSTITUTII))


@dataclass(frozen=True)
class Obligatie:
    """A duty to issue something, by a time, stated in a provision."""

    act: Act | None
    locator: Locator
    institutie: str | None
    institutie_text: str | None
    instrument: str | None
    tip_asteptat: str | None
    termen_zile: int | None
    ancora: str
    data_limita: date | None
    text: str

    def scadenta(self, vigoare: date | None = None, publicare: date | None = None) -> date | None:
        """When the instrument was due. `None` when the host act's own dates are unknown.

        Returning `None` rather than guessing an anchor date is the whole discipline: an
        overdue count computed from an assumed entry-into-force is a number that looks checkable
        and is not.
        """
        if self.data_limita is not None:
            return self.data_limita
        if self.termen_zile is None:
            return None
        baza = publicare if self.ancora == "publicare" else vigoare
        return baza + timedelta(days=self.termen_zile) if baza else None


def _cantitate(brut: str) -> int | None:
    brut = brut.strip().lower()
    if brut.isdigit():
        return int(brut)
    return NUMERALE.get(cheie(brut))


def _prima(regex: re.Pattern[str], text: str, nume: list[str]) -> tuple[str | None, str | None]:
    m = regex.search(text)
    if m is None:
        return None, None
    grup = next(n for n in nume if m.group(n.replace("-", "_")) is not None)
    return grup, m.group(0).strip()


def obligatii(text: str, act: Act | None = None, locator: Locator | None = None) -> list[Obligatie]:
    """Every dated obligation stated in the passage.

    One obligation per sentence that carries a deadline. A sentence with a deadline but no
    recognisable instrument is still returned, with `instrument=None`: the deadline is real and
    an unrecognised instrument is this module's gap, not the law's, so dropping the sentence
    would hide a miss behind a smaller-looking result.
    """
    text = normalizeaza(text)
    gasite: list[Obligatie] = []
    for frazǎ in re.split(r"(?<!\bart)(?<!\balin)(?<!\bnr)(?<!\blit)\.\s+", text):
        termen = _TERMEN.search(frazǎ)
        pana_la = _CEL_TARZIU.search(frazǎ)
        if termen is None and pana_la is None:
            continue

        zile = None
        if termen is not None:
            cantitate = _cantitate(termen.group("cantitate"))
            unitate = ZILE_PE_UNITATE.get(cheie(termen.group("unitate")))
            zile = cantitate * unitate if cantitate and unitate else None

        data_limita = None
        if pana_la is not None:
            luna = LUNI.get(cheie(pana_la.group("luna")))
            if luna:
                # An impossible date — a drafting typo like "31 septembrie", or a day the regex
                # matched from something that is not really a date — yields no fixed deadline
                # rather than crashing the whole corpus scan on one bad match.
                try:
                    data_limita = date(int(pana_la.group("an")), luna, int(pana_la.group("zi")))
                except ValueError:
                    data_limita = None

        ancora_m = _ANCORE.search(frazǎ)
        ancora = (
            next(n for n, _ in ANCORE if ancora_m.group(n) is not None)
            if ancora_m
            else ("data-fixa" if data_limita else "vigoare")
        )

        instrument, _ = _prima(_INSTRUMENTE, frazǎ, [n for n, _, _ in INSTRUMENTE])
        asteptat = next((t for n, t, _ in INSTRUMENTE if n == instrument), None)
        institutie, institutie_text = _prima(_INSTITUTII, frazǎ, [n for n, _ in INSTITUTII])

        gasite.append(
            Obligatie(
                act=act,
                locator=locator or Locator(),
                institutie=institutie,
                institutie_text=institutie_text,
                instrument=instrument,
                tip_asteptat=asteptat,
                termen_zile=zile,
                ancora=ancora,
                data_limita=data_limita,
                text=frazǎ.strip(),
            )
        )
    return gasite
