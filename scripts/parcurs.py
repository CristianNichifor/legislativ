"""How a bill actually moved: who proposed it, who was asked, and how the room voted.

`cdep.Initiativa` records where a bill *is* — one `stadiu` string, the current stage. That answers
"is this a live duplicate" and nothing else. The same Fișa carries the whole passage underneath it,
and the passage is what a reader wants when the question is political rather than legistic: who put
their name to it, which committees were asked and what they said, when it reached the floor, and
what the tally was.

Four things are read, and each is a different kind of evidence:

- **Initiators**, grouped the way the Fișa groups them — by chamber and by parliamentary group.
  `20 deputati+senatori, din care: deputati - PNL: …` — the group is not decoration, it is the
  answer to "who backed this", and a flat list of names throws it away.
- **The timeline**: one row per step, dated, and tagged with the chamber it happened in. The Fișa
  writes the chamber as a bare `CD` / `SE` / `PA` marker row and then lists the steps under it, so
  the chamber has to be carried down the table rather than read off each row.
- **Avize** — the opinions of the Legislative Council, the Government, and the standing committees.
  Their verdict is written in the action text, either in parentheses (`(favorabil)`) or as a word
  in the phrase (`raport de respingere`), and the committee that gave it is a nested link.
- **Votes**: `rezultat vot (pentru respingere): pentru=296, contra=1, abtineri=0`. What was voted
  on matters as much as the count — 296 votes *for rejection* is not 296 votes for the bill, and
  storing the tally without the question would invert the meaning of every rejected initiative.

**Nothing is inferred that the page does not say.** A step with no date keeps `None` rather than
borrowing the previous row's; an aviz whose sense is not written stays `None` rather than being
read as favourable. The Fișa is a record, and the gaps in it are part of the record.

The HTML is nested — committee names live inside a table inside the action cell — so this does not
reuse `cdep._celule`, whose flat `<td>…</td>` scan cannot see past the inner table.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Final

from scripts.text import normalizeaza

# `CD` / `SE` / `PA`: Chamber of Deputies, Senate, and the two in joint session. Written as a marker
# row that heads the steps below it.
CAMERE: Final[dict[str, str]] = {
    "CD": "Camera Deputaților",
    "SE": "Senat",
    "PA": "Parlament",
}

_RAND = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
# An innermost table — one containing no further `<table>`. The Fișa puts one inside the action
# cell of a step, listing the committee and links to its PDF.
_TABEL_INTERIOR = re.compile(r"<table(?:(?!<table)[\s\S])*?</table>", re.I)
_LEGATURA = re.compile(r"<a\b[^>]*>[\s\S]*?</a>", re.I)
_ANEXA = re.compile(r'<span class="anexa">[\s\S]*?</span>', re.I)
_ETICHETA = re.compile(r"<[^>]+>")
_DATA = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
# `pentru=296, contra=1, abtineri=0`, with the question that was put in the parentheses before it.
_VOT = re.compile(
    r"rezultat\s+vot(?:\s*\((?P<intrebare>[^)]*)\))?\s*:?\s*"
    r"pentru\s*=\s*(?P<pentru>\d+)\s*,\s*contra\s*=\s*(?P<contra>\d+)\s*,\s*"
    r"ab[țt]ineri\s*=\s*(?P<abtineri>\d+)"
    r"(?:\s*,\s*nu\s+au\s+votat\s*=\s*(?P<absenti>\d+))?",
    re.I,
)
# The outcome the sentence states, next to the tally. Read rather than inferred from the absence of
# a `(pentru respingere)` parenthetical: a null question would otherwise be the only thing
# distinguishing 275 votes *for* a bill from 296 votes to throw one out.
_REZULTAT = re.compile(r"\b(adoptat[ăa]?|respins[ăa]?)\b", re.I)
# `- cu nr.49/17.02.2021 (favorabil)`
_NUMAR_AVIZ = re.compile(r"\bnr\.?\s*(\d+)\s*/\s*(\d{2}\.\d{2}\.\d{4})")
_SENS = re.compile(r"\((favorabil[ăa]?|negativ[ăa]?|f[ăa]r[ăa] obiec[țt]iuni)[^)]*\)", re.I)
_COMISIE = re.compile(r'<a[^>]+href="[^"]*structura2015\.co[^"]*"[^>]*>(.*?)</a>', re.S | re.I)
# The body an opinion was asked of, when it is not a committee: `de la Consiliul Legislativ`,
# `de la Guvern`. Stops at the `-` that introduces the opinion's own number.
_DE_LA = re.compile(r"\bde la\s+(?P<cine>[^-:]+?)\s*(?:-|:|$)", re.I)
# `solicitare aviz de la Consiliul Legislativ termen: 16.02.2021` — the deadline that follows the
# body's name is not part of it, and `_DE_LA` stops at the colon after `termen`, not before it.
_COADA_TERMEN = re.compile(r"\s+termen\w*$", re.I)
# A deputy's own link on the Fișa: `structura2015.mp?idm=45`.
_MP = re.compile(r"<a[^>]+structura2015\.mp\?idm=(\d+)([^>]*)>([\s\S]*?)</a>", re.I)
# The chamber the person sits in, from their own link. Some headings read `- neafiliati:` with no
# chamber word at all, and `cam` is then the only place the page states it — read, not inferred.
_CAM = re.compile(r"[?&]cam=(\d+)")
# The legislature the link is scoped to. `idm` is unique *within* one, not across them: measured on
# the collected corpus, 349 distinct `idm` values cover 1 044 distinct people, and `idm=56` alone is
# four — Buzoianu (USR), Ghica (USR), Ciobanu (PNL) and Lavric (AUR). Without this a profile merges
# strangers and reports one deputy sitting in three parties at once.
_LEG = re.compile(r"[?&]leg=(\d+)")
CAM_NUME: Final[dict[str, str]] = {"1": "Senat", "2": "Camera Deputaților"}


@dataclass(frozen=True)
class Initiator:
    """One name on the bill, with the group it was signed under.

    `idm` is the Chamber's id for the person and `leg` the legislature it is scoped to. **Both are
    needed to name someone.** `idm` is reused between legislatures: 349 distinct values cover 1 044
    distinct people, and `idm=56` is Buzoianu, Ghica, Ciobanu and Lavric depending on the year.
    Keying on `idm` alone merges strangers and reports one deputy sitting in three parties.

    Matching on the name string is no better in the other direction — it splits `Şovăială` from
    `Șovăială` and merges two people who share a name.
    """

    nume: str
    grup: str | None
    camera: str | None
    idm: str | None = None
    leg: str | None = None  # the legislature `idm` is scoped to; `idm` alone is not a person


@dataclass(frozen=True)
class Aviz:
    """An opinion asked for or received. `sens` is None where the Fișa does not say."""

    de_la: str
    data: str | None
    sens: str | None
    numar: str | None
    primit: bool


@dataclass(frozen=True)
class Vot:
    """A recorded division. `intrebare` is what was put — usually `pentru respingere`."""

    data: str | None
    camera: str | None
    intrebare: str | None
    pentru: int
    contra: int
    abtineri: int
    rezultat: str | None = None  # 'adoptat' | 'respins', as the step's own sentence puts it
    absenti: int | None = None  # `nu au votat=2`, where the Fișa records it


@dataclass(frozen=True)
class Etapa:
    """One dated step of the passage, in the chamber the Fișa filed it under."""

    data: str | None
    camera: str | None
    actiune: str
    comisii: tuple[str, ...] = ()


@dataclass(frozen=True)
class Parcurs:
    """Everything the Fișa says about how the bill moved."""

    plx_id: str
    idp: str
    initiatori: tuple[Initiator, ...] = ()
    etape: tuple[Etapa, ...] = ()
    avize: tuple[Aviz, ...] = ()
    voturi: tuple[Vot, ...] = ()
    stenograme: tuple[str, ...] = field(default=())


def _text(brut: str) -> str:
    """Markup to readable text, entities decoded.

    `html.unescape` before the tag strip, not after: the page writes `&#539;` for `ț` inside the
    action text, and a strip that ran first would leave the entity sitting in a sentence the
    reader is meant to read.
    """
    import html

    return normalizeaza(_ETICHETA.sub(" ", html.unescape(brut))).strip()


def _fara_tabele_interne(html: str) -> str:
    """Collapse the table inside a step's action cell to just its links.

    This has to happen *before* the page is split into rows, and that is the whole reason it
    exists. The inner table has its own `<tr>`, so a non-greedy `<tr>(.*?)</tr>` over the raw page
    ends the outer row at the *inner* row's close: the step is truncated, the remainder becomes a
    spurious row, and the action comes out reading `Adresa inițiatorului` — the label of a PDF link
    from inside the nested table — instead of `prezentare în Biroul Permanent`. Six of sixteen
    steps were wrong that way, including every one carrying an opinion's verdict.

    Exactly one pass, and that is deliberate. `_TABEL_INTERIOR` cannot match a table that contains
    another, so a single pass rewrites the innermost tables and leaves the outer timeline table —
    the one whose rows are being read — untouched. A second pass would find the timeline table
    innermost by then and flatten the page away.

    The links survive because the committee that gave an opinion is only named inside one of them.
    """

    def inlocuieste(m: re.Match[str]) -> str:
        legaturi = "".join(a.group(0) for a in _LEGATURA.finditer(m.group(0)))
        return f'<span class="anexa">{legaturi}</span>'

    return _TABEL_INTERIOR.sub(inlocuieste, html)


def _celule(rand: str) -> list[str]:
    """The row's cells, with the collapsed inner table dropped.

    Dropped rather than read: the links it holds are a PDF of the opinion, and their labels
    (`Adresa inițiatorului`, `Punctul de vedere al Guvernului`) would otherwise be appended to the
    step's own sentence. The committee names in the same block are read separately, off the row.
    """
    curat = _ANEXA.sub(" ", rand)
    return re.findall(r"<td[^>]*>([\s\S]*?)</td>", curat, re.I)


def _data_iso(brut: str) -> str | None:
    m = _DATA.search(brut)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _initiatori(html: str, plat: str) -> list[Initiator]:
    """Who signed it: a list of people, or the body that proposed it.

    The people are read from the raw page, before the inner tables are collapsed, because they
    *are* an inner table — `Initiator:` holds a count, then a table whose rows are `deputati - PNL:`
    against a cell of linked names. Read off the flattened page that returns the count and nothing
    else. Names come from the links rather than the text so each carries its `idm`.

    **The table has to be the sponsors' table.** A Government bill has no list at all — the Fișa
    says `Initiator: | Guvern` — and searching forward for the next table then finds the unrelated
    `Consultati:` block and reads its PDF labels as people: `Expunerea de motive` and `Forma
    inițiatorului` were being stored as initiators of an ordonanță de urgență. So a table only
    counts when it actually links to deputies, and otherwise the Fișa's own answer is used, which
    for those bills is the government that sent it.
    """
    i = html.find("Initiator")
    if i >= 0:
        m = _TABEL_INTERIOR.search(html, i)
        if m is not None and "structura2015.mp" in m.group(0):
            iesire: list[Initiator] = []
            for rand in re.split(r"<tr\b", m.group(0), flags=re.I)[1:]:
                celule = re.findall(r"<td[^>]*>([\s\S]*?)</td>", rand, re.I)
                if len(celule) < 2:
                    continue
                grup, camera = _grup_si_camera(_text(celule[0]))
                for mm in _MP.finditer(celule[1]):
                    din_link = _CAM.search(mm.group(2))
                    leg = _LEG.search(mm.group(2))
                    iesire.append(
                        Initiator(
                            _text(mm.group(3)),
                            grup,
                            camera or (CAM_NUME.get(din_link.group(1)) if din_link else None),
                            mm.group(1),
                            leg.group(1) if leg else None,
                        )
                    )
            if iesire:
                return iesire
    # No list of people. Read the Fișa's own one-word answer off the flattened page.
    for celule in (_celule(r) for r in _RAND.findall(plat)):
        text = [_text(c) for c in celule]
        if len(text) >= 2 and "initiator" in _fold(text[0]):
            nume = _text(_ANEXA.sub(" ", celule[-1]))
            if nume and len(nume) <= 60:
                return [Initiator(nume, None, None, None, None)]
            return []
    return []


def _fold(s: str) -> str:
    from scripts.text import cheie

    return cheie(s)


def _pare_grup(cap: str) -> bool:
    f = _fold(cap)
    return f.startswith("deputati") or f.startswith("senatori") or " - " in cap


def _grup_si_camera(cap: str) -> tuple[str | None, str | None]:
    """`deputati - PNL:` -> ("PNL", "Camera Deputaților")."""
    f = _fold(cap)
    camera = None
    if f.startswith("deputati"):
        camera = "Camera Deputaților"
    elif f.startswith("senatori"):
        camera = "Senat"
    m = re.search(r"-\s*([^:]+)", cap)
    grup = m.group(1).strip() if m else None
    return (grup or None), camera


def _nume(brut: str) -> list[str]:
    """`Bola Bogdan-Alexandru , Kocsis-Cristea Alexandru` -> two names.

    Split on the comma the page uses between people. A name itself never contains one — the Fișa
    writes `Surname Forename`, not `Surname, Forename`.
    """
    return [n.strip() for n in brut.split(",") if len(n.strip()) > 3]


def _comisii(celula: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_text(m.group(1)) for m in _COMISIE.finditer(celula)))


def _sens(text: str) -> str | None:
    m = _SENS.search(text)
    if m:
        return _fold(m.group(1)).split()[0].replace("fara", "fără")
    # A report carries its verdict in the phrase rather than in parentheses: `raport de respingere`,
    # `raport de adoptare`. Read only those two, and only on a report — `primire aviz de la` with no
    # parenthesis genuinely does not say, and guessing would invent an opinion.
    f = _fold(text)
    if "raport de respingere" in f:
        return "respingere"
    if "raport de adoptare" in f or "raport de aprobare" in f:
        return "adoptare"
    return None


def parseaza_parcurs(html: str, plx_id: str, idp: str) -> Parcurs:
    """One Fișa into its passage. Everything is read off the page; nothing is filled in."""
    plat = _fara_tabele_interne(html)
    brute = _RAND.findall(plat)
    randuri = [_celule(r) for r in brute]

    initiatori = _initiatori(html, plat)

    etape: list[Etapa] = []
    avize: list[Aviz] = []
    voturi: list[Vot] = []
    stenograme: list[str] = []
    camera: str | None = None
    pornit = False

    for rand, celule in zip(brute, randuri, strict=True):
        text = [_text(c) for c in celule]
        nevide = [t for t in text if t]
        if not nevide:
            continue
        # The steps table starts after its own header row.
        if not pornit:
            if any(_fold(t) == "actiunea" for t in nevide):
                pornit = True
            continue
        # A bare `CD` / `SE` / `PA` heads the steps that follow it.
        if len(nevide) == 1 and nevide[0] in CAMERE:
            camera = CAMERE[nevide[0]]
            continue
        actiune = text[-1] if text else ""
        if not actiune:
            continue
        data = _data_iso(text[0]) if text else None
        comisii = _comisii(rand)
        etape.append(Etapa(data, camera, actiune, comisii))

        f = _fold(actiune)
        if "stenograma" in f:
            stenograme.extend(
                m.group(1) for m in re.finditer(r'href="([^"]*steno[^"]*)"', rand, re.I)
            )
        if "aviz" in f or "punct de vedere" in f or "raport" in f:
            avize.extend(_avize_din(actiune, comisii, data))
        m = _VOT.search(actiune)
        if m:
            rez = _REZULTAT.search(actiune)
            voturi.append(
                Vot(
                    data,
                    camera,
                    (m.group("intrebare") or "").strip() or None,
                    int(m.group("pentru")),
                    int(m.group("contra")),
                    int(m.group("abtineri")),
                    _fold(rez.group(1))[:7].rstrip("a") if rez else None,
                    int(m.group("absenti")) if m.group("absenti") else None,
                )
            )

    return Parcurs(
        plx_id=plx_id,
        idp=idp,
        initiatori=tuple(initiatori),
        etape=tuple(etape),
        avize=tuple(avize),
        voturi=tuple(voturi),
        stenograme=tuple(dict.fromkeys(stenograme)),
    )


def _avize_din(actiune: str, comisii: tuple[str, ...], data: str | None) -> list[Aviz]:
    """The opinions one step records. A step names either committees or a single body."""
    f = _fold(actiune)
    primit = f.startswith("primire") or "primire" in f[:20]
    m = _NUMAR_AVIZ.search(actiune)
    numar, data_aviz = (m.group(1), _data_iso(m.group(2))) if m else (None, None)
    sens = _sens(actiune)
    if comisii:
        return [Aviz(c, data_aviz or data, sens, numar, primit) for c in comisii]
    m_cine = _DE_LA.search(actiune)
    if not m_cine:
        return []
    cine = _COADA_TERMEN.sub("", m_cine.group("cine").strip(" .,")).strip()
    return [Aviz(cine, data_aviz or data, sens, numar, primit)] if cine else []


def fisa_parcurs(idp: str, cam: int = 2, *, opener=None) -> Parcurs:
    """Fetch one Fișa and read its passage. `plx_id` comes from the same page's own numbering."""
    import urllib.request

    from scripts.cdep import BASE, _fetch, parseaza_fisa

    url = f"{BASE}.proiect?cam={cam}&idp={idp}"
    html = _fetch(url, opener=opener or urllib.request.urlopen)
    ini = parseaza_fisa(html, idp, cam, url=url)
    return parseaza_parcurs(html, ini.plx_id, idp)


