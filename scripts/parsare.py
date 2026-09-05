"""Reading an act off legislatie.just.ro, against markup that was actually looked at.

This module replaces a stub that raised. The stub existed because the portal was unreachable
from the environment the package was first written in, and a parser written against imagined
markup is the most expensive artefact a project like this can carry: it imports, it reads well,
its invented fixtures pass, and it fails on the first real page. The stub is gone because three
real pages are now in `sources/`, and every selector below was read off one of them.

**The portal marks its own structure, and it marks it well.** An act page is not a soup of
divs — it carries `S_DEN` for the designation, `S_EMT_BDY` for the issuer, `S_PUB_BDY` for the
publication line, and a nested tree of `S_ART` / `S_ALN` / `S_LIT` for articles, paragraphs and
letters. Legea 98/2016 yields 246 `S_ART`, 724 `S_ALN` and 465 `S_LIT` from one fetch. The
locator model in `referinte.py` — articol, alineat, literă, punct — maps onto that one to one,
which is luck rather than design, and worth taking.

**The id in the URL is not the id of the act.** Requesting `/Public/DetaliiDocument/178667`
returns a page whose own `id_act` field reads `290673`. The first is the search result's handle,
the second identifies the consolidated form being displayed. This was the open question that
decided the collection strategy, and the answer is the awkward one: walking a range of URL ids
enumerates handles, not acts, and the same act reached two ways can present two numbers. So
neither number is the identity. `Act.id` — type, number, year, off the designation line — is,
because it is what the law itself is called and what every citation in every other act uses.
Both portal numbers are kept as attributes, for fetching and for auditing, and neither is a key.

**`S_LGI` is a gift and is used as one.** The portal wraps every legislative reference it
recognises in the running text — `anexa nr. 1`, `lit. m)`, an act's designation — in a
`S_LGI` span. It does not resolve them to targets, so `referinte.py` is still the module that
says *which* act is meant. But it means the corpus arrives with the reference *positions*
already marked by the publisher, which is ground truth this package could not otherwise afford:
recall can be measured against real documents instead of against thirty-six sentences somebody
wrote by hand.

Parsing is done with the standard library's HTML parser. That is a deliberate refusal of lxml
and BeautifulSoup: the package has no runtime dependencies, the markup is regular enough not to
need a forgiving parser, and a legal corpus is not the place to find out that two HTML libraries
disagree about where a tag ends.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from scripts.referinte import Act, Locator
from scripts.text import cheie, normalizeaza

LUNI: dict[str, int] = {
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

TIPURI_DEN: list[tuple[str, str]] = [
    ("oug", r"ORDONAN[ȚT][ĂA]\s+DE\s+URGEN[ȚT][ĂA]"),
    ("og", r"ORDONAN[ȚT][ĂA]"),
    ("hg", r"HOT[ĂA]R[ÂA]RE"),
    ("lege", r"LEGE"),
    ("ordin", r"ORDIN"),
    ("decret", r"DECRET"),
    ("decizie", r"DECIZIE"),
]
_DEN = re.compile(
    r"(?P<tip>" + "|".join(s for _, s in TIPURI_DEN) + r")"
    r"[^\d]{0,20}?(?P<numar>\d{1,5})\s+din\s+(?P<zi>\d{1,2})\s+(?P<luna>[a-zăâîșț]+)\s+(?P<an>\d{4})",
    re.IGNORECASE,
)
_PUB = re.compile(
    r"nr\.\s*(?P<numar>\d{1,5})\s+din\s+(?P<zi>\d{1,2})\s+(?P<luna>[a-zăâîșț]+)\s+(?P<an>\d{4})",
    re.IGNORECASE,
)
_ASCUNS = re.compile(
    r'name="(?P<nume>id_act|Actiunisuferite|ActiuniInduse|Referape|Referitde)"'
    r'[^>]*value="(?P<val>[^"]*)"'
)
_NR_TTL = re.compile(r"(\d+(?:\^\d+)?)")


@dataclass(frozen=True)
class Provizie:
    """One addressable provision, with the text a finding will quote."""

    locator_id: str
    text: str
    in_vigoare_de_la: date | None = None
    in_vigoare_pana_la: date | None = None
    referinte_marcate: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class ActParsat:
    """What one document page yields. `act.id` is the key; the portal's numbers are not."""

    act: Act
    titlu: str
    publicat: date | None = None
    vigoare: date | None = None
    republicat_din: date | None = None
    emitent: str = ""
    provizii: tuple[Provizie, ...] = field(default=())
    sursa_url: str = ""
    id_portal: str = ""
    id_act_portal: str = ""
    relatii: frozenset[str] = field(default_factory=frozenset)


