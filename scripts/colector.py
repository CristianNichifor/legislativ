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
from scripts.api import Client, Inregistrare, RaspunsLent
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


@dataclass(frozen=True)
class Actualizare:
    """What a freshness run did: which tail it re-walked, and how much of it was new."""

    pagini: int  # pages re-fetched this run
    acte_scrise: int  # rows upserted (new + rewritten)
    acte_noi: int  # net growth in the corpus (after − before)
    ultima_veche: int  # the corpus end when the run started
    ultima_noua: int  # the corpus end the run discovered


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


# Why each retry happened, counted for the run. Read by the caller to report whether the service
# was asking for room (429/503) or the client was at fault, rather than guessing from a rate.
RETRAGERI: dict[str, int] = {}


def _pagina(
    client: Client, pagina: int, incercari: int = 6, deadline: float = 120.0
) -> list[Inregistrare]:
    """One page, under a hard deadline, retried with exponential backoff.

    Backoff covers both the service asking for room (503/429) and a withheld body, because both
    are the same event from the collector's side — the page did not arrive, wait and ask again.

    **The deadline is enforced inside the read, not around it.** An earlier version ran each
    request in a throwaway `ThreadPoolExecutor` and, on timeout, abandoned the worker — which
    left the socket open and the thread alive. Two full runs died of it: the collector took
    roughly a hundred pages, then sat at zero throughput with hundreds of fds in `CLOSE-WAIT`
    while a fresh process got an answer from the same service in half a second. Nothing about
    that failure looks like a failure — the process is up, the log is quiet, and the corpus
    simply stops growing. `api.RaspunsLent` replaces it: the body read carries its own deadline
    and closes the response before raising, so a slow page costs one page and not the run.
    """
    astept = 2.0
    for incercare in range(incercari):
        motiv = ""
        try:
            return client.search(pagina=pagina, pe_pagina=10, termen_corp=deadline)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or incercare == incercari - 1:
                raise
            motiv = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, RaspunsLent) as e:
            if incercare == incercari - 1:
                raise
            motiv = type(e).__name__
        # Retries used to be silent, which is how a run could spend hours backing off against a
        # token the service had discarded while the log stayed empty and the process looked
        # healthy. A 429 or a 503 is the service asking for room and is the one signal that says
        # concurrency is too high — it has to be visible to be acted on.
        RETRAGERI[motiv] = RETRAGERI.get(motiv, 0) + 1
        print(
            f"  ! pagina {pagina}: {motiv}, reîncerc peste {astept:.0f}s "
            f"(încercarea {incercare + 2}/{incercari})",
            flush=True,
        )
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
            # Every 20 pages, not every 100. The commit interval is not a performance knob, it is
            # how much work a kill throws away and how long a watcher waits before it can tell a
            # working collector from a stuck one. Re-collecting over an existing corpus is several
            # times slower than filling an empty one — each act is deleted, cascaded and
            # re-indexed rather than simply inserted — and at 100 pages a run could spend minutes
            # doing real work with nothing durable to show for it, look stalled, get restarted,
            # and lose the lot. Twenty pages is roughly half a minute of work at any observed rate.
            if i % 20 == 0:
                con.commit()
                log(f"  {i}/{len(de_facut)} pagini · {scrise} acte scrise · {sarite} sărite")
            if pauza:
                time.sleep(pauza)
    return Progres(len(de_facut), scrise, sarite, ultima)


