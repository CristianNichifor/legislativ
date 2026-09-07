"""How each member voted, name by name.

`parcurs.py` reads the tally off a Fișa — `pentru=275, contra=34, abtineri=0, nu au votat=3` — and
that is the room's answer, not anybody's. The same step links `evot2015.Nominal?idv=25475`, the
Chamber's own roll of the division, and it names every member and what they pressed. The link was
captured with the vote row for exactly this; nothing read it until now.

It is the question a voter actually has. "The bill passed 275 to 34" is a fact about Parliament;
"your deputy voted against it" is a fact about the person they elected, and it is the only one of
the two they can do anything with.

**The join is the Chamber's own key.** Each name on the roll is wrapped in
`structura2015.mp?idm=1&cam=2&leg=2020` — the same `(leg, camera, idm)` triple the profiles, the
signatures and the speeches are all keyed on. So a vote attaches to the person who cast it through
the id, never through the printed name, which splits `Şovăială` from `Șovăială` and merges two
people who share one.

**Two silences that are not the same, and are not merged.** A member listed with `-` was in the
room and did not vote. A member not listed at all was not there. The page states the first and is
silent about the second, so only the first is stored — 312 names on a roll where the Chamber has
330 members is 18 absences the page never mentions, and inventing rows for them would be inventing
attendance records.

**The option is stored as the page prints it, and folded alongside.** `DA`, `NU`, `AB`, `-` are
what the roll shows; `brut` keeps them verbatim so a reading can always be checked against the
source, and `optiune` carries the folded form the app groups on.
"""

from __future__ import annotations

import re
import sqlite3
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from scripts.ritm import Ritm
from scripts.text import normalizeaza

BAZA = "https://www.cdep.ro/ords/pls/steno/evot2015.Nominal"

# One member's row: position, their own link, the printed name, the group, the option.
_RAND = re.compile(
    r"<td[^>]*>\s*\d+\.\s*</td>\s*"
    r'<td[^>]*><a href="[^"]*structura2015\.mp\?(?P<legatura>[^"]*)"[^>]*>(?P<nume>.*?)</a></td>\s*'
    r"<td[^>]*>(?P<grup>.*?)</td>\s*<td[^>]*>(?P<optiune>.*?)</td>",
    re.S | re.I,
)
_IDM = re.compile(r"(?:^|[?&])idm=(\d+)")
_CAM = re.compile(r"(?:^|[?&])cam=(\d+)")
_LEG = re.compile(r"(?:^|[?&])leg=(\d+)")
CAM_NUME: dict[str, str] = {"1": "Senat", "2": "Camera Deputaților"}
# `Subiect vot: Vot final / Adoptare PL 1/2021 pentru aprobarea...`
_SUBIECT = re.compile(r"Subiect vot:\s*</td>\s*<td[^>]*>(.*?)</td>", re.S | re.I)
_SEDINTA = re.compile(r"Sedinta:\s*</td>\s*<td[^>]*>(.*?)</td>", re.S | re.I)
_IDP = re.compile(r"upl_pck2015\.proiect\?idp=(\d+)")
_ETICHETA = re.compile(r"<[^>]+>")

# What the roll prints, folded. `-` is the member who was in the room and did not vote, which is
# not the same fact as being absent and is not stored as one.
OPTIUNI: dict[str, str] = {
    "da": "da",
    "nu": "nu",
    "ab": "abtinere",
    "abtinere": "abtinere",
    "-": "nu_a_votat",
}


@dataclass(frozen=True)
class Optiune:
    """One member's vote in one division."""

    idm: str
    leg: str | None
    camera: str | None
    nume: str
    grup: str | None
    optiune: str
    brut: str


@dataclass(frozen=True)
class Nominal:
    """One division's roll."""

    idv: str
    camera: str | None
    subiect: str | None
    idp: str | None
    url: str
    optiuni: tuple[Optiune, ...] = ()


def url_nominal(idv: str) -> str:
    return f"{BAZA}?idv={idv}"


