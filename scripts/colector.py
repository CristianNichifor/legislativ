"""Walk the whole corpus through the API, once, politely, and resumably.

This is the job that turns an empty database into a national corpus. It is not fast and it is not
meant to be: measuring the service showed four concurrent readers sustaining about five pages a
second — roughly ninety minutes for all ~251 000 acts — while six readers earned an immediate
`HTTP 503`. The ceiling is the server's, not the client's, so this collector is built to run
long and survive interruruption rather than to sprint:

- **Resumable.** Every page that lands is recorded in `progres`; a re-run skips what is done. A
  ninety-minute job that cannot resume is a job that never finishes, because a laptop sleeps, a
  network blips, or someone hits Ctrl-C to read the news.
- **Backing off.** A `503`, a `429` or a timeout is the service asking for room, so the worker
  waits — doubling, capped — and tries again rather than hammering. A run that provokes 503s is
  collecting slower than one that stays under the limit, quite apart from being rude to a
  ministry's server.
- **Bounded.** Concurrency defaults to four, the level that did not draw a 503. Higher is a flag,
  not an edit, so raising it is a decision someone makes on purpose.

**Enumeration is the API's unfiltered `Search`, paged.** It returns the whole corpus in
chronological order, ten to a page, and it has no act-type filter — so this fetches everything and
keeps the six normative types the linter needs, dropping the other 166 (`ADEVERINȚĂ`,
`AMENAJAMENT`, and so on) on the way in. What was dropped is counted and reported, because a
corpus that quietly discards five sixths of what it saw should say so.

Run it: `python -m scripts.colector --db corpus.db`. Stop it whenever; run it again to continue.
"""

from __future__ import annotations

import argparse
import re
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from scripts import depozit
from scripts.api import Client, Inregistrare
from scripts.text import cheie

# The API returns a type as a display string; the linter keys acts by a slug. The six normative
# types get short canonical slugs the rest of the package already speaks; every other type keeps
# a slug derived from its name. Nothing is filtered by type at collection: the network cost of a
# record is paid to enumerate it whether or not it is kept, so discarding it saves only disk and
# throws away data that cannot be cheaply re-fetched — including the codes (Codul fiscal, muncii,
# penal), the implementing norms `vid.py` hunts for, and the draft bills a duplicate-check needs.
# The product filters by `tip` at query time; the collector keeps what it can key.
TIP_CANONIC: dict[str, str] = {
    "lege": "lege",
    "ordonanta de urgenta": "oug",
    "ordonanta": "og",
    "hotarare": "hg",
    "ordin": "ordin",
    "decret": "decret",
}

# The six the in-force linter reasons about. A query-time filter, not a collection-time one.
TIP_NORMATIV: frozenset[str] = frozenset(TIP_CANONIC.values())


def slug_tip(tip_act: str) -> str:
    """Canonical slug for the six, a name-derived slug for the other 166."""
    c = cheie(tip_act)
    return TIP_CANONIC.get(c, re.sub(r"[^a-z0-9]+", "-", c).strip("-") or "necunoscut")


_AN = re.compile(r"\b(1[6-9]\d{2}|20\d{2})\b")


@dataclass(frozen=True)
class Progres:
    """What a run did, so it can report itself rather than be trusted."""

    pagini: int
    acte_scrise: int
    sarite_tip: int
    ultima_pagina: int


def este_normativ(tip_act: str) -> bool:
    """Whether a type is one of the six the in-force linter reasons about."""
    return slug_tip(tip_act) in TIP_NORMATIV


def _an(rec: Inregistrare) -> int | None:
    if rec.an:
        return rec.an
    if rec.data_vigoare:
        return rec.data_vigoare.year
    m = _AN.search(rec.titlu)
    return int(m.group(1)) if m else None


def act_din_inregistrare(rec: Inregistrare):
    """An API record to an `Act`, or None when it cannot be keyed.

    Keyable means a type slug, a number and a year — the three that make `tip-numar-an`, the id
    every citation uses. Year is taken from the record, then its in-force date, then its title,
    because the API's `An` field comes back empty in practice. A numberless record (a LISTĂ, a
    RAPORT, a COMUNICAT) has no citable identity and is the only thing dropped; those are counted
    so the skip is visible, not silent.
    """
    from scripts.referinte import Act

    an = _an(rec)
    numar = rec.numar.replace(".", "") or None
    if an is None or numar is None:
        return None
    return Act(slug_tip(rec.tip_act), numar, an)


class _Trickle(Exception):
    """The server accepted the connection and then withheld the response past the deadline."""


