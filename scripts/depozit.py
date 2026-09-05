"""Where the corpus lives once it has been read.

SQLite, and not as a compromise. `sqlite3` is in the standard library, so the corpus store costs
this package exactly nothing in dependencies — the property the extractors were built around and
the reason a legislative linter can be handed to a research team as a checkout rather than as an
installation. It holds a hundred thousand acts without complaint, it is one file to copy or
delete, and FTS5 gives full-text search over legal Romanian without a search server.

The alternative that was actually considered is a graph database, because the object here is a
graph. It loses on the same argument the rest of this package runs on: Neo4j is a container, a
driver, a query language and an afternoon, in exchange for edge traversal over a corpus where
the deepest question anyone asks is "what points at this act, and what does this act point at" —
two indexed selects. If the traversals ever get deeper than that, the export is a `SELECT` away.

**One act, one row, keyed by what the law calls itself.** `lege-98-2016`, from the designation
line. Not the portal's URL id and not its `id_act`: requesting document 178667 returns a page
whose own `id_act` is 290673, so both numbers identify a *route to a rendering*, not the act.
Both are stored anyway, because a scraper that cannot say where a row came from cannot be
audited, and because refetching needs the URL id.

**The fetch cache is a table, not a directory.** Every page ever retrieved is kept with the time
it was retrieved and its length, so a re-run costs nothing and a parser change can be replayed
over the whole corpus without touching the portal again. That is the single most important
property of the collector: `legislatie.just.ro` is a ministry's server, this package is built
for a political party, and the number of times it asks for the same document should be one.

**Provisions are stored at every level, with their marked references.** `art7`, `art7.alin2`,
`art7.alin2.lita` are three rows, because a finding may need to quote any of them, and the
`S_LGI` spans the portal itself marks travel alongside — they are the only reference ground
truth this package has that nobody on this project wrote by hand.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from scripts.api import Inregistrare
from scripts.parsare import ActParsat
from scripts.referinte import Act

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS acte (
    id              TEXT PRIMARY KEY,   -- 'lege-98-2016': what the law calls itself
    tip             TEXT NOT NULL,
    numar           TEXT,
    an              INTEGER,
    titlu           TEXT NOT NULL,
    emitent         TEXT,
    publicat        TEXT,               -- ISO date
    vigoare         TEXT,
    republicat_din  TEXT,
    id_portal       TEXT,               -- the URL id: how to fetch it again
    id_act_portal   TEXT,               -- the page's own id_act; differs from the above
    sursa_url       TEXT,
    citit_la        TEXT NOT NULL
);

-- `ord` is in the key because a locator is not unique. An article whose body sits in an
-- unnumbered block yields a row at `art7` and so does the block inside it, and the first
-- version keyed on (act_id, locator) alone: Legea 98/2016 went in with 1 435 provisions and
-- came out with 1 404. Thirty-one rows replaced by their namesakes, silently, which is the
-- one thing this package is not allowed to do to a corpus.
CREATE TABLE IF NOT EXISTS provizii (
    act_id      TEXT NOT NULL REFERENCES acte(id) ON DELETE CASCADE,
    locator     TEXT NOT NULL,          -- 'art7.alin2.lita'
    ord         INTEGER NOT NULL,       -- position in the document, and the tiebreak
    text        TEXT NOT NULL,
    vigoare_de_la  TEXT,
    vigoare_pana_la TEXT,
    PRIMARY KEY (act_id, ord)
);
CREATE INDEX IF NOT EXISTS idx_provizii_locator ON provizii(act_id, locator);

-- The reference spans the portal marks itself, kept apart from anything this package infers.
CREATE TABLE IF NOT EXISTS referinte_marcate (
    act_id   TEXT NOT NULL REFERENCES acte(id) ON DELETE CASCADE,
    ord      INTEGER NOT NULL,
    locator  TEXT NOT NULL,
    text     TEXT NOT NULL
);

-- Edges. `fel` is the portal's own vocabulary where it came from the portal, and this
-- package's where it was extracted, and `sursa` says which — they are not equally trustworthy.
CREATE TABLE IF NOT EXISTS relatii (
    din_act   TEXT NOT NULL,
    catre_act TEXT,
    locator   TEXT,
    fel       TEXT NOT NULL,
    sursa     TEXT NOT NULL CHECK (sursa IN ('portal', 'extras')),
    incredere TEXT NOT NULL CHECK (incredere IN ('verbatim', 'derived', 'assumed')),
    de_la     TEXT,
    PRIMARY KEY (din_act, catre_act, locator, fel, sursa)
);

-- Fetch once, ever.
CREATE TABLE IF NOT EXISTS cache (
    url       TEXT PRIMARY KEY,
    corp      BLOB NOT NULL,
    octeti    INTEGER NOT NULL,
    stare     INTEGER NOT NULL,
    adus_la   TEXT NOT NULL
);

-- Collection progress, so an interrupted run resumes instead of restarting. One row per page
-- of the API's unfiltered enumeration, marked done once its acts are written. A 90-minute job
-- that cannot resume is a job that never finishes, because something always interrupts it.
CREATE TABLE IF NOT EXISTS progres (
    pagina     INTEGER PRIMARY KEY,
    acte       INTEGER NOT NULL,
    terminat_la TEXT NOT NULL
);

-- Pending legislative initiatives, from cdep.ro. A different corpus from `acte`: these are
-- bills in motion, not law in force, and the question they answer is duplication — does a new
-- draft repeat one already moving through Parliament. Keyed by the Chamber of Deputies id
-- (plx), which the Fișa links to the Senate id, because one initiative has a number in each
-- chamber and the two are the same bill seen from two rooms.
CREATE TABLE IF NOT EXISTS initiative (
    plx_id       TEXT PRIMARY KEY,      -- 'plx-33-2025'
    cam          INTEGER NOT NULL,
    idp          TEXT NOT NULL,         -- the portal handle, to refetch the Fișa
    senat_id     TEXT,                  -- 'L576/2024', the same bill in the other chamber
    tip          TEXT,                  -- 'propunere legislativa' | 'proiect de lege'
    titlu        TEXT NOT NULL,
    obiect       TEXT,                  -- what the bill sets out to do; the dedup text
    urgenta      INTEGER NOT NULL DEFAULT 0,
    stadiu       TEXT,                  -- 'raport depus...' — whether it is still alive
    camera_decizionala TEXT,
    data_inreg   TEXT,
    sursa_url    TEXT,
    citit_la     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_initiative_senat ON initiative(senat_id);

-- Which acts each initiative sets out to change, extracted from its title and obiect. Precomputed
-- so "which pending bills touch Legea X" is a lookup, not a scan of every initiative's text on
-- each query — the question a drafter amending X most wants answered.
CREATE TABLE IF NOT EXISTS initiative_tinta (
    plx_id   TEXT NOT NULL,
    act_id   TEXT NOT NULL,
    locator  TEXT,
    PRIMARY KEY (plx_id, act_id, locator)
);
CREATE INDEX IF NOT EXISTS idx_initiative_tinta_act ON initiative_tinta(act_id);

CREATE VIRTUAL TABLE IF NOT EXISTS initiative_fts USING fts5(
    titlu, obiect, plx_id UNINDEXED, tokenize = 'unicode61 remove_diacritics 2'
);

CREATE INDEX IF NOT EXISTS idx_relatii_catre ON relatii(catre_act);
CREATE INDEX IF NOT EXISTS idx_acte_tip_an   ON acte(tip, an);

CREATE VIRTUAL TABLE IF NOT EXISTS provizii_fts USING fts5(
    text, act_id UNINDEXED, locator UNINDEXED, tokenize = 'unicode61 remove_diacritics 2'
);
"""


