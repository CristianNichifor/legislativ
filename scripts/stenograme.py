"""The debate itself: what was said in the Chamber about a bill, and by whom.

`parcurs.py` reads a Fișa and gets the shape of a bill's passage — filed, referred, reported,
divided, adopted. Every step of that is an event with a date and a verb, and none of it is an
argument. The transcript is where the argument is, and the Chamber publishes it at exactly the
granularity that makes it usable: `stenograma?ids=8235&idm=8` is *the item*, not the day. A
sitting runs through dozens of bills; the link on a step points at the one that step was about.

**Why the speaker's own link is the whole point.** Each name in the transcript is wrapped in
`structura2015.mp?idm=165&cam=2&leg=2020` — the same `(leg, camera, idm)` triple `deputati.py`
builds a profile on. So a speech joins to the person who gave it through the Chamber's own
identifier, and never through the name string, which splits `Şovăială` from `Șovăială` and merges
two people who share one. This is the join that turns "here is a debate" into "here is what your
deputy said", and it costs nothing because the page already carries it.

**Where the link is absent, so is the claim.** Ministers, secretaries of state and guests speak
without a profile to link to. Their name is stored as printed and `rol` carries the parenthetical
the page prints for them — `(secretar de stat, Ministerul Justiţiei)` — which is the only place
the transcript says who they were. They are not guessed into a deputy id.

**A collective is not a person, whatever the page says.** The Chamber's own markup links
interjections from the floor to the deputy who was chairing: on ids=8236 the words `Voci din sală`
carry `idm=245`, which is Prună. Attributing them would put crowd noise on a named person's
record. Every genuine speaker is announced with `Domnul` or `Doamna`, so a linked name lacking the
honorific keeps its text and loses its id — the speech is still reported, under the name the page
printed, with nobody's profile attached.
"""

from __future__ import annotations

import html as _html
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from scripts.parsare import LUNI
from scripts.text import normalizeaza

BAZA = "https://www.cdep.ro/ords/pls/steno/steno2015.stenograma"

# One turn at the microphone, delimited by the transcript's own comments. The numbers inside
# `START=` are the video offsets, which is what they are there for; the delimiters are used here
# only as the boundary of a speech, because nothing else in the markup marks one.
_BLOC = re.compile(r"<!--\s*START=[^>]*?-->(.*?)<!--\s*END\s*-->", re.S)
# `<B><a href="...structura2015.mp?idm=165&cam=2&leg=2020"><font color="#0000FF">Domnul X</font>
# </a></B> <I>(rol)</I>:`. Every part between `<b>` and the name is confined to a single tag —
# no `.*?` spanning — so a speaker cannot pick up the link of the one before them.
_VORBITOR = re.compile(
    r"<b>\s*(?:<a[^>]*?structura2015\.mp\?(?P<legatura>[^\"']*)\"[^>]*>)?\s*"
    r"<font[^>]*>(?P<nume>[^<]*)</font>\s*(?:</a>)?\s*</b>\s*"
    r"(?:<i>\s*\(?(?P<rol>[^<]*?)\)?\s*</i>)?\s*:",
    re.I,
)
# Anchored at the start of the captured query string as well as after a separator: what is matched
# is the inside of one href, `idm=165&cam=2&leg=2020`, which has no leading `?`.
_IDM = re.compile(r"(?:^|[?&])idm=(\d+)")
_CAM = re.compile(r"(?:^|[?&])cam=(\d+)")
_LEG = re.compile(r"(?:^|[?&])leg=(\d+)")
CAM_NUME: dict[str, str] = {"1": "Senat", "2": "Camera Deputaților"}
# `Şedinţa Camerei Deputaţilor din 22 februarie  2021`, off the page's own breadcrumb. Four links
# on the page point at the same sitting summary — the two language toggles, `Sumarul şedinţei`,
# and the breadcrumb — and only the last spells the sitting out, so the one carrying a date is the
# one read rather than the first.
_SUMAR = re.compile(r"steno2015\.sumar\?ids=\d+[^\"]*\"[^>]*>(.*?)</a>", re.S | re.I)
_DATA_RO = re.compile(r"(\d{1,2})\s+([a-zăâîșț]+)\s+(\d{4})", re.I)
# The item's own subject line. The transcript highlights two cells in that colour — the item's
# number and its subject — so the longer of them is the subject.
_TITLU = re.compile(r'<td[^>]*bgcolor="#fef9c2"[^>]*>(.*?)</td>', re.S | re.I)
# The Fișa the transcript names for this item — `consulta fisa PL nr. 1/2021`.
_IDP = re.compile(r"upl_pck2015\.proiect\?idp=(\d+)")
_ETICHETA = re.compile(r"<[^>]+>")
# A speaker the page links but does not announce. Every person is introduced with an honorific;
# `Voci din sală` is not a person and carries the chair's id in the Chamber's own markup.
_ONORIFIC = re.compile(r"^\s*(domnul|doamna|dl\.?|dna\.?)\b", re.I)