class _Culegator(HTMLParser):
    """Collects the full text of every element carrying a class this package cares about.

    A buffer per open element, and every character appended to *all* of them, so a closing
    `S_ART` yields the whole article — title, paragraphs, letters and all — while the `S_ALN`
    that closed inside it yields only its own paragraph. The first version kept one shared
    buffer and cleared it whenever anything interesting closed, which meant a parent lost its
    text the moment a child ended: Legea 98/2016 came out with one provision instead of
    hundreds, and the designation line came out as the page's `<title>` plus a slab of
    JavaScript.

    Void elements are never pushed. They have no end tag, and pushing them walks the stack out
    of alignment for the rest of the document, which in a 1,6 MB page is not a bug you find by
    reading.
    """

    INTERESANTE = {
        "S_DEN",
        "S_EMT_BDY",
        "S_PUB_BDY",
        "S_ART",
        "S_ART_TTL",
        "S_ART_DEN",
        "S_ALN",
        "S_ALN_TTL",
        "S_ALN_BDY",
        "S_LIT",
        "S_LIT_TTL",
        "S_LIT_BDY",
        "S_PAR",
        "S_LGI",
    }
    # The collapsed copy the page reveals on hover. Counted, it doubles every letter in the act.
    IGNORATE = {"S_LIT_SHORT"}
    GOALE = {"br", "img", "input", "meta", "link", "hr", "col", "area", "base", "source", "wbr"}
    # `script` and `style` bodies are text to HTMLParser and would land in the nearest buffer.
    MUTE = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.evenimente: list[tuple[str, str, str]] = []
        self._stiva: list[tuple[str | None, list[str]]] = []
        self._sarit = 0
        self._mut = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.GOALE:
            return
        if tag in self.MUTE:
            self._mut += 1
            self._stiva.append((None, []))
            return
        clase = (dict(attrs).get("class") or "").split()
        if self._sarit or any(c in self.IGNORATE for c in clase):
            self._sarit += 1
            self._stiva.append((None, []))
            return
        nume = next((c for c in clase if c in self.INTERESANTE), None)
        self._stiva.append((nume, []))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if tag in self.GOALE or not self._stiva:
            return
        nume, buf = self._stiva.pop()
        if tag in self.MUTE and self._mut:
            self._mut -= 1
            return
        if self._sarit:
            self._sarit -= 1
            return
        if nume:
            self.evenimente.append(("inchide", nume, "".join(buf)))

    def handle_data(self, data: str) -> None:
        if self._sarit or self._mut:
            return
        for _, buf in self._stiva:
            buf.append(data)


def _data(zi: str, luna: str, an: str) -> date | None:
    numar = LUNI.get(cheie(luna))
    return date(int(an), numar, int(zi)) if numar else None


def _act_din_denumire(den: str) -> tuple[Act | None, date | None]:
    m = _DEN.search(normalizeaza(den))
    if m is None:
        return None, None
    tip = next(
        (t for t, s in TIPURI_DEN if re.fullmatch(s, m.group("tip"), re.IGNORECASE)),
        "lege",
    )
    semnat = _data(m.group("zi"), m.group("luna"), m.group("an"))
    return Act(tip, m.group("numar"), int(m.group("an"))), semnat


# The `+` / `-` the page puts before a heading is the expand control, not part of the law.
_CONTROL = re.compile(r"^\s*[+\-−]\s*")


def _text_din(evenimente: list[tuple[str, str, str]], i: int) -> str:
    brut = _CONTROL.sub("", re.sub(r"\s+", " ", evenimente[i][2]))
    # `Articolul 7Prezenta lege...` — the heading and its body are adjacent nodes with no
    # separator between them, so the join has to put one back or every article opens with its
    # own title welded to its first word.
    brut = re.sub(r"(Articolul\s+\d+(?:\^\d+)?)(?=[A-ZȘȚĂÂÎ(])", r"\1 - ", brut)
    return normalizeaza(brut)