@dataclass(frozen=True)
class Randament:
    """What one act contributed, so an import can report itself rather than be trusted."""

    act_id: str
    provizii: int
    referinte_marcate: int
    relatii_portal: int


def _iso(v: date | None) -> str | None:
    return v.isoformat() if v else None


@contextmanager
def deschide(
    cale: Path | str = "corpus.db", *, readonly: bool = False
) -> Iterator[sqlite3.Connection]:
    """Open the corpus. Writers create the schema and commit; readers do neither.

    `readonly=True` opens the file `mode=ro` and skips `executescript(SCHEMA)`. That matters
    during collection: the schema statements are DDL — writes — so a plain open contends for the
    writer lock even to read, and a reader that lands mid-batch dies with "database is locked"
    while the collector holds it. A read-only connection under WAL reads the last committed state
    concurrently with the writer and never wants that lock at all. The backend and the product
    read this way; only the collector and importers open for write.
    """
    if readonly:
        con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        try:
            yield con
        finally:
            con.close()
        return

    con = sqlite3.connect(str(cale), timeout=30.0)
    con.row_factory = sqlite3.Row
    # A reader and the collector's writer share the file under WAL; the busy timeout makes a
    # write that lands mid-commit wait the moment out instead of failing.
    con.execute("PRAGMA busy_timeout = 30000")
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def scrie_act(con: sqlite3.Connection, parsat: ActParsat) -> Randament:
    """Upsert one act and everything it carries. Re-importing the same act replaces it.

    Replaces rather than merges on purpose: a second read of the same document is a newer read,
    and half of an old parse mixed with half of a new one is a corpus nobody can reason about.
    """
    act = parsat.act
    con.execute("DELETE FROM acte WHERE id = ?", (act.id,))
    con.execute(
        "INSERT INTO acte (id, tip, numar, an, titlu, emitent, publicat, vigoare,"
        " republicat_din, id_portal, id_act_portal, sursa_url, citit_la)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            act.id,
            act.tip,
            act.numar,
            act.an,
            parsat.titlu,
            parsat.emitent,
            _iso(parsat.publicat),
            _iso(parsat.vigoare),
            _iso(parsat.republicat_din),
            parsat.id_portal,
            parsat.id_act_portal,
            parsat.sursa_url,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    con.execute("DELETE FROM provizii_fts WHERE act_id = ?", (act.id,))

    marcate = 0
    for ord_, p in enumerate(parsat.provizii, start=1):
        con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text, vigoare_de_la,"
            " vigoare_pana_la) VALUES (?,?,?,?,?,?)",
            (
                act.id,
                p.locator_id,
                ord_,
                p.text,
                _iso(p.in_vigoare_de_la),
                _iso(p.in_vigoare_pana_la),
            ),
        )
        con.execute(
            "INSERT INTO provizii_fts (text, act_id, locator) VALUES (?,?,?)",
            (p.text, act.id, p.locator_id),
        )
        for ref in p.referinte_marcate:
            con.execute(
                "INSERT INTO referinte_marcate (act_id, ord, locator, text) VALUES (?,?,?,?)",
                (act.id, ord_, p.locator_id, ref),
            )
            marcate += 1

    # The importer checks itself rather than being trusted: what the parser handed over and
    # what the table now holds must be the same number. This is the guard that would have
    # caught the thirty-one lost rows on the day they were lost.
    stocate = con.execute("SELECT count(*) FROM provizii WHERE act_id = ?", (act.id,)).fetchone()[0]
    if stocate != len(parsat.provizii):
        raise ValueError(
            f"{act.id}: parserul a dat {len(parsat.provizii)} provizii, în tabel au ajuns {stocate}"
        )

    # The portal's flags say a relation *exists*, not what it points at. Recorded as `assumed`
    # until the relation panels are fetched, because "this act amends something" is not a fact
    # anyone can act on and must not look like one.
    for fel in sorted(parsat.relatii):
        con.execute(
            "INSERT OR REPLACE INTO relatii (din_act, catre_act, locator, fel, sursa,"
            " incredere, de_la) VALUES (?,?,?,?,?,?,?)",
            (act.id, "", "", fel, "portal", "assumed", None),
        )
    return Randament(act.id, len(parsat.provizii), marcate, len(parsat.relatii))