@dataclass(frozen=True)
class Interventie:
    """One speech. `dep_*` is the Chamber's key for the speaker, absent where the page has none."""

    ord: int
    vorbitor: str | None
    dep_idm: str | None
    dep_leg: str | None
    dep_camera: str | None
    rol: str | None
    text: str


@dataclass(frozen=True)
class Stenograma:
    """One item of one sitting, and everything said under it."""

    ids: str
    idm: str
    data: str | None
    camera: str | None
    titlu: str | None
    idp: str | None
    url: str
    interventii: tuple[Interventie, ...] = ()


def url_stenograma(ids: str, idm: str) -> str:
    return f"{BAZA}?ids={ids}&idm={idm}"


def _text(brut: str) -> str:
    """Markup to readable text, entities decoded before the tags are stripped.

    The order matters for the same reason it does on a Fișa: the page writes `&#355;` for `ţ`
    inside sentences a reader is meant to read, and a strip that ran first would leave the entity
    sitting in the prose. `normalizeaza` then folds the Latin-2 cedilla letters the transcript is
    full of onto the correct comma-below Romanian ones.
    """
    return normalizeaza(_ETICHETA.sub(" ", _html.unescape(brut))).strip()


def _data_iso(titlu: str) -> str | None:
    m = _DATA_RO.search(titlu)
    if not m:
        return None
    luna = LUNI.get(normalizeaza(m.group(2)).lower())
    return f"{m.group(3)}-{luna:02d}-{int(m.group(1)):02d}" if luna else None


def _camera(titlu: str) -> str | None:
    jos = normalizeaza(titlu).lower()
    if "camerei deputaților" in jos or "camera deputaților" in jos:
        return "Camera Deputaților"
    if "senatului" in jos or "senat" in jos:
        return "Senat"
    if "parlamentului" in jos or "comune" in jos:
        return "Parlament"
    return None


def _vorbitorul(fragment: str) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """`(nume, idm, leg, camera, rol)` from the first announced speaker in a fragment.

    The id is dropped for a name the page does not announce as a person — see the module note on
    `Voci din sală`. The text of such an interjection is kept; only the attribution goes.
    """
    m = _VORBITOR.search(fragment)
    if not m:
        return (None, None, None, None, None)
    nume = _text(m.group("nume")) or None
    rol = _text(m.group("rol") or "") or None
    legatura = m.group("legatura") or ""
    if not nume or not _ONORIFIC.match(nume):
        return (nume, None, None, None, rol)
    idm = _IDM.search(legatura)
    cam = _CAM.search(legatura)
    leg = _LEG.search(legatura)
    return (
        nume,
        idm.group(1) if idm else None,
        leg.group(1) if leg else None,
        CAM_NUME.get(cam.group(1)) if cam else None,
        rol,
    )