def _text(brut: str) -> str:
    """Markup to one line of readable text.

    Whitespace is collapsed rather than merely stripped: the roll writes the subject across four
    lines — `Vot final`, `Adoptare`, `PL 1/2021`, then the title — and a stored newline renders as
    a broken heading everywhere it is shown.
    """
    import html as _html

    return " ".join(normalizeaza(_ETICHETA.sub(" ", _html.unescape(brut))).split())


def parseaza_nominal(pagina: str, idv: str, *, url: str | None = None) -> Nominal:
    """One roll page into one row per member. Everything is read off the page."""
    subiect = _SUBIECT.search(pagina)
    sedinta = _SEDINTA.search(pagina)
    idp = _IDP.search(pagina)

    optiuni: list[Optiune] = []
    for m in _RAND.finditer(pagina):
        legatura = m.group("legatura")
        idm = _IDM.search(legatura)
        if not idm:
            continue
        cam = _CAM.search(legatura)
        leg = _LEG.search(legatura)
        brut = _text(m.group("optiune"))
        optiuni.append(
            Optiune(
                idm=idm.group(1),
                leg=leg.group(1) if leg else None,
                camera=CAM_NUME.get(cam.group(1)) if cam else None,
                nume=_text(m.group("nume")),
                grup=_text(m.group("grup")) or None,
                optiune=OPTIUNI.get(brut.lower(), "necunoscut"),
                brut=brut,
            )
        )
    camera = _text(sedinta.group(1)) if sedinta else None
    return Nominal(
        idv=idv,
        camera=("Camera Deputaților" if camera and "deputa" in camera.lower() else camera),
        subiect=_text(subiect.group(1)) if subiect else None,
        idp=idp.group(1) if idp else None,
        url=url or url_nominal(idv),
        optiuni=tuple(optiuni),
    )


def adu_nominal(idv: str, *, opener=None) -> Nominal:
    from scripts.cdep import _fetch

    url = url_nominal(idv)
    return parseaza_nominal(_fetch(url, opener=opener or urllib.request.urlopen), idv, url=url)


def de_adus(con: sqlite3.Connection) -> list[str]:
    """The divisions a vote row links a roll for and no roll has been stored yet."""
    return [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT v.idv FROM initiativa_vot v"
            " LEFT JOIN vot_nominal_sedinta s ON s.idv = v.idv"
            " WHERE v.idv IS NOT NULL AND s.idv IS NULL"
        )
    ]