def pune_in_cache(con: sqlite3.Connection, url: str, corp: bytes, stare: int) -> None:
    con.execute(
        "INSERT OR REPLACE INTO cache (url, corp, octeti, stare, adus_la) VALUES (?,?,?,?,?)",
        (url, corp, len(corp), stare, datetime.now(UTC).isoformat(timespec="seconds")),
    )


def din_cache(con: sqlite3.Connection, url: str) -> bytes | None:
    r = con.execute("SELECT corp FROM cache WHERE url = ? AND stare = 200", (url,)).fetchone()
    return r["corp"] if r else None


def cauta(con: sqlite3.Connection, intrebare: str, limita: int = 20) -> list[sqlite3.Row]:
    """Full-text search over every provision, diacritic-insensitive.

    `remove_diacritics 2` is what makes `hotarare` find `hotărâre`, which matters because half
    the corpus was typed before the comma-below letters were reliably available.
    """
    # Joined to `acte` for the source URL and title, so a result links straight to the act on the
    # portal rather than to a search-by-number that returns a list — the difference between "here
    # it is" and "go find it".
    return con.execute(
        "SELECT f.act_id, f.locator, snippet(provizii_fts, 0, '[', ']', '…', 12) AS fragment,"
        " a.titlu, a.sursa_url"
        " FROM provizii_fts f LEFT JOIN acte a ON a.id = f.act_id"
        " WHERE provizii_fts MATCH ? ORDER BY rank LIMIT ?",
        (intrebare, limita),
    ).fetchall()


