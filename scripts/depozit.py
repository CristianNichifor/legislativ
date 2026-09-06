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
from scripts.publicare import publicare
from scripts.referinte import Act
from scripts.text import fara_separatoare

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

-- Every document the service handed over, keyed by its own portal id rather than by what it
-- calls itself. `acte.id` is a *citation* key — `lege-98-2016` is what a drafter writes and what
-- `referinte.py` resolves — and a citation key is not unique over the real corpus: ministries
-- number their ordine from 1 each year, and `decizie-5-1996` is as good a name for a Curtea
-- Constituțională decision as for an agency's. Writing both into `acte` means the second erases
-- the first, which is exactly the failure the `provizii` note below describes, one level up and
-- three orders of magnitude worse: measured over the first 2 000 pages, 19 975 records written
-- and 15 014 surviving — 4 961 documents, a quarter of the collection, deleted by a namesake.
--
-- So the two identities are separated. `documente` keeps every record, permanently; `acte`
-- stays the citation view it always was, last writer winning, because that is what resolution
-- needs and what the graph is built on. Nothing is lost, and a reader that wants all the
-- decisions of one issuer asks `documente` instead of guessing from a collided id.
CREATE TABLE IF NOT EXISTS documente (
    id_portal   TEXT PRIMARY KEY,       -- the document's own identity, unique on the portal
    cheie_act   TEXT NOT NULL,          -- the citation key it would claim: 'lege-98-2016'
    tip         TEXT NOT NULL,
    numar       TEXT,
    an          INTEGER,
    titlu       TEXT NOT NULL,
    emitent     TEXT,
    vigoare     TEXT,
    publicat    TEXT,               -- ISO date, read from the act's own Monitorul Oficial line
    monitor     INTEGER,            -- the MO issue number, so a finding can be checked
    republicare INTEGER,            -- 1 when that line is a republication, not first publication
    sursa_url   TEXT,
    text        TEXT NOT NULL,
    adus_la     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documente_cheie ON documente(cheie_act);
CREATE INDEX IF NOT EXISTS idx_documente_emitent ON documente(emitent, tip);

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

-- What a Curtea Constituțională decision put out of force, extracted once and kept.
--
-- Reading it is not cheap: the register spent 177 of its 178 seconds re-parsing all 20 006
-- decisions to find the ~530 that strike anything, on every single run. The text does not change
-- once collected, so the answer does not either — and a tool an MP waits three minutes for is a
-- tool nobody opens twice.
--
-- Keyed by the document's own portal id rather than by the citation key, for the same reason
-- `documente` is: `decizie-5-1996` names a Court decision no better than an agency's, and a
-- collision there would attribute a strike to the wrong issuer. `ord` keeps two strikes by one
-- decision apart, exactly as it does in `provizii`.
CREATE TABLE IF NOT EXISTS lovituri (
    id_portal   TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    cheie_act   TEXT NOT NULL,      -- the deciding act, as a citation key
    publicat    TEXT,               -- when the decision was published; the art. 147 clock
    definitiva  INTEGER,            -- 1 final, 0 open to recourse, NULL unstated
    act         TEXT,               -- the struck act, NULL when it could not be keyed
    locator     TEXT NOT NULL,
    fel         TEXT NOT NULL,      -- neconstitutional | abrogat_constitutional
    text        TEXT NOT NULL,      -- the span it was read from, so a finding can quote it
    PRIMARY KEY (id_portal, ord)
);
CREATE INDEX IF NOT EXISTS idx_lovituri_act ON lovituri(act);

-- The document as the portal serves it, kept so it is fetched once and never again.
--
-- The SOAP service returns an act's text already flattened: no article headings a parser can
-- trust, and paragraph breaks gone, so `provizii` holds one row per document (`locator = 'text'`)
-- and nothing is addressable below the act. The HTML detail page carries the structure the
-- package is built on — `S_ART` / `S_ALN` / `S_LIT` — and `parsare.py` has always known how to
-- read it. What was missing was somewhere to put it.
--
-- Stored gzipped because that is how it arrives and how it stays: 1 023 KB of markup for the
-- Penal Code becomes 142 KB, and the corpus is already 9 GB. It is therefore fetched for the acts
-- that need addressing, not for all 152 079.
--
-- `incercat_la` is the load-bearing column, and the same discipline as `publicare_incercata` and
-- `lovituri_extrase`: it records that a document was *asked for*, whatever came back. Resuming on
-- "has no html" would re-ask the service for every act it has already refused, every run —
-- politely hammering somebody else's server for an answer that will not change.
CREATE TABLE IF NOT EXISTS surse (
    id_portal   TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    html        BLOB,               -- gzipped; NULL when the fetch failed
    octeti      INTEGER,            -- uncompressed size, so a report needs no decompression
    stare       TEXT NOT NULL,      -- ok | http-<cod> | retea | gol
    incercat_la TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_surse_stare ON surse(stare);

-- What this copy was last brought up to, written by `delta.aplica`. One row, `adus_la`.
--
-- Recorded rather than derived, and the difference is not cosmetic. `max(acte.citit_la)` looks
-- like a free answer until you notice a copy is not read-only: `surse.imbogateste` rewrites acts
-- locally and marks them now, which pushes a derived position past everything the source wrote in
-- between — and the next pack skips exactly that range, permanently, with no symptom.
CREATE TABLE IF NOT EXISTS versiune (
    cheie   TEXT PRIMARY KEY,
    valoare TEXT NOT NULL
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

-- The authority's own list of implementing norms that were mandated and never issued
-- (Consiliul Legislativ / SGG: *Situația normelor neîndeplinite*). This is ground truth for the
-- gap report: `vid.py` derives the same claim from the corpus, and comparing the two turns a
-- derived finding into one measured against the source. Imported from a file the user supplies —
-- the tool stays offline — one row per outstanding norm, keyed by host act + instrument + which
-- list it came from, so re-importing a newer list replaces its own rows and not another's.
CREATE TABLE IF NOT EXISTS neindeplinite (
    act_id       TEXT NOT NULL,          -- host act the norm implements, 'lege-196-2016'
    act_citat    TEXT NOT NULL,          -- the act exactly as the list cites it
    instrument   TEXT NOT NULL,          -- the norm to be issued, as named
    tip_asteptat TEXT,                   -- mapped instrument type (hg/ordin/...) or NULL
    scadenta     TEXT,                   -- ISO deadline, when the list gives one
    stadiu       TEXT,                   -- the authority's status text
    sursa        TEXT NOT NULL,          -- which list this row came from
    citit_la     TEXT NOT NULL,
    PRIMARY KEY (act_id, instrument, sursa)
);
CREATE INDEX IF NOT EXISTS idx_neindeplinite_act ON neindeplinite(act_id);

CREATE INDEX IF NOT EXISTS idx_relatii_catre ON relatii(catre_act);
CREATE INDEX IF NOT EXISTS idx_acte_tip_an   ON acte(tip, an);

-- `content='provizii'` makes this an index and nothing else. Left to itself fts5 keeps a
-- verbatim copy of everything it indexes: measured on the finished corpus, `provizii` held
-- 1 952.7 MB of text and `provizii_fts_content` another 1 950.8 MB of the same text — a quarter
-- of an 8.4 GB file, and the difference between a corpus that can be handed to a research team
-- and one that cannot.
--
-- The cost is that the index is no longer maintained for us. Rows must be handed to fts5 as they
-- are written, and — the part that bites — *before* they are deleted, because a cascade delete on
-- `acte` removes `provizii` rows without fts5 ever hearing about it. `_sterge_fts` does that, and
-- `test_replacing_an_act_leaves_no_stale_rows_in_an_external_index` is what stops it rotting.
CREATE VIRTUAL TABLE IF NOT EXISTS provizii_fts USING fts5(
    text, act_id UNINDEXED, locator UNINDEXED,
    content = 'provizii', content_rowid = 'rowid',
    tokenize = 'unicode61 remove_diacritics 2'
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


# The portal renders every document at /Public/DetaliiDocument/<id>. The stored `sursa_url` is the
# canonical link where we have one; where we only kept the portal's own document id (the common case
# for acts parsed from a saved page), that id reconstructs the same URL.
PORTAL_DOCUMENT = "https://legislatie.just.ro/Public/DetaliiDocument/"


def url_document(sursa_url: str | None, id_act_portal: str | None) -> str:
    """The public portal URL for an act: its stored source, or one built from its portal id."""
    if sursa_url:
        return sursa_url
    if id_act_portal:
        return f"{PORTAL_DOCUMENT}{id_act_portal}"
    return ""


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
        _adauga_coloane(con)
        _migreaza_fts(con)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _adauga_coloane(con: sqlite3.Connection) -> None:
    """Add columns a corpus collected under an older schema does not have.

    `CREATE TABLE IF NOT EXISTS` is a no-op on a table that already exists, columns and all, so a
    new field never reaches a corpus that took hours to collect. Each one is added on its own,
    guarded by what `table_info` actually reports, so this stays safe to run on every open and on
    a file at any schema age.
    """
    noi = {
        "documente": [
            ("publicat", "TEXT"),
            ("monitor", "INTEGER"),
            ("republicare", "INTEGER"),
            # Whether the Monitorul Oficial line has been looked for, as opposed to found.
            # `publicat IS NULL` conflates "not yet examined" with "examined, has no line" —
            # true of 22% of documents — so a resumable pass re-reads them for ever. One bit
            # ends that: a daily refresh then costs only the documents that arrived that day.
            ("publicare_incercata", "INTEGER"),
            # Whether this document has been read for strikes, as opposed to having any. 97% of
            # decisions strike nothing, so "has no rows in `lovituri`" is the normal case and
            # cannot mean "not yet examined" without re-reading the whole corpus every time.
            ("lovituri_extrase", "INTEGER"),
        ],
    }
    for tabel, coloane in noi.items():
        existente = {r[1] for r in con.execute(f"PRAGMA table_info({tabel})")}
        for nume, tip in coloane:
            if nume not in existente:
                con.execute(f"ALTER TABLE {tabel} ADD COLUMN {nume} {tip}")


def _migreaza_fts(con: sqlite3.Connection) -> None:
    """Move a corpus off the content-owning index it may have been collected under.

    `CREATE VIRTUAL TABLE IF NOT EXISTS` is a no-op on a table that already exists, so a corpus
    that took hours to collect would keep its old index and its duplicate copy of every provision
    for ever. The text is already in `provizii`, so the index can simply be rebuilt from it —
    nothing is re-fetched and nothing is at risk beyond the time it takes.
    """
    tabele = {
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }
    if "provizii_fts_content" not in tabele and "provizii_fts_rand" not in tabele:
        return
    con.execute("DROP TABLE IF EXISTS provizii_fts_rand")
    con.execute("DROP TABLE IF EXISTS provizii_fts")
    con.executescript(
        "CREATE VIRTUAL TABLE provizii_fts USING fts5("
        " text, act_id UNINDEXED, locator UNINDEXED,"
        " content = 'provizii', content_rowid = 'rowid',"
        " tokenize = 'unicode61 remove_diacritics 2');"
    )
    con.execute("INSERT INTO provizii_fts(provizii_fts) VALUES('rebuild')")


def _sterge_fts(con: sqlite3.Connection, act_id: str) -> None:
    """Withdraw an act's rows from the index before they leave the table underneath it.

    With `content='provizii'` fts5 owns no copy, so a delete must hand back the *original* column
    values against the original rowid — and it must happen before the rows go, because a cascade
    delete on `acte` takes `provizii` with it silently. An index left holding withdrawn rows makes
    an act match a search for text it no longer contains, which is the quiet kind of wrong.
    """
    randuri = con.execute(
        "SELECT rowid, text, act_id, locator FROM provizii WHERE act_id = ?", (act_id,)
    ).fetchall()
    for r in randuri:
        con.execute(
            "INSERT INTO provizii_fts(provizii_fts, rowid, text, act_id, locator)"
            " VALUES('delete', ?, ?, ?, ?)",
            (r[0], r[1], r[2], r[3]),
        )


def _scrie_fts(con: sqlite3.Connection, rowid: int, act_id: str, locator: str, text: str) -> None:
    """Index one provision, under the rowid the content table gave it."""
    con.execute(
        "INSERT INTO provizii_fts(rowid, text, act_id, locator) VALUES (?,?,?,?)",
        (rowid, text, act_id, locator),
    )


def scrie_provizii(con: sqlite3.Connection, act_id: str, provizii) -> int:
    """Replace one act's provisions, leaving everything else about the act alone.

    `scrie_act` replaces the act wholesale, which is right when a document is (re)collected and
    wrong here: upgrading an act from one flattened `locator = 'text'` row to its real article
    tree must not also overwrite `acte.publicat`, which was reconciled once already against the
    document's own Monitorul Oficial line and is better than what a page parse guesses.

    Same withdrawal order as everywhere else — the index hands back the original values *before*
    the rows go, because `content='provizii'` keeps no copy of its own.
    """
    _sterge_fts(con, act_id)
    con.execute("DELETE FROM provizii WHERE act_id = ?", (act_id,))
    # `citit_la` is the only mark of when an act's stored content last changed, and it is what a
    # delta pack selects on. Upgrading an act's provisions from its HTML changes that content, so
    # leaving the mark alone would hide the change from every offline copy — the act would keep the
    # flattened text for ever, silently.
    con.execute(
        "UPDATE acte SET citit_la = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(timespec="seconds"), act_id),
    )
    scrise = 0
    for ord_, p in enumerate(provizii, start=1):
        cur = con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text, vigoare_de_la, vigoare_pana_la)"
            " VALUES (?,?,?,?,?,?)",
            (
                act_id,
                p.locator_id,
                ord_,
                p.text,
                _iso(p.in_vigoare_de_la),
                _iso(p.in_vigoare_pana_la),
            ),
        )
        _scrie_fts(con, cur.lastrowid, act_id, p.locator_id, p.text)
        scrise += 1
    return scrise


def scrie_act(con: sqlite3.Connection, parsat: ActParsat) -> Randament:
    """Upsert one act and everything it carries. Re-importing the same act replaces it.

    Replaces rather than merges on purpose: a second read of the same document is a newer read,
    and half of an old parse mixed with half of a new one is a corpus nobody can reason about.
    """
    act = parsat.act
    # Before the cascade, not after: `DELETE FROM acte` takes `provizii` with it, and an
    # external-content index cannot withdraw rows whose values are already gone.
    _sterge_fts(con, act.id)
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

    marcate = 0
    for ord_, p in enumerate(parsat.provizii, start=1):
        cur = con.execute(
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
        _scrie_fts(con, cur.lastrowid, act.id, p.locator_id, p.text)
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


def _filtre_cauta(
    tip: str | None, an_min: int | None, an_max: int | None
) -> tuple[str, list[object]]:
    """The optional `AND a.tip = … AND a.an BETWEEN …` clause and its parameters, shared by the
    search and its count so the two never drift."""
    clauze, params = "", []
    if tip:
        clauze += " AND a.tip = ?"
        params.append(tip)
    if an_min is not None:
        clauze += " AND a.an >= ?"
        params.append(an_min)
    if an_max is not None:
        clauze += " AND a.an <= ?"
        params.append(an_max)
    return clauze, params


def cauta(
    con: sqlite3.Connection,
    intrebare: str,
    limita: int = 20,
    *,
    offset: int = 0,
    tip: str | None = None,
    an_min: int | None = None,
    an_max: int | None = None,
) -> list[sqlite3.Row]:
    """Full-text search over every provision, diacritic-insensitive, one page at a time.

    `remove_diacritics 2` is what makes `hotarare` find `hotărâre`, which matters because half
    the corpus was typed before the comma-below letters were reliably available. Optional filters
    narrow by act type and year; `offset` pages through the ranked hits.
    """
    # Joined to `acte` for the source URL, title and the filterable fields, so a result links
    # straight to the act on the portal rather than to a search-by-number that returns a list.
    clauze, params = _filtre_cauta(tip, an_min, an_max)
    return con.execute(
        "SELECT f.act_id, f.locator, snippet(provizii_fts, 0, '[', ']', '…', 12) AS fragment,"
        " a.titlu, a.sursa_url, a.tip, a.an"
        " FROM provizii_fts f LEFT JOIN acte a ON a.id = f.act_id"
        f" WHERE provizii_fts MATCH ?{clauze} ORDER BY rank LIMIT ? OFFSET ?",
        (intrebare, *params, limita, offset),
    ).fetchall()


def cauta_numar(
    con: sqlite3.Connection,
    intrebare: str,
    *,
    tip: str | None = None,
    an_min: int | None = None,
    an_max: int | None = None,
) -> int:
    """How many provisions match the query and filters — the total behind a paged result."""
    clauze, params = _filtre_cauta(tip, an_min, an_max)
    return con.execute(
        "SELECT count(*) FROM provizii_fts f LEFT JOIN acte a ON a.id = f.act_id"
        f" WHERE provizii_fts MATCH ?{clauze}",
        (intrebare, *params),
    ).fetchone()[0]


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
        "documente": n("SELECT count(*) FROM documente"),
        # How many documents share a citation key with another. This is the number that spent a
        # collection run at zero because nobody counted it: `acte` looked healthy while a quarter
        # of what had been fetched was being deleted by namesakes. It belongs in every summary.
        "documente_cu_cheie_partajata": n(
            "SELECT coalesce(sum(n - 1), 0) FROM ("
            "  SELECT count(*) AS n FROM documente GROUP BY cheie_act HAVING n > 1)"
        ),
        "provizii": n("SELECT count(*) FROM provizii"),
        # How many acts are actually structured. The SOAP service returns flattened text, so an
        # unenriched act holds one row with `locator = 'text'` — and a corpus of those reports a
        # provision count equal to its act count, which reads as healthy and means the opposite.
        # Without this number the header says "152 079 prevederi" over 132 real article trees.
        "acte_structurate": n(
            "SELECT count(DISTINCT act_id) FROM provizii WHERE locator <> 'text'"
        ),
        "referinte_marcate": n("SELECT count(*) FROM referinte_marcate"),
        "relatii": n("SELECT count(*) FROM relatii"),
        "pagini_in_cache": n("SELECT count(*) FROM cache"),
        "initiative": n("SELECT count(*) FROM initiative"),
        "neindeplinite": n("SELECT count(*) FROM neindeplinite"),
    }


def scrie_norma(con: sqlite3.Connection, norma) -> None:
    """Upsert one outstanding-norm row from the authority's list. Re-importing the same list
    replaces its rows — a newer list is a newer status, and status is what moves."""
    con.execute(
        "INSERT OR REPLACE INTO neindeplinite"
        " (act_id, act_citat, instrument, tip_asteptat, scadenta, stadiu, sursa, citit_la)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            norma.act_id,
            norma.act_citat,
            norma.instrument,
            norma.tip_asteptat,
            norma.scadenta.isoformat() if norma.scadenta else None,
            norma.stadiu,
            norma.sursa,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )


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
    # The document first, under its own identity, so that a citation-key collision costs the
    # `acte` row and nothing else. Keyed on the portal id and replaced in place, so re-collecting
    # a page updates a document rather than duplicating it.
    # The publication date is read from the act's own Monitorul Oficial line, because the service
    # does not carry it: its `Publicatie` field is the literal string "Monitorul Oficial". Where
    # the line cannot be read the columns stay NULL — a missing publication date has to look
    # missing, which is precisely what went wrong when `publicat` was filled with `vigoare`.
    pub = publicare(rec.text)
    con.execute(
        "INSERT OR REPLACE INTO documente (id_portal, cheie_act, tip, numar, an, titlu,"
        " emitent, vigoare, publicat, monitor, republicare, sursa_url, text, adus_la)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rec.id_portal,
            act.id,
            act.tip,
            act.numar,
            act.an,
            rec.titlu,
            rec.emitent,
            _iso(rec.data_vigoare),
            _iso(pub.data) if pub else None,
            pub.monitor if pub else None,
            int(pub.republicare) if pub else None,
            rec.link_html,
            rec.text,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    # Before the cascade, not after: `DELETE FROM acte` takes `provizii` with it, and an
    # external-content index cannot withdraw rows whose values are already gone.
    _sterge_fts(con, act.id)
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
            # publicat: the real thing or nothing. It used to be a second copy of the in-force
            # date, identical in all 63 933 rows, which made every art. 147 / art. 78 deadline
            # anchor on the wrong event without anything saying so.
            _iso(pub.data) if pub else None,
            _iso(rec.data_vigoare),
            None,
            rec.id_portal,
            "",
            rec.link_html,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    # `documente.text` above keeps what the service returned, verbatim. This copy is the one a
    # reader is quoted and a model is shown, so the service's block markers come out of it.
    curatat = fara_separatoare(rec.text)
    cur = con.execute(
        "INSERT INTO provizii (act_id, locator, ord, text, vigoare_de_la, vigoare_pana_la)"
        " VALUES (?,?,?,?,?,?)",
        (act.id, "text", 1, curatat, _iso(rec.data_vigoare), None),
    )
    _scrie_fts(con, cur.lastrowid, act.id, "text", curatat)


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