class Ritm:
    """A ceiling on requests per second, shared by every worker.

    Concurrency and politeness are separate dials and this is the second one. Three connections
    that each wait their turn against one clock is three times the throughput at the same load on
    the server; three connections that each sleep between their own requests is three times the
    load. Measured against cdep.ro, a Fișa takes 1.3 to 10.9 seconds to come back and 0.006 to
    parse, so the whole job is waiting — which is exactly the shape concurrency helps and better
    code does not.
    """

    def __init__(self, pe_secunda: float) -> None:
        self._interval = 1.0 / pe_secunda if pe_secunda > 0 else 0.0
        self._lacat = threading.Lock()
        self._urmatorul = 0.0

    def asteapta(self) -> None:
        if not self._interval:
            return
        with self._lacat:
            acum = time.monotonic()
            if self._urmatorul > acum:
                time.sleep(self._urmatorul - acum)
                acum = time.monotonic()
            self._urmatorul = acum + self._interval


def colecteaza_parcurs(
    cale_db: str = "corpus.db",
    *,
    limita: int | None = None,
    pauza: float = 0.3,
    doar_lipsa: bool = True,
    fara_legislatura: bool = False,
    paralel: int = 1,
    rata: float = 2.0,
    opener=None,
    log=print,
) -> dict:
    """Read the passage of every initiative already collected, from its Fișa.

    Works off `initiative` rather than re-enumerating the years: `cdep.colecteaza_cdep` has already
    decided which bills exist and holds the `idp` needed to fetch each one. One request per
    initiative, sequential and paced — this is a few thousand small pages against a second
    ministry's server, and there is nothing to gain by hurrying it.

    `doar_lipsa` skips initiatives whose passage is already stored, so a run can be resumed. Pass
    False to re-read them, which is what a refetch is for: a bill that was in committee last month
    has moved, and its Fișa is the only thing that knows.

    `fara_legislatura` selects only the initiatives whose signatures were stored before `leg` was
    read. A backfill needs to re-read pages it has already seen, which `doar_lipsa` would skip and
    `doar_lipsa=False` would restart from the top on every interruption — this makes the pass
    resumable against what is actually missing.

    `paralel` opens more than one connection; `rata` caps requests per second across all of them,
    so raising the first does not raise the load. The work is 99.9% waiting on the server, so this
    is the only dial that changes anything.
    """
    from scripts import depozit

    # Writable, not read-only, and that is not an oversight. `deschide(readonly=True)` skips the
    # schema step, so against a database collected before these tables existed the very first read
    # fails with `no such table: initiativa_etapa`. Opening for write creates them, which is what a
    # store that has never held a passage needs before it can be asked whether it holds one.
    with depozit.deschide(cale_db) as con:
        randuri = [
            (r[0], r[1], r[2]) for r in con.execute("SELECT plx_id, idp, cam FROM initiative")
        ]
        deja = (
            {r[0] for r in con.execute("SELECT DISTINCT plx_id FROM initiativa_etapa")}
            if doar_lipsa
            else set()
        )
        cu_leg = (
            {
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT plx_id FROM initiativa_initiator WHERE leg IS NOT NULL"
                )
            }
            if fara_legislatura
            else set()
        )
    de_facut = [r for r in randuri if r[0] not in deja]
    if fara_legislatura:
        de_facut = [r for r in de_facut if r[0] not in cu_leg]
    if limita is not None:
        de_facut = de_facut[:limita]
    log(f"{len(de_facut)} inițiative de citit (din {len(randuri)})")

    citite = etape = voturi = esuate = 0
    ritm = Ritm(rata) if paralel > 1 else None

    def adu_unul(rand):
        plx_id, idp, cam = rand
        if ritm is not None:
            ritm.asteapta()
        try:
            return rand, fisa_parcurs(idp, cam or 2, opener=opener)
        except Exception as e:  # noqa: BLE001
            return rand, e

    if paralel > 1:
        pool = ThreadPoolExecutor(max_workers=paralel)
        rezultate = pool.map(adu_unul, de_facut)
    else:
        pool = None
        rezultate = (adu_unul(r) for r in de_facut)

    with depozit.deschide(cale_db) as con:
        for i, ((plx_id, idp, _cam), p) in enumerate(rezultate, start=1):
            if isinstance(p, Exception):
                esuate += 1
                log(f"  idp={idp}: {p}")
                continue
            # The Fișa's own plx_id wins over the stored one only when it says something; a page
            # that failed to name itself must not rename the initiative it was fetched for.
            depozit.scrie_parcurs(
                con, Parcurs(plx_id, idp, p.initiatori, p.etape, p.avize, p.voturi, p.stenograme)
            )
            citite += 1
            etape += len(p.etape)
            voturi += len(p.voturi)
            if i % 25 == 0 or i == len(de_facut):
                con.commit()
                log(f"  {i}/{len(de_facut)} · {etape} etape · {voturi} voturi · {esuate} eșuate")
            # Paced, and the pause is the whole reason the parameter exists. cdep.ro is a second
            # ministry's server and this is a few thousand requests against it; an unpaced loop is
            # the difference between collecting a corpus and being a nuisance. With workers the
            # pacing is `Ritm`, one clock for all of them, so the pause here would double it.
            if pool is None and i < len(de_facut):
                time.sleep(pauza)
        con.commit()
    if pool is not None:
        pool.shutdown()
    return {"citite": citite, "etape": etape, "voturi": voturi, "esuate": esuate}


def _main() -> int:
    import argparse

    from scripts import depozit

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--limita", type=int)
    ap.add_argument("--pauza", type=float, default=0.3)
    ap.add_argument("--paralel", type=int, default=1, help="conexiuni simultane")
    ap.add_argument("--rata", type=float, default=2.0, help="cereri pe secundă, peste toate")
    ap.add_argument(
        "--fara-legislatura",
        action="store_true",
        help="doar inițiativele ale căror semnături nu au încă legislatura",
    )
    ap.add_argument(
        "--reciteste",
        action="store_true",
        help="recitește și inițiativele al căror parcurs e deja stocat (au mai avansat)",
    )
    a = ap.parse_args()
    r = colecteaza_parcurs(
        a.db,
        limita=a.limita,
        pauza=a.pauza,
        doar_lipsa=not a.reciteste,
        fara_legislatura=a.fara_legislatura,
        paralel=a.paralel,
        rata=a.rata,
    )
    print(f"\ngata: {r['citite']} fișe · {r['etape']} etape · {r['voturi']} voturi")
    with depozit.deschide(a.db, readonly=True) as con:
        n = con.execute("SELECT count(*) FROM initiativa_initiator").fetchone()[0]
        print(f"initiatori stocați: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
