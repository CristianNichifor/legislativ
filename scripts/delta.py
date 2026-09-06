"""What changed since a copy was made, small enough to send to someone offline.

`distributie.py` cuts a 742 MB release. Romania publishes a few dozen acts on a working day, so
re-sending that release to say so is the difference between a corpus a team keeps current and one
they update twice and then stop. This is the increment: the acts written since a stated moment,
and nothing else.

**A copy's position is what it was last brought up to, recorded when it is.** The first design
derived it — `max(acte.citit_la)`, no bookkeeping, nothing that could disagree with the rows — and
it was wrong for a reason only measurement showed. A copy is not read-only: `surse.imbogateste`
rewrites acts locally, which sets their marks to *now*. That pushes a derived position past
everything the source wrote in between, and the next pack skips it — silently, permanently, and
worse the more local work the reader does. So `aplica` records the pack's own end, and only a copy
that has never been updated falls back to reading its rows.

**`citit_la` means "when this act's stored content last changed", and every write path maintains
it.** Collection sets it; so does upgrading an act's provisions from its HTML page
(`depozit.scrie_provizii`). A write that did not touch it would hide that act from every offline
copy for ever — not fail, just quietly never arrive.

**Replace, never merge.** An act in the pack replaces the act in the copy: its provisions, its
marked references, its relations, its strikes and its edges all go and come back together. Half of
an old parse beside half of a new one is a corpus nobody can reason about, which is the same rule
`depozit.scrie_act` follows for the same reason.

**What a pack cannot carry is a deletion.** The collector only ever adds and rewrites — nothing is
removed from the national corpus, so nothing needs removing from a copy. If that changes, this
needs a tombstone and a reader should be told rather than left with a row the source dropped.
`aplica` therefore never deletes an act the pack does not mention.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from scripts import depozit

# Copied wholesale for each act in the pack, keyed by the act. `provizii` carries the text and the
# search index is rebuilt from it; `lovituri` is keyed by document rather than act and is handled
# separately, because a decision's strikes belong to the decision that made them.
TABELE_ACT: tuple[str, ...] = ("provizii", "referinte_marcate")


@dataclass(frozen=True)
class Pachet:
    """What one increment contains, so a run reports itself rather than being trusted."""

    de_la: str
    pana_la: str
    acte: int
    provizii: int
    muchii: int
    lovituri: int
    octeti: int
    secunde: float

    def __str__(self) -> str:
        return (
            f"{self.acte} acte · {self.provizii} provizii · {self.muchii} muchii · "
            f"{self.lovituri} lovituri · {self.octeti / 1_048_576:.1f} MB · {self.secunde:.0f}s"
        )


def versiune(cale_db: str) -> str:
    """Where a copy stands — what it was last brought up to, or how far its rows reach.

    The recorded position wins, and the fallback is for a copy that has never had a pack applied:
    a freshly cut release, whose rows are the only statement of where it is.

    Deriving it always was the first design and it is unsafe, because a copy is not read-only.
    `surse.imbogateste` rewrites acts locally and sets their marks to now, which pushes a derived
    position past everything the source wrote in between — and the next pack skips exactly that
    range, permanently and without a symptom. An empty corpus has no position, and asking for
    everything since the empty string is asking for everything, which is right for a copy holding
    nothing.
    """
    cx = sqlite3.connect(f"file:{cale_db}?mode=ro", uri=True)
    try:
        rand = cx.execute("SELECT valoare FROM versiune WHERE cheie = 'adus_la'").fetchone()
        if rand and rand[0]:
            return rand[0]
        return cx.execute("SELECT coalesce(max(citit_la), '') FROM acte").fetchone()[0]
    except sqlite3.OperationalError:
        # A copy cut before this table existed. Its rows are all it can say.
        return cx.execute("SELECT coalesce(max(citit_la), '') FROM acte").fetchone()[0]
    finally:
        cx.close()


def _acte_de_la(cx: sqlite3.Connection, de_la: str) -> list[str]:
    """Qualified `sursa.acte`, not `acte`: the pack has an `acte` table of its own and it is empty
    at this point, so an unqualified name selects from the wrong database and every pack ships
    with nothing in it."""
    return [
        r[0]
        for r in cx.execute("SELECT id FROM sursa.acte WHERE citit_la > ? ORDER BY id", (de_la,))
    ]


def construieste(
    corpus_db: str,
    tinta: str,
    de_la: str,
    *,
    graf_db: str | None = None,
    log=print,
) -> Pachet:
    """Cut the increment a copy at `de_la` needs to catch up.

    The pack is itself a corpus — same schema, same tools — so a reader can open it, count it and
    search it before applying it. That costs a few kilobytes of empty tables and buys the ability
    to inspect an update rather than trust it.
    """
    t0 = time.monotonic()
    cale = Path(tinta)
    if cale.exists():
        cale.unlink()

    with depozit.deschide(tinta) as con:
        con.execute("ATTACH DATABASE ? AS sursa", (corpus_db,))
        ids = _acte_de_la(con, de_la)
        log(f"{len(ids)} acte scrise după {de_la or '(niciodată)'}")
        pana_la = de_la

        provizii = lovituri = muchii = 0
        if ids:
            con.execute("INSERT INTO acte SELECT * FROM sursa.acte WHERE citit_la > ?", (de_la,))
            for tabel in TABELE_ACT:
                cur = con.execute(
                    f"INSERT INTO {tabel} SELECT t.* FROM sursa.{tabel} t"
                    " JOIN sursa.acte a ON a.id = t.act_id WHERE a.citit_la > ?",
                    (de_la,),
                )
                if tabel == "provizii":
                    provizii = cur.rowcount
            con.execute(
                "INSERT INTO relatii SELECT r.* FROM sursa.relatii r"
                " JOIN sursa.acte a ON a.id = r.din_act WHERE a.citit_la > ?",
                (de_la,),
            )
            # Strikes belong to the *deciding* document, so they travel when the decision does —
            # not when the struck act does. A decision arriving in this pack brings its strikes;
            # one collected long ago keeps them in the copy already.
            cur = con.execute(
                "INSERT INTO lovituri SELECT l.* FROM sursa.lovituri l"
                " JOIN sursa.acte a ON a.id = l.cheie_act WHERE a.citit_la > ?",
                (de_la,),
            )
            lovituri = cur.rowcount
            pana_la = con.execute("SELECT max(citit_la) FROM main.acte").fetchone()[0] or de_la
        con.commit()
        con.execute("DETACH DATABASE sursa")

        # The index travels rebuilt rather than copied: it is derived from `provizii`, and a pack
        # small enough to send is a pack cheap enough to index.
        con.execute("INSERT INTO provizii_fts(provizii_fts) VALUES('rebuild')")
        con.commit()

    if graf_db and ids and Path(graf_db).is_file():
        muchii = _muchii(tinta, graf_db, ids)

    octeti = cale.stat().st_size
    p = Pachet(de_la, pana_la, len(ids), provizii, muchii, lovituri, octeti, time.monotonic() - t0)
    log(f"pachet: {p}")
    return p


def _muchii(tinta: str, graf_db: str, ids: list[str]) -> int:
    """The graph edges of the acts in the pack, carried alongside them.

    An increment without them would leave the copy's register reasoning about new law with an old
    graph — every new amending act invisible, and therefore every repair it made unrecorded.
    """
    from scripts.graf import _deschide_graf

    cx = sqlite3.connect(tinta)
    try:
        cx.executescript(
            "CREATE TABLE IF NOT EXISTS muchii ("
            " din_act TEXT NOT NULL, catre_act TEXT, locator TEXT, fel TEXT NOT NULL,"
            " incredere TEXT, de_la TEXT, text TEXT);"
        )
        gx = _deschide_graf(graf_db, readonly=True)
        try:
            coloane = [r[1] for r in gx.execute("PRAGMA table_info(muchii)")]
            nume = ", ".join(coloane)
            semne = ",".join("?" * len(ids))
            randuri = gx.execute(
                f"SELECT {nume} FROM muchii WHERE din_act IN ({semne})", ids
            ).fetchall()
        finally:
            gx.close()
        if not randuri:
            return 0
        cx.execute("DROP TABLE IF EXISTS muchii")
        cx.execute(f"CREATE TABLE muchii ({', '.join(c + ' TEXT' for c in coloane)})")
        cx.executemany(
            f"INSERT INTO muchii ({nume}) VALUES ({','.join('?' * len(coloane))})",
            [tuple(r) for r in randuri],
        )
        cx.commit()
        return len(randuri)
    finally:
        cx.close()


def aplica(copie_db: str, pachet_db: str, *, graf_db: str | None = None, log=print) -> Pachet:
    """Bring a copy up to the pack's position. Replaces act by act; never deletes.

    Safe to apply twice: an act is removed before it is written, so a repeated pack lands on the
    same rows. Safe to apply out of order too — a pack older than the copy simply rewrites acts
    with the same content — though nothing is gained by it.
    """
    t0 = time.monotonic()
    inainte = versiune(copie_db)

    with depozit.deschide(copie_db) as con:
        con.execute("ATTACH DATABASE ? AS pachet", (pachet_db,))
        ids = [r[0] for r in con.execute("SELECT id FROM pachet.acte ORDER BY id")]
        log(f"{len(ids)} acte de aplicat peste o copie de la {inainte or '(gol)'}")

        provizii = lovituri = 0
        for start in range(0, len(ids), 500):
            felie = ids[start : start + 500]
            semne = ",".join("?" * len(felie))
            for act_id in felie:
                # Before the cascade: `content='provizii'` keeps no copy of its own, so the index
                # has to hand back the original values while the rows are still there.
                depozit._sterge_fts(con, act_id)
            con.execute(f"DELETE FROM relatii WHERE din_act IN ({semne})", felie)
            con.execute(f"DELETE FROM lovituri WHERE cheie_act IN ({semne})", felie)
            con.execute(f"DELETE FROM acte WHERE id IN ({semne})", felie)

            con.execute(f"INSERT INTO acte SELECT * FROM pachet.acte WHERE id IN ({semne})", felie)
            for tabel in TABELE_ACT:
                cur = con.execute(
                    f"INSERT INTO {tabel} SELECT * FROM pachet.{tabel} WHERE act_id IN ({semne})",
                    felie,
                )
                if tabel == "provizii":
                    provizii += cur.rowcount
            con.execute(
                f"INSERT INTO relatii SELECT * FROM pachet.relatii WHERE din_act IN ({semne})",
                felie,
            )
            cur = con.execute(
                f"INSERT INTO lovituri SELECT * FROM pachet.lovituri WHERE cheie_act IN ({semne})",
                felie,
            )
            lovituri += cur.rowcount
            con.commit()

        # The pack's own end, not this copy's rows: local work must not move the position, or the
        # next pack skips whatever the source wrote while the reader was busy.
        pana_la = con.execute("SELECT coalesce(max(citit_la), '') FROM pachet.acte").fetchone()[0]
        con.execute("DETACH DATABASE pachet")
        if pana_la and pana_la > inainte:
            con.execute(
                "INSERT OR REPLACE INTO versiune (cheie, valoare) VALUES ('adus_la', ?)",
                (pana_la,),
            )
        con.execute("INSERT INTO provizii_fts(provizii_fts) VALUES('rebuild')")
        con.commit()

    muchii = _aplica_muchii(graf_db, pachet_db, ids) if graf_db and ids else 0
    dupa = versiune(copie_db)
    p = Pachet(inainte, dupa, len(ids), provizii, muchii, lovituri, 0, time.monotonic() - t0)
    log(f"aplicat: {p}")
    return p


def _aplica_muchii(graf_db: str, pachet_db: str, ids: list[str]) -> int:
    """Replace the changed acts' edges in the local graph, if the pack carries any."""
    from scripts.graf import _deschide_graf

    px = sqlite3.connect(f"file:{pachet_db}?mode=ro", uri=True)
    try:
        are = px.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='muchii'"
        ).fetchone()
        if not are:
            return 0
        coloane = [r[1] for r in px.execute("PRAGMA table_info(muchii)")]
        randuri = px.execute(f"SELECT {', '.join(coloane)} FROM muchii").fetchall()
    finally:
        px.close()
    if not randuri:
        return 0

    gx = _deschide_graf(graf_db)
    try:
        for start in range(0, len(ids), 500):
            felie = ids[start : start + 500]
            semne = ",".join("?" * len(felie))
            gx.execute(f"DELETE FROM muchii WHERE din_act IN ({semne})", felie)
        gx.executemany(
            f"INSERT INTO muchii ({', '.join(coloane)}) VALUES ({','.join('?' * len(coloane))})",
            [tuple(r) for r in randuri],
        )
        gx.commit()
        return len(randuri)
    finally:
        gx.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="comanda", required=True)

    v = sub.add_parser("versiune", help="unde se află o copie")
    v.add_argument("--db", default="corpus.db")

    c = sub.add_parser("construieste", help="taie incrementul de la o poziție încoace")
    c.add_argument("--db", default="corpus.db")
    c.add_argument("--graf", default="graf.db")
    c.add_argument("--tinta", default="delta.db")
    c.add_argument("--de-la", required=True, help="poziția copiei: `delta versiune --db copie.db`")

    a = sub.add_parser("aplica", help="adu o copie la zi cu un pachet")
    a.add_argument("--db", required=True, help="copia de actualizat")
    a.add_argument("--pachet", required=True)
    a.add_argument("--graf", default=None)

    args = ap.parse_args()
    if args.comanda == "versiune":
        print(versiune(args.db) or "(gol)")
    elif args.comanda == "construieste":
        construieste(args.db, args.tinta, args.de_la, graf_db=args.graf)
    else:
        aplica(args.db, args.pachet, graf_db=args.graf)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