def parseaza(html: str, url: str = "") -> ActParsat:
    """One document page into the shape the rest of the package consumes."""
    culegator = _Culegator()
    culegator.feed(html)
    ev = culegator.evenimente

    def primul(nume: str) -> str:
        return next(
            (_text_din(ev, i) for i, e in enumerate(ev) if e[0] == "inchide" and e[1] == nume), ""
        )

    den = primul("S_DEN")
    act, semnat = _act_din_denumire(den)
    pub = primul("S_PUB_BDY")
    m_pub = _PUB.search(normalizeaza(pub))
    publicat = _data(m_pub.group("zi"), m_pub.group("luna"), m_pub.group("an")) if m_pub else None

    ascunse = {m.group("nume"): m.group("val") for m in _ASCUNS.finditer(html)}
    relatii = {
        nume
        for nume in ("Actiunisuferite", "ActiuniInduse", "Referape", "Referitde")
        if re.search(rf'name="{nume}"[^>]*value="true"', html)
    }

    return ActParsat(
        act=act or Act("necunoscut"),
        titlu=den,
        publicat=publicat,
        vigoare=publicat,
        emitent=primul("S_EMT_BDY"),
        provizii=tuple(_provizii(ev)),
        sursa_url=url,
        id_portal=re.search(r"/(\d+)\s*$", url).group(1) if re.search(r"/(\d+)\s*$", url) else "",
        id_act_portal=ascunse.get("id_act", ""),
        relatii=frozenset(relatii),
    )


def _provizii(ev: list[tuple[str, str, str]]) -> list[Provizie]:
    """Walk the flat event list into one Provizie per article, alineat and literă.

    Deliberately emits a provision at every level rather than only the leaves: a finding may
    need to quote article 7 whole, or only its paragraph (2), and the linter should not have to
    reassemble the parent from its children to do the first.
    """
    provizii: list[Provizie] = []
    art = aln = lit = None
    paragrafe: list[tuple[str, tuple[str, ...]]] = []
    marcate: list[str] = []
    for i, (fel, nume, _) in enumerate(ev):
        if fel == "inchide" and nume == "S_LGI":
            marcate.append(_text_din(ev, i))
        if fel != "inchide":
            continue
        text = _text_din(ev, i)
        if nume == "S_ART_TTL":
            m = _NR_TTL.search(text)
            art, aln, lit = (m.group(1) if m else None), None, None
        elif nume == "S_ALN_TTL":
            m = _NR_TTL.search(text)
            aln, lit = (m.group(1) if m else None), None
        elif nume == "S_LIT_TTL":
            m = re.search(r"([a-zșț](?:\^\d+)?)\)", text)
            lit = m.group(1) if m else None
        elif nume in {"S_ART", "S_ALN", "S_LIT"} and text:
            loc = Locator(
                articol=art,
                alineat=aln if nume in {"S_ALN", "S_LIT"} else None,
                litera=lit if nume == "S_LIT" else None,
            )
            if loc:
                provizii.append(
                    Provizie(loc.id, text, referinte_marcate=tuple(dict.fromkeys(marcate)))
                )
                marcate = []
        elif nume == "S_PAR" and text:
            paragrafe.append((text, tuple(dict.fromkeys(marcate))))
            marcate = []

    # Not every act has articles. A Curtea Constituțională decision is `S_PAR` all the way
    # down, and the first version of this returned nothing for one — a document with text in
    # it, stored as empty, which is worse than refusing it. Numbered paragraphs are a poor
    # locator but they are addressable, and they keep the text searchable.
    if not provizii:
        provizii = [
            Provizie(f"par{i}", text, referinte_marcate=refs)
            for i, (text, refs) in enumerate(paragrafe, start=1)
        ]
    return provizii


def din_fisier(cale: Path, url: str = "") -> ActParsat:
    """Read a saved page, gzipped or not. The fixtures in `sources/` are gzipped."""
    brut = cale.read_bytes()
    if cale.suffix == ".gz":
        brut = gzip.decompress(brut)
    return parseaza(brut.decode("utf-8", errors="replace"), url=url)