def parseaza_stenograma(pagina: str, ids: str, idm: str, *, url: str | None = None) -> Stenograma:
    """One transcript page into its speeches. Everything is read off the page.

    A speech's speaker is the one announced inside its own block, and where the block opens
    without an announcement — the chair carries on from the row above — it is the last speaker
    announced before it. Both shapes occur on the same page and neither is an error: the Chamber
    prints the name once and then the words.
    """
    titlu_sedinta = next(
        (t for t in (_text(m.group(1)) for m in _SUMAR.finditer(pagina)) if _DATA_RO.search(t)),
        "",
    )
    celule = [_text(m.group(1)) for m in _TITLU.finditer(pagina)]
    titlu = max(celule, key=len) if celule else None
    idp = _IDP.search(pagina)

    interventii: list[Interventie] = []
    ultim: tuple[str | None, str | None, str | None, str | None, str | None] = (
        None,
        None,
        None,
        None,
        None,
    )
    for bloc in _BLOC.finditer(pagina):
        corp = bloc.group(1)
        propriu = _vorbitorul(corp)
        if propriu[0]:
            # The block announces its own speaker; the announcement is not part of the speech.
            ultim = propriu
            text = _text(_VORBITOR.sub(" ", corp, count=1))
        else:
            # The block carries no announcement — the chair carries on from the row above — so
            # the speaker is whoever was announced last on the page before it.
            inainte = _ultima_anuntare(pagina, bloc.start())
            if inainte[0]:
                ultim = inainte
            text = _text(corp)
        if not text:
            continue
        interventii.append(
            Interventie(
                ord=len(interventii),
                vorbitor=ultim[0],
                dep_idm=ultim[1],
                dep_leg=ultim[2],
                dep_camera=ultim[3],
                rol=ultim[4],
                text=text,
            )
        )
    return Stenograma(
        ids=ids,
        idm=idm,
        data=_data_iso(titlu_sedinta),
        camera=_camera(titlu_sedinta),
        titlu=titlu or None,
        idp=idp.group(1) if idp else None,
        url=url or url_stenograma(ids, idm),
        interventii=tuple(interventii),
    )


