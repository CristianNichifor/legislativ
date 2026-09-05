"""Pending legislative initiatives, from the Chamber of Deputies.

The linter answers "does this draft fight the law that exists". This module feeds the other
half: "does this draft repeat a bill already moving". Romania is bicameral, so an initiative has
a number in each chamber — `Pl-x nr. 33/2025` at the Chamber of Deputies, `L576/2024` at the
Senate — and they are the same bill seen from two rooms. cdep.ro's Fișa carries both numbers and
links across, so this collects from cdep alone rather than scraping both and trying to join them
afterwards.

**Why cdep is the spine and not the Senate.** cdep's "urmărirea procesului legislativ" tracks the
whole passage — registration, stage, decision chamber, the Senate counterpart id — in one Fișa.
The Senate portal is the same data from the other side. One source, cross-referenced, is less to
keep consistent than two sources merged.

**What a Fișa gives, read off a real one:** the descriptive title, the *obiect de reglementare*
(what the bill sets out to do — the text a duplicate-check compares), the type (proiect vs
propunere), whether it is on the emergency track, the current stage (so a dead initiative is not
offered as a live duplicate), the decision chamber, and the Senate id. The bill's target acts are
not a field — they are read from the title and obiect by `amendamente.py`, which is the point of
having built it: two initiatives that both amend art. 7 of Legea 98/2016 are the duplicate worth
flagging, and that target comes out of the same extractor the linter already uses.

Politeness is the same posture as the main collector — an identifying User-Agent, backoff on the
server asking for room — but cdep is a different host on different software (Oracle ORDS), so it
gets its own thin fetcher rather than sharing the SOAP client. Enumeration is per year:
`lista?cam=2&anp=YYYY` lists a year's initiatives, a few hundred each, every one an `idp` handle
to a Fișa.
"""

from __future__ import annotations

import gzip
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from scripts import depozit
from scripts.text import cheie, normalizeaza

BASE = "https://www.cdep.ro/ords/pls/proiecte/upl_pck2015"
CAM_DEPUTATI = 2
USER_AGENT = (
    "legislativ-linter/0.1 (+https://github.com/CristianNichifor/legislativ; "
    "contact: cristian@cnwebify.com)"
)

_IDP = re.compile(r"upl_pck2015\.proiect\?cam=(\d+)&idp=(\d+)")
_SENAT = re.compile(r"\b([BL]\.?\s?\d{2,4}/\d{4})\b")
_CD_NR = re.compile(r"(\d+)\s*/\s*(\d{2})\.(\d{2})\.(\d{4})")


@dataclass(frozen=True)
class Initiativa:
    """One initiative as its Fișa states it. `obiect` is the text a duplicate-check compares."""

    plx_id: str
    cam: int
    idp: str
    senat_id: str | None
    tip: str
    titlu: str
    obiect: str
    urgenta: bool
    stadiu: str
    camera_decizionala: str
    data_inreg: str | None
    sursa_url: str


def _fetch(
    url: str, *, timeout: float = 40.0, incercari: int = 5, opener=urllib.request.urlopen
) -> str:
    """One GET, retried with backoff when the server asks for room."""
    astept = 2.0
    for i in range(incercari):
        try:
            cerere = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
            )
            with opener(cerere, timeout=timeout) as r:
                brut = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    brut = gzip.decompress(brut)
                return brut.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == incercari - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == incercari - 1:
                raise
        time.sleep(astept)
        astept = min(astept * 2, 60.0)
    return ""


def _celule(rand: str) -> list[str]:
    return [
        normalizeaza(re.sub(r"<[^>]+>", " ", c)).strip()
        for c in re.findall(r"<td[^>]*>(.*?)</td>", rand, re.S)
    ]


def _camp(randuri: list[list[str]], eticheta: str) -> str:
    """Value of the first label/value row whose label contains `eticheta` (diacritic-folded)."""
    tinta = cheie(eticheta)
    for cel in randuri:
        celule = [c for c in cel if c]
        if len(celule) >= 2 and tinta in cheie(celule[0]):
            return celule[1]
    return ""