def actualizeaza(
    cale_db: str = "corpus.db",
    *,
    client: Client | None = None,
    sfarsit: int | None = None,
    margine: int = 3,
    pauza: float = 0.0,
    timeout: float = 90.0,
    log=print,
) -> Actualizare:
    """Bring a fully-collected corpus up to date by re-walking its tail.

    The API has no `modified-since` and no date filter, but its enumeration is chronological and
    append-at-end — the whole resumable walk relies on that — so new law lands on new pages past
    the old end, and a law amended since arrives as a new amending act on one of those pages. So
    freshness is not a diff against the server; it is re-discovering the end and re-collecting from
    a little before the previous end to it.

    Two things make the tail, not just the new pages: the last page collected was very likely
    *partial* when it was written (a page holds ten acts; the corpus rarely ends on a boundary), so
    re-fetching it picks up the acts that filled it since — `pagina_terminata` is INSERT-OR-REPLACE,
    the write is idempotent. `margine` is how many completed pages back from the old end to redo,
    small cover against that partial page and ordinary churn.

    This is for a corpus whose initial walk has finished. While it is still filling, the resumable
    `colecteaza` is the mechanism — it already recomputes the end each run and collects whatever is
    new — and this refuses an empty corpus rather than pretending a first walk is an update.
    """
    client = client or Client(timeout=timeout)
    with depozit.deschide(cale_db, readonly=True) as con:
        gata = depozit.pagini_terminate(con)
        acte_inainte = depozit.rezumat(con)["acte"]
    if not gata:
        log("corpus gol — folosește `colecteaza` pentru colectarea inițială, nu `actualizeaza`")
        return Actualizare(0, 0, 0, 0, 0)

    ultima = max(gata)
    if sfarsit is None:
        sfarsit = _gaseste_sfarsitul(client, log=log)
    start = max(1, ultima - margine + 1)
    pagini = list(range(start, sfarsit + 1))
    log(
        f"sfârșit vechi ~{ultima}, sfârșit acum ~{sfarsit}; "
        f"reîmprospătez {len(pagini)} pagini (de la {start})"
    )

    scrise = 0
    with depozit.deschide(cale_db) as con:
        for i, p in enumerate(pagini, start=1):
            recs = _pagina(client, p, deadline=timeout + 30)
            pe_pagina = 0
            for rec in recs:
                act = act_din_inregistrare(rec)
                if act is None:
                    continue
                depozit.scrie_inregistrare(con, rec, act)
                scrise += 1
                pe_pagina += 1
            depozit.pagina_terminata(con, p, pe_pagina)
            if i % 50 == 0:
                con.commit()
                log(f"  {i}/{len(pagini)} pagini · {scrise} acte scrise")
            if pauza:
                time.sleep(pauza)
        acte_dupa = depozit.rezumat(con)["acte"]

    return Actualizare(len(pagini), scrise, acte_dupa - acte_inainte, ultima, sfarsit)


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
    ap.add_argument("--lucratori", type=int, default=1, help="concurență (1 = lent și constant)")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--stop", type=int, default=None)
    ap.add_argument("--pauza", type=float, default=0.5, help="secunde între pagini, per lucrător")
    ap.add_argument("--timeout", type=float, default=90.0, help="secunde per cerere")
    ap.add_argument(
        "--actualizeaza",
        action="store_true",
        help="reîmprospătează un corpus deja colectat (re-parcurge coada), nu colecta de la zero",
    )
    ap.add_argument("--margine", type=int, default=3, help="pagini de coadă re-parcurse la update")
    ap.add_argument(
        "--graf",
        nargs="?",
        const="graf.db",
        default=None,
        help="după update, reconstruiește graful (implicit graf.db)",
    )
    a = ap.parse_args()

    if a.actualizeaza:
        u = actualizeaza(a.db, margine=a.margine, pauza=a.pauza, timeout=a.timeout, sfarsit=a.stop)
        print(
            f"\ngata: {u.acte_noi} acte noi ({u.acte_scrise} scrise/rescrise), "
            f"coadă {u.ultima_veche}→{u.ultima_noua}, {u.pagini} pagini re-parcurse"
        )
        if a.graf:
            from scripts.graf import construieste

            print(f"reconstruiesc graful în {a.graf}…")
            construieste(a.db, a.graf)
        with depozit.deschide(a.db) as con:
            print("rezumat:", depozit.rezumat(con))
        return 0

    p = colecteaza(
        a.db,
        lucratori=a.lucratori,
        pagina_start=a.start,
        pagina_stop=a.stop,
        pauza=a.pauza,
        timeout=a.timeout,
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