def scrie_nominal(con: sqlite3.Connection, n: Nominal) -> None:
    """Replace one division's roll. The page is the authority on its own division."""
    con.execute("DELETE FROM vot_nominal WHERE idv = ?", (n.idv,))
    con.execute(
        "INSERT OR REPLACE INTO vot_nominal_sedinta (idv, camera, subiect, idp, url, adus_la)"
        " VALUES (?,?,?,?,?,?)",
        (
            n.idv,
            n.camera,
            n.subiect,
            n.idp,
            n.url,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    for o in n.optiuni:
        con.execute(
            "INSERT OR REPLACE INTO vot_nominal (idv, idm, leg, camera, nume, grup, optiune, brut)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (n.idv, o.idm, o.leg, o.camera, o.nume, o.grup, o.optiune, o.brut),
        )


def colecteaza_nominale(
    cale_db,
    *,
    paralel: int = 1,
    rata: float = 2.0,
    limita: int | None = None,
    log=print,
) -> tuple[int, int, int]:
    """Fetch every roll a vote row links. Resumable. Returns `(rolls, options, failures)`."""
    from scripts import depozit

    with depozit.deschide(cale_db) as con:
        de_facut = de_adus(con)
    if limita:
        de_facut = de_facut[:limita]
    log(f"{len(de_facut)} voturi nominale de adus")

    ritm = Ritm(rata) if paralel > 1 else None
    sedinte = optiuni = esuate = 0

    def adu_unul(idv):
        if ritm:
            ritm.asteapta()
        try:
            return idv, adu_nominal(idv)
        except Exception as e:  # noqa: BLE001 - one dead page must not stop the run
            return idv, e

    with depozit.deschide(cale_db) as con:
        rezultate = (
            ThreadPoolExecutor(max_workers=paralel).map(adu_unul, de_facut)
            if paralel > 1
            else (adu_unul(x) for x in de_facut)
        )
        for i, (idv, n) in enumerate(rezultate, start=1):
            if isinstance(n, Exception):
                esuate += 1
                log(f"  idv={idv}: {n}")
            else:
                scrie_nominal(con, n)
                sedinte += 1
                optiuni += len(n.optiuni)
            if i % 25 == 0 or i == len(de_facut):
                con.commit()
                log(f"  {i}/{len(de_facut)} · {optiuni} opțiuni · {esuate} eșuate")
        con.commit()
    log(f"gata: {sedinte} voturi nominale · {optiuni} opțiuni · {esuate} eșuate")
    return sedinte, optiuni, esuate


def cum_a_votat(
    con: sqlite3.Connection, idm: str, leg: str | None, camera: str | None, *, limita: int = 40
) -> list[dict]:
    """How one member voted, newest first, with what the division was about.

    Joined on `(leg, camera, idm)` and never on the name — the same key their signatures and their
    speeches hang off, so a profile is one person rather than everyone who shares a surname.
    """
    try:
        return [
            {
                "idv": r[0],
                "optiune": r[1],
                "brut": r[2],
                "subiect": r[3],
                "data": r[4],
                "plx_id": r[5],
                "rezultat": r[6],
            }
            for r in con.execute(
                "SELECT n.idv, n.optiune, n.brut, s.subiect, v.data, v.plx_id, v.rezultat"
                " FROM vot_nominal n"
                " JOIN vot_nominal_sedinta s ON s.idv = n.idv"
                " LEFT JOIN initiativa_vot v ON v.idv = n.idv"
                " WHERE n.idm = ? AND n.leg IS ? AND n.camera IS ?"
                " ORDER BY v.data DESC LIMIT ?",
                (idm, leg, camera, limita),
            )
        ]
    except sqlite3.OperationalError:
        # No rolls collected in this store.
        return []


def rolul(con: sqlite3.Connection, idv: str) -> dict:
    """One division's roll, grouped the way the chamber sits: by parliamentary group."""
    cap = con.execute(
        "SELECT camera, subiect, idp, url FROM vot_nominal_sedinta WHERE idv = ?", (idv,)
    ).fetchone()
    if not cap:
        return {"gasit": False, "idv": idv, "grupuri": []}
    randuri = con.execute(
        "SELECT grup, optiune, nume, idm, leg, camera FROM vot_nominal WHERE idv = ?"
        " ORDER BY grup, nume",
        (idv,),
    ).fetchall()
    pe_grup: dict[str, list] = {}
    for grup, optiune, nume, idm, leg, camera in randuri:
        pe_grup.setdefault(grup or "—", []).append(
            {"nume": nume, "optiune": optiune, "idm": idm, "leg": leg, "camera": camera}
        )
    return {
        "gasit": True,
        "idv": idv,
        "camera": cap[0],
        "subiect": cap[1],
        "idp": cap[2],
        "url": cap[3],
        "grupuri": [
            {
                "grup": g,
                "membri": m,
                "da": sum(1 for x in m if x["optiune"] == "da"),
                "nu": sum(1 for x in m if x["optiune"] == "nu"),
                "abtineri": sum(1 for x in m if x["optiune"] == "abtinere"),
                "nu_au_votat": sum(1 for x in m if x["optiune"] == "nu_a_votat"),
            }
            for g, m in sorted(pe_grup.items(), key=lambda kv: -len(kv[1]))
        ],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Adu rolul fiecărui vot: cine cum a votat.")
    p.add_argument("--db", required=True)
    p.add_argument("--paralel", type=int, default=1)
    p.add_argument("--rata", type=float, default=2.0)
    p.add_argument("--limita", type=int)
    a = p.parse_args(argv)
    colecteaza_nominale(a.db, paralel=a.paralel, rata=a.rata, limita=a.limita)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