def idp_din_an(an: int, cam: int = CAM_DEPUTATI, *, opener=urllib.request.urlopen) -> list[str]:
    """Every initiative handle registered in a year. A few hundred per year."""
    html = _fetch(f"{BASE}.lista?cam={cam}&anp={an}", opener=opener)
    return list(dict.fromkeys(m.group(2) for m in _IDP.finditer(html)))


def parseaza_fisa(html: str, idp: str, cam: int, url: str = "") -> Initiativa:
    """One Fișa page into an Initiativa. Labels are matched folded, so cedilla spellings match."""
    randuri = [_celule(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)]

    cd = _camp(randuri, "Camera Deputatilor")
    m = _CD_NR.search(cd)
    if m:
        numar, an = m.group(1), m.group(4)
        data_inreg = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
    else:
        pt = re.search(r"Pl-?x[.\s]*(\d+)/(\d{4})", html)
        numar, an = (pt.group(1), pt.group(2)) if pt else (idp, "0")
        data_inreg = None

    senat = _camp(randuri, "Senat")
    senat_m = _SENAT.search(senat)

    obiect = _camp(randuri, "obiect de reglementare")
    titlu = next(
        (
            c[1]
            for c in randuri
            if len(c) >= 2 and cheie(c[0]) in ("titlu", "denumire") and len(c[1]) > 15
        ),
        obiect or f"Pl-x {numar}/{an}",
    )

    return Initiativa(
        plx_id=f"plx-{numar}-{an}",
        cam=cam,
        idp=idp,
        senat_id=senat_m.group(1).replace(" ", "").replace(".", "") if senat_m else None,
        tip=cheie(_camp(randuri, "Tip initiativa")) or "necunoscut",
        titlu=titlu,
        obiect=obiect,
        urgenta=cheie(_camp(randuri, "Procedura de urgenta")).startswith("da"),
        stadiu=_camp(randuri, "Stadiu"),
        camera_decizionala=_camp(randuri, "Camera decizionala"),
        data_inreg=data_inreg,
        sursa_url=url,
    )


def fisa(idp: str, cam: int = CAM_DEPUTATI, *, opener=urllib.request.urlopen) -> Initiativa:
    url = f"{BASE}.proiect?cam={cam}&idp={idp}"
    return parseaza_fisa(_fetch(url, opener=opener), idp, cam, url=url)


def colecteaza_cdep(
    cale_db: str = "corpus.db",
    *,
    ani: range | list[int],
    cam: int = CAM_DEPUTATI,
    pauza: float = 0.3,
    opener=urllib.request.urlopen,
    log=print,
) -> int:
    """Collect every initiative of the given years, skipping Fișe already stored.

    Sequential and unhurried on purpose: this is a few thousand small pages, not a quarter of a
    million, so there is nothing to gain from concurrency and a courteous single stream is the
    right posture toward a second ministry's server. Resumable — an `idp` already in the table
    is not fetched again.
    """
    with depozit.deschide(cale_db) as con:
        vazute = depozit.initiative_vazute(con)

    scrise = 0
    with depozit.deschide(cale_db) as con:
        for an in ani:
            idps = [i for i in idp_din_an(an, cam, opener=opener) if i not in vazute]
            log(f"{an}: {len(idps)} inițiative noi")
            for i, idp in enumerate(idps, start=1):
                try:
                    ini = fisa(idp, cam, opener=opener)
                except Exception as e:  # noqa: BLE001
                    log(f"  idp={idp}: {e}")
                    continue
                depozit.scrie_initiativa(con, ini)
                scrise += 1
                if i % 50 == 0:
                    con.commit()
                    log(f"  {an}: {i}/{len(idps)}")
                time.sleep(pauza)
    return scrise


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--de-la", type=int, default=2021)
    ap.add_argument("--pana-la", type=int, default=2026)
    ap.add_argument("--pauza", type=float, default=0.3)
    a = ap.parse_args()
    n = colecteaza_cdep(a.db, ani=range(a.de_la, a.pana_la + 1), pauza=a.pauza)
    print(f"\ngata: {n} inițiative")
    with depozit.deschide(a.db) as con:
        print("rezumat:", depozit.rezumat(con))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