def acte(con: sqlite3.Connection) -> list[Act]:
    return [
        Act(r["tip"], r["numar"], r["an"])
        for r in con.execute("SELECT tip, numar, an FROM acte ORDER BY an, numar")
    ]


def rezumat(con: sqlite3.Connection) -> dict[str, int]:
    """What the corpus actually holds, for a report that states its own coverage."""

    def n(q: str) -> int:
        # Tolerant of a table a reader opened before a writer added it: a read-only connection to
        # a mid-upgrade corpus counts what exists and reports zero for what does not, rather than
        # crashing. A write-open runs the schema first, so for writers nothing is ever missing.
        try:
            return con.execute(q).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    return {
        "acte": n("SELECT count(*) FROM acte"),
        "provizii": n("SELECT count(*) FROM provizii"),
        "referinte_marcate": n("SELECT count(*) FROM referinte_marcate"),
        "relatii": n("SELECT count(*) FROM relatii"),
        "pagini_in_cache": n("SELECT count(*) FROM cache"),
        "initiative": n("SELECT count(*) FROM initiative"),
    }


def scrie_initiativa(con: sqlite3.Connection, ini) -> None:
    """Upsert one initiative and its search row. Re-collecting replaces it — a later read of a
    Fișa is a newer stage, and a bill's stage is the field most likely to have moved."""
    con.execute("DELETE FROM initiative WHERE plx_id = ?", (ini.plx_id,))
    con.execute("DELETE FROM initiative_fts WHERE plx_id = ?", (ini.plx_id,))
    con.execute(
        "INSERT INTO initiative (plx_id, cam, idp, senat_id, tip, titlu, obiect, urgenta,"
        " stadiu, camera_decizionala, data_inreg, sursa_url, citit_la)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ini.plx_id,
            ini.cam,
            ini.idp,
            ini.senat_id,
            ini.tip,
            ini.titlu,
            ini.obiect,
            int(ini.urgenta),
            ini.stadiu,
            ini.camera_decizionala,
            ini.data_inreg,
            ini.sursa_url,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    con.execute(
        "INSERT INTO initiative_fts (titlu, obiect, plx_id) VALUES (?,?,?)",
        (ini.titlu, ini.obiect or "", ini.plx_id),
    )


def initiative_vazute(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT idp FROM initiative")}


def scrie_inregistrare(con: sqlite3.Connection, rec: Inregistrare, act: Act) -> None:
    """Write one act from an API record: metadata, in-force date, and the flat full text.

    The API's text has no article tree, so it is stored as a single searchable provision keyed
    `text`. An act that later needs article-level locators is re-read from its HTML by
    `scrie_act`, which replaces this row wholesale — the two paths never half-merge. Relation
    flags are not written here because the API does not carry them; they come from the HTML.
    """
    con.execute("DELETE FROM acte WHERE id = ?", (act.id,))
    con.execute(
        "INSERT INTO acte (id, tip, numar, an, titlu, emitent, publicat, vigoare,"
        " republicat_din, id_portal, id_act_portal, sursa_url, citit_la)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            act.id,
            act.tip,
            act.numar,
            act.an,
            rec.titlu,
            rec.emitent,
            _iso(rec.data_vigoare),
            _iso(rec.data_vigoare),
            None,
            rec.id_portal,
            "",
            rec.link_html,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    con.execute("DELETE FROM provizii_fts WHERE act_id = ?", (act.id,))
    con.execute(
        "INSERT INTO provizii (act_id, locator, ord, text, vigoare_de_la, vigoare_pana_la)"
        " VALUES (?,?,?,?,?,?)",
        (act.id, "text", 1, rec.text, _iso(rec.data_vigoare), None),
    )
    con.execute(
        "INSERT INTO provizii_fts (text, act_id, locator) VALUES (?,?,?)",
        (rec.text, act.id, "text"),
    )


def pagina_terminata(con: sqlite3.Connection, pagina: int, acte: int) -> None:
    con.execute(
        "INSERT OR REPLACE INTO progres (pagina, acte, terminat_la) VALUES (?,?,?)",
        (pagina, acte, datetime.now(UTC).isoformat(timespec="seconds")),
    )


def pagini_terminate(con: sqlite3.Connection) -> set[int]:
    return {r[0] for r in con.execute("SELECT pagina FROM progres")}


def importa(cale_db: Path | str, parsate: Iterable[ActParsat]) -> list[Randament]:
    with deschide(cale_db) as con:
        return [scrie_act(con, p) for p in parsate]