def _cu_termen(fn, secunde: float):
    """Run `fn` under a hard wall-clock deadline. A socket timeout is not enough here: this
    server trickles a byte at a time, and a per-recv timeout never fires while bytes dribble in,
    so a worker blocks forever in the read. A one-shot executor gives a deadline the trickle
    cannot reset; if it lapses the underlying socket is abandoned (a rare leak, cheap against a
    quarter-million pages) and the page is retried."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FTimeout

    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=secunde)
    except FTimeout as e:
        raise _Trickle from e
    finally:
        ex.shutdown(wait=False)


def _pagina(
    client: Client, pagina: int, incercari: int = 6, deadline: float = 120.0
) -> list[Inregistrare]:
    """One page, under a hard deadline, retried with exponential backoff.

    Backoff covers both the service asking for room (503/429) and the trickle-hang, because both
    are the same event from the collector's side — the page did not arrive, wait and ask again.
    """
    astept = 2.0
    for incercare in range(incercari):
        try:
            return _cu_termen(lambda: client.search(pagina=pagina, pe_pagina=10), deadline)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or incercare == incercari - 1:
                raise
        except (urllib.error.URLError, TimeoutError, _Trickle):
            if incercare == incercari - 1:
                raise
        time.sleep(astept)
        astept = min(astept * 2, 20.0)
    return []


def colecteaza(
    cale_db: str = "corpus.db",
    *,
    client: Client | None = None,
    lucratori: int = 4,
    pagina_start: int = 1,
    pagina_stop: int | None = None,
    pauza: float = 0.0,
    timeout: float = 90.0,
    log=print,
) -> Progres:
    """Fetch every page not already done, write the normative acts, skip the rest.

    Pages are fetched concurrently but written on one connection in the main thread: SQLite is
    happiest with a single writer, and the network is the bottleneck anyway, so the writer is
    never what holds a run up.
    """
    # The request timeout is generous on purpose. Under sustained collection this server
    # throttles by trickling the body — the bytes still arrive, just slowly — so a short deadline
    # does not fix a hang, it kills a read that was going to finish and retries it forever. A
    # long timeout lets a throttled page complete; one worker keeps only one connection open at a
    # time, which is what keeps the throttle from tightening in the first place. Slow and constant
    # beats fast and wedged. The executor deadline downstream is a last-resort guard against a
    # truly dead socket, set well above this so it fires only when the socket really is dead.
    client = client or Client(timeout=timeout)
    with depozit.deschide(cale_db) as con:
        gata = depozit.pagini_terminate(con)

    # The end is where `Search` stops returning rows. Discovered, not assumed, so the collector
    # keeps working when the corpus grows past whatever number was true when this was written.
    if pagina_stop is None:
        pagina_stop = _gaseste_sfarsitul(client, log=log)
    de_facut = [p for p in range(pagina_start, pagina_stop + 1) if p not in gata]
    log(f"{len(gata)} pagini deja colectate; {len(de_facut)} de făcut (până la {pagina_stop})")

    scrise = sarite = ultima = 0
    with depozit.deschide(cale_db) as con, ThreadPoolExecutor(max_workers=lucratori) as ex:
        viitoare = {ex.submit(_pagina, client, p, deadline=timeout + 30): p for p in de_facut}
        for i, fut in enumerate(as_completed(viitoare), start=1):
            pagina = viitoare[fut]
            recs = fut.result()
            pe_pagina = 0
            for rec in recs:
                act = act_din_inregistrare(rec)
                if act is None:
                    sarite += 1
                    continue
                depozit.scrie_inregistrare(con, rec, act)
                scrise += 1
                pe_pagina += 1
            depozit.pagina_terminata(con, pagina, pe_pagina)
            ultima = max(ultima, pagina)
            if i % 100 == 0:
                con.commit()
                log(f"  {i}/{len(de_facut)} pagini · {scrise} acte scrise · {sarite} sărite")
            if pauza:
                time.sleep(pauza)
    return Progres(len(de_facut), scrise, sarite, ultima)


def _gaseste_sfarsitul(client: Client, *, log=print) -> int:
    """Binary-search the last non-empty page. A dozen requests to size a quarter-million-doc job."""
    lo, hi = 1, 40000
    while client.search(pagina=hi, pe_pagina=10):
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if client.search(pagina=mid, pe_pagina=10):
            lo = mid
        else:
            hi = mid
        time.sleep(0.3)
    log(f"corpus se termină la pagina {lo} (~{lo * 10} documente)")
    return lo


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--lucratori", type=int, default=4, help="concurență (4 = sub pragul de 503)")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--stop", type=int, default=None)
    ap.add_argument("--pauza", type=float, default=0.0, help="secunde între pagini, per lucrător")
    a = ap.parse_args()
    p = colecteaza(
        a.db, lucratori=a.lucratori, pagina_start=a.start, pagina_stop=a.stop, pauza=a.pauza
    )
    print(
        f"\ngata: {p.acte_scrise} acte normative scrise, {p.sarite_tip} sărite (alt tip), "
        f"{p.pagini} pagini"
    )
    with depozit.deschide(a.db) as con:
        print("rezumat:", depozit.rezumat(con))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