def _ultima_anuntare(
    pagina: str, pana_la: int
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """The last speaker announced before `pana_la`, or an empty tuple of Nones."""
    ultim = None
    for m in _VORBITOR.finditer(pagina, 0, pana_la):
        ultim = m
    return _vorbitorul(pagina[ultim.start() :]) if ultim else (None, None, None, None, None)


def adu_stenograma(ids: str, idm: str, *, opener=None) -> Stenograma:
    from scripts.cdep import _fetch

    url = url_stenograma(ids, idm)
    return parseaza_stenograma(
        _fetch(url, opener=opener or urllib.request.urlopen), ids, idm, url=url
    )


def de_adus(con: sqlite3.Connection) -> list[tuple[str, str]]:
    """The (sitting, item) pairs some step links and no transcript has been stored for yet.

    Distinct, not one per step: several bills are debated under one item and several steps of one
    bill can point at the same transcript, so fetching per step would ask the Chamber for the same
    page repeatedly.
    """
    return [
        (r[0], r[1])
        for r in con.execute(
            "SELECT DISTINCT e.steno_ids, e.steno_idm FROM initiativa_etapa e"
            " LEFT JOIN stenograma s ON s.ids = e.steno_ids AND s.idm = e.steno_idm"
            " WHERE e.steno_ids IS NOT NULL AND s.ids IS NULL"
        )
    ]


def scrie_stenograma(con: sqlite3.Connection, s: Stenograma) -> None:
    """Replace everything stored about one item with this reading of its page.

    Wholesale for the same reason a Fișa is: the page is the authority on its own sitting, and a
    speech has no identity of its own to merge on beyond its place in the order.
    """
    con.execute("DELETE FROM interventie WHERE ids = ? AND idm = ?", (s.ids, s.idm))
    con.execute(
        "DELETE FROM interventie_fts WHERE ids = ? AND idm = ?",
        (s.ids, s.idm),
    )
    con.execute(
        "INSERT OR REPLACE INTO stenograma (ids, idm, data, camera, titlu, plx_id, url, adus_la)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            s.ids,
            s.idm,
            s.data,
            s.camera,
            s.titlu,
            _plx_din_idp(con, s.idp),
            s.url,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    for it in s.interventii:
        con.execute(
            "INSERT OR REPLACE INTO interventie (ids, idm, ord, vorbitor, dep_idm, dep_leg,"
            " dep_camera, rol, text) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                s.ids,
                s.idm,
                it.ord,
                it.vorbitor,
                it.dep_idm,
                it.dep_leg,
                it.dep_camera,
                it.rol,
                it.text,
            ),
        )
        con.execute(
            "INSERT INTO interventie_fts (text, vorbitor, ids, idm, ord) VALUES (?,?,?,?,?)",
            (it.text, it.vorbitor or "", s.ids, s.idm, it.ord),
        )


def _plx_din_idp(con: sqlite3.Connection, idp: str | None) -> str | None:
    """The bill the transcript names, under the id the rest of the store keys bills on.

    The transcript links a Fișa by `idp`; everything else here is keyed on `plx_id`. Resolved
    through the collected initiatives rather than parsed out of the `PL-x 1/2021` string on the
    page, because the string is written several ways and the link is not.
    """
    if not idp:
        return None
    r = con.execute("SELECT plx_id FROM initiative WHERE idp = ?", (idp,)).fetchone()
    return r[0] if r else None


def colecteaza_stenograme(
    cale_db,
    *,
    pauza: float = 0.4,
    paralel: int = 1,
    rata: float = 2.0,
    limita: int | None = None,
    log=print,
) -> tuple[int, int, int]:
    """Fetch every transcript a step points at. Resumable: an item already stored is skipped.

    Returns `(items, speeches, failures)`.
    """
    import concurrent.futures as cf

    from scripts import depozit
    from scripts.parcurs import Ritm

    with depozit.deschide(cale_db) as con:
        de_facut = de_adus(con)
    if limita:
        de_facut = de_facut[:limita]
    log(f"{len(de_facut)} stenograme de adus")

    ritm = Ritm(rata) if paralel > 1 else None
    stenograme = 0
    interventii = 0
    esuate = 0

    def adu_una(pereche):
        ids, idm = pereche
        if ritm:
            ritm.asteapta()
        try:
            return pereche, adu_stenograma(ids, idm)
        except Exception as e:  # noqa: BLE001 - a dead page must not stop the run
            return pereche, e

    with depozit.deschide(cale_db) as con:
        if paralel > 1:
            with cf.ThreadPoolExecutor(max_workers=paralel) as pool:
                rezultate = pool.map(adu_una, de_facut)
                for i, (pereche, s) in enumerate(rezultate, start=1):
                    stenograme, interventii, esuate = _stocheaza(
                        con, pereche, s, stenograme, interventii, esuate, log
                    )
                    if i % 25 == 0 or i == len(de_facut):
                        con.commit()
                        log(f"  {i}/{len(de_facut)} · {interventii} intervenții · {esuate} eșuate")
        else:
            for i, pereche in enumerate(de_facut, start=1):
                _, s = adu_una(pereche)
                stenograme, interventii, esuate = _stocheaza(
                    con, pereche, s, stenograme, interventii, esuate, log
                )
                if i % 25 == 0 or i == len(de_facut):
                    con.commit()
                    log(f"  {i}/{len(de_facut)} · {interventii} intervenții · {esuate} eșuate")
                if pauza:
                    time.sleep(pauza)
    log(f"gata: {stenograme} stenograme · {interventii} intervenții · {esuate} eșuate")
    return stenograme, interventii, esuate


def _stocheaza(con, pereche, s, stenograme, interventii, esuate, log):
    if isinstance(s, Exception):
        log(f"  ids={pereche[0]} idm={pereche[1]}: {s}")
        return stenograme, interventii, esuate + 1
    scrie_stenograma(con, s)
    return stenograme + 1, interventii + len(s.interventii), esuate


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Adu dezbaterile pe care pașii le indică.")
    p.add_argument("--db", required=True)
    p.add_argument("--pauza", type=float, default=0.4)
    p.add_argument("--paralel", type=int, default=1)
    p.add_argument("--rata", type=float, default=2.0)
    p.add_argument("--limita", type=int)
    a = p.parse_args(argv)
    colecteaza_stenograme(a.db, pauza=a.pauza, paralel=a.paralel, rata=a.rata, limita=a.limita)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
