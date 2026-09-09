"""Fetch EU legal acts from Cellar, the Publications Office repository.

Cellar is useful to this project for one narrow reason first: CELEX is a stable identifier, and
Cellar can tell us which official language expressions and downloadable streams exist for it. This
module does only that first step. It resolves a CELEX work through the public SPARQL endpoint,
prefers the official Romanian expression (`RON`) when available, falls back to English (`ENG`), and
stores the selected text plus all discovered manifestations in a local SQLite database.

It does not decide whether a Romanian draft violates EU law. That later pass must cite exact
provisions and say what it could not check; this module is just the source-of-record reader it will
stand on.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

from scripts import instantanee_ue
from scripts.text import cheie, normalizeaza

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELEX_URI = "http://publications.europa.eu/resource/celex/{celex}"
USER_AGENT = (
    "legislativ-linter/0.1 (+https://github.com/CristianNichifor/legislativ; "
    "contact: cristian@cnwebify.com)"
)

LIMBI_IMPLICITE = ("RON", "ENG")
FORMATE_TEXT = ("xhtml", "html", "txt", "text", "xml", "fmx4")
PRIORITATE_FORMAT = {fmt: i for i, fmt in enumerate(FORMATE_TEXT)}
_DOC_NR = re.compile(r"/DOC_(\d+)(?:$|[?#])")
_ARTICOL = re.compile(r"^(?:Articolul|Article)\s+([0-9]+[A-Za-z]?)\.?$", re.I)
_CONSIDERENT = re.compile(r"^\((\d{1,3})\)$")
_ANEXA = re.compile(r"^(?:ANEXA|ANNEX)\s*([IVXLCDM]+|\d+)?\b", re.I)
_CUVINTE_GOLE = {
    "acest",
    "acesta",
    "aceste",
    "acestea",
    "acestor",
    "aceasta",
    "ale",
    "alin",
    "articolul",
    "asupra",
    "care",
    "catre",
    "ceea",
    "cele",
    "este",
    "fost",
    "intr",
    "lege",
    "normele",
    "pentru",
    "prezent",
    "prezenta",
    "prin",
    "privind",
    "regulament",
    "sunt",
    "this",
    "that",
    "shall",
    "with",
    "from",
    "into",
    "under",
    "article",
    "regulation",
}

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS eu_acte (
    celex          TEXT PRIMARY KEY,
    work_uri       TEXT NOT NULL,
    expression_uri TEXT NOT NULL,
    manifestation_uri TEXT NOT NULL,
    limba          TEXT NOT NULL,
    format         TEXT NOT NULL,
    titlu          TEXT,
    data_document  TEXT,
    tip_uri        TEXT,
    in_vigoare     INTEGER,
    item_url       TEXT NOT NULL,
    sursa_url      TEXT NOT NULL,
    text           TEXT NOT NULL,
    text_sha256    TEXT NOT NULL,
    citit_la       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eu_acte_limba ON eu_acte(limba);
CREATE INDEX IF NOT EXISTS idx_eu_acte_data ON eu_acte(data_document);

CREATE TABLE IF NOT EXISTS eu_manifestari (
    celex          TEXT NOT NULL,
    work_uri       TEXT NOT NULL,
    expression_uri TEXT NOT NULL,
    manifestation_uri TEXT NOT NULL,
    limba          TEXT NOT NULL,
    format         TEXT NOT NULL,
    titlu          TEXT,
    data_document  TEXT,
    tip_uri        TEXT,
    in_vigoare     INTEGER,
    item_url       TEXT NOT NULL,
    PRIMARY KEY (celex, limba, format, item_url)
);
CREATE INDEX IF NOT EXISTS idx_eu_manifestari_celex ON eu_manifestari(celex);
CREATE INDEX IF NOT EXISTS idx_eu_manifestari_limba ON eu_manifestari(limba);

CREATE TABLE IF NOT EXISTS eu_provizii (
    celex    TEXT NOT NULL,
    locator  TEXT NOT NULL,
    fel      TEXT NOT NULL,
    titlu    TEXT,
    text     TEXT NOT NULL,
    ord      INTEGER NOT NULL,
    limba    TEXT NOT NULL,
    PRIMARY KEY (celex, locator)
);
CREATE INDEX IF NOT EXISTS idx_eu_provizii_celex_ord ON eu_provizii(celex, ord);
CREATE INDEX IF NOT EXISTS idx_eu_provizii_fel ON eu_provizii(fel);

CREATE VIRTUAL TABLE IF NOT EXISTS eu_provizii_fts USING fts5(
    text, titlu, celex UNINDEXED, locator UNINDEXED, limba UNINDEXED,
    content = 'eu_provizii', content_rowid = 'rowid',
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


class CellarError(RuntimeError):
    """Cellar answered with a shape this importer cannot use."""


class CelexNegasit(CellarError):
    """No Cellar work was found for this CELEX id in the requested languages."""


class TextIndisponibil(CellarError):
    """Cellar exposes metadata, but no text stream this zero-dependency importer can read."""


@dataclass(frozen=True)
class ManifestareUE:
    celex: str
    work_uri: str
    expression_uri: str
    manifestation_uri: str
    limba: str
    format: str
    item_url: str
    titlu: str
    data_document: str | None
    tip_uri: str | None
    in_vigoare: bool | None


@dataclass(frozen=True)
class ProvizieUE:
    celex: str
    locator: str
    fel: str
    titlu: str
    text: str
    ord: int
    limba: str


@contextmanager
def deschide(cale: str = "eu.db", *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the EU source database. Readers never run DDL."""
    if readonly:
        con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        try:
            yield con
        finally:
            con.close()
        return

    con = sqlite3.connect(cale, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 30000")
    try:
        con.executescript(SCHEMA)
        con.executescript(instantanee_ue.SCHEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def normalizeaza_celex(valoare: str) -> str:
    """A CELEX id from a bare id, `CELEX:...`, or a Publications Office/EUR-Lex URL."""
    text = (valoare or "").strip().rstrip("/")
    m = re.search(r"(?:^|[/?&])uri=CELEX:([^&#]+)", text, re.I)
    if not m:
        m = re.search(r"(?:^|[:/])celex[:/]([^/?#&]+)", text, re.I)
    celex = (m.group(1) if m else text).strip().upper()
    if not re.fullmatch(r"[0-9A-Z()._-]{5,50}", celex):
        raise ValueError(f"CELEX invalid: {valoare!r}")
    return celex


def _limbi(limbi: Sequence[str] = LIMBI_IMPLICITE) -> tuple[str, ...]:
    out = tuple(dict.fromkeys(limba.strip().upper() for limba in limbi if limba.strip()))
    if not out or any(not re.fullmatch(r"[A-Z]{3}", limba) for limba in out):
        raise ValueError("limbile Cellar trebuie scrise ca ISO 639-3, de exemplu RON,ENG")
    return out


def _interogare(celex: str, limbi: Sequence[str]) -> str:
    filtre = " || ".join(f'str(?langCode)="{limba}"' for limba in _limbi(limbi))
    return f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX purl: <http://purl.org/dc/elements/1.1/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT DISTINCT ?work ?expr ?manif ?langCode ?format ?item ?title
                ?date_document ?legal_type ?in_force
WHERE {{
  ?work owl:sameAs <{CELEX_URI.format(celex=celex)}> .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language ?lang .
  ?lang purl:identifier ?langCode .
  FILTER({filtre})
  OPTIONAL {{ ?expr cdm:expression_title ?title . }}
  OPTIONAL {{ ?work cdm:work_date_document ?date_document . }}
  OPTIONAL {{ ?work cdm:resource_legal_type ?legal_type . }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?in_force . }}
  ?manif cdm:manifestation_manifests_expression ?expr ;
         cdm:manifestation_type ?format .
  ?item cdm:item_belongs_to_manifestation ?manif .
}}
LIMIT 500
""".strip()


@dataclass(frozen=True)
class _Raspuns:
    body: bytes
    headers: object


def _deschide_url(cerere, *, timeout: float, opener=urllib.request.urlopen) -> _Raspuns:
    try:
        with opener(cerere, timeout=timeout) as raspuns:
            return _Raspuns(
                body=raspuns.read(),
                headers=getattr(raspuns, "headers", {}),
            )
    except urllib.error.URLError as e:
        raise CellarError(str(e)) from e


def _val(binding: dict, cheie: str) -> str:
    return str((binding.get(cheie) or {}).get("value") or "")


def _bool(brut: str) -> bool | None:
    if brut == "":
        return None
    return brut.lower() in {"true", "1"}


def manifestari_celex(
    celex: str,
    *,
    limbi: Sequence[str] = LIMBI_IMPLICITE,
    timeout: float = 30.0,
    opener=urllib.request.urlopen,
) -> list[ManifestareUE]:
    """Return Cellar manifestations for one CELEX id, sorted by language and text usefulness."""
    celex = normalizeaza_celex(celex)
    limbi = _limbi(limbi)
    corp = urllib.parse.urlencode({"query": _interogare(celex, limbi)}).encode("utf-8")
    cerere = urllib.request.Request(
        SPARQL_ENDPOINT,
        data=corp,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    raspuns = _deschide_url(cerere, timeout=timeout, opener=opener)
    try:
        date = json.loads(raspuns.body.decode("utf-8", "replace"))
    except ValueError as e:
        raise CellarError("SPARQL nu a întors JSON") from e

    bindings = ((date.get("results") or {}).get("bindings") or []) if isinstance(date, dict) else []
    out: list[ManifestareUE] = []
    for b in bindings:
        limba = _val(b, "langCode").upper()
        item_url = _val(b, "item")
        if limba not in limbi or not item_url:
            continue
        out.append(
            ManifestareUE(
                celex=celex,
                work_uri=_val(b, "work"),
                expression_uri=_val(b, "expr"),
                manifestation_uri=_val(b, "manif"),
                limba=limba,
                format=_val(b, "format").lower(),
                item_url=item_url,
                titlu=normalizeaza(_val(b, "title")),
                data_document=_val(b, "date_document") or None,
                tip_uri=_val(b, "legal_type") or None,
                in_vigoare=_bool(_val(b, "in_force")),
            )
        )
    if not out:
        raise CelexNegasit(f"{celex}: niciun rezultat Cellar pentru {','.join(limbi)}")
    out.sort(key=lambda m: _rang_manifestare(m, limbi))
    return out


def _rang_manifestare(m: ManifestareUE, limbi: Sequence[str]) -> tuple[int, int, int, str]:
    try:
        rang_limba = tuple(limbi).index(m.limba)
    except ValueError:
        rang_limba = len(limbi)
    rang_format = PRIORITATE_FORMAT.get(m.format, 80)
    doc = 0 if m.item_url.endswith("/DOC_1") else 1
    return rang_limba, rang_format, doc, m.item_url


def _rang_doc(m: ManifestareUE) -> tuple[int, str]:
    nr = _DOC_NR.search(m.item_url)
    return int(nr.group(1)) if nr else 9999, m.item_url


def _parti_manifestare(
    manifestare: ManifestareUE, manifestari: Sequence[ManifestareUE] | None
) -> list[ManifestareUE]:
    if not manifestari:
        return [manifestare]
    parti = [
        m
        for m in manifestari
        if m.manifestation_uri == manifestare.manifestation_uri and m.format == manifestare.format
    ]
    return sorted(parti or [manifestare], key=_rang_doc)


def alege_manifestare_text(
    manifestari: Sequence[ManifestareUE], *, limbi: Sequence[str] = LIMBI_IMPLICITE
) -> ManifestareUE:
    """The best readable official stream: Romanian first, English fallback, no PDF parsing."""
    limbi = _limbi(limbi)
    for m in sorted(manifestari, key=lambda x: _rang_manifestare(x, limbi)):
        if m.format in FORMATE_TEXT:
            return m
    raise TextIndisponibil("Cellar nu a oferit XHTML/XML/text; PDF parsing nu este încă inclus")


def descarca_text(
    manifestare: ManifestareUE,
    *,
    manifestari: Sequence[ManifestareUE] | None = None,
    timeout: float = 60.0,
    opener=urllib.request.urlopen,
) -> str:
    """Fetch and extract text from all item streams in the selected manifestation."""
    parti = _parti_manifestare(manifestare, manifestari)
    texte: list[str] = []
    ultima_eroare: TextIndisponibil | None = None
    for parte in parti:
        cerere = urllib.request.Request(
            parte.item_url,
            headers={
                "Accept": "application/xhtml+xml,text/html,application/xml,text/plain,*/*",
                "User-Agent": USER_AGENT,
            },
        )
        raspuns = _deschide_url(cerere, timeout=timeout, opener=opener)
        content_type = ""
        get = getattr(raspuns.headers, "get", None)
        if get:
            content_type = get("Content-Type", "") or ""
        try:
            texte.append(extrage_text(raspuns.body, content_type=content_type, format=parte.format))
        except TextIndisponibil as e:
            ultima_eroare = e
            if len(parti) == 1:
                raise
    if not texte:
        raise ultima_eroare or TextIndisponibil("manifestarea Cellar nu conține text")
    return _curata_text("\n\n".join(texte))


def _charset(content_type: str) -> str:
    m = re.search(r"charset=([^;\s]+)", content_type, re.I)
    return m.group(1).strip("\"'") if m else "utf-8"


class _TextHTML(HTMLParser):
    blocuri = {
        "address",
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignora: list[str] = []

    def _linie(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"head", "script", "style"}:
            self._ignora.append(tag)
        if tag in self.blocuri:
            self._linie()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._ignora and self._ignora[-1] == tag:
            self._ignora.pop()
        if tag in self.blocuri:
            self._linie()

    def handle_data(self, data: str) -> None:
        if not self._ignora:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _curata_text(text: str) -> str:
    text = normalizeaza(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extrage_text(brut: bytes, *, content_type: str = "", format: str = "") -> str:
    """Text from Cellar XHTML/XML/plain streams; PDFs are explicit unsupported data."""
    if brut.startswith(b"%PDF"):
        raise TextIndisponibil("Cellar a întors PDF; nu îl parsăm fără dependențe")
    text = brut.decode(_charset(content_type), "replace")
    if format.lower() != "txt" and re.search(r"<[A-Za-z!/][^>]*>", text):
        parser = _TextHTML()
        parser.feed(text)
        text = parser.text()
    text = _curata_text(text)
    if len(text) < 20:
        raise TextIndisponibil("streamul Cellar nu conține text suficient")
    return text


def _loc_articol(numar: str) -> str:
    return f"art{numar.lower()}"


def _loc_anexa(numar: str) -> str:
    return f"anexa-{numar.lower()}" if numar else "anexa"


def _linie_noua(line: str) -> tuple[str, str, str] | None:
    art = _ARTICOL.match(line)
    if art:
        return "articol", _loc_articol(art.group(1)), line
    anexa = _ANEXA.match(line)
    if anexa:
        return "anexa", _loc_anexa(anexa.group(1) or ""), line
    return None


def _titlu_dupa(linii: list[str], idx: int) -> str:
    urm = linii[idx + 1] if idx + 1 < len(linii) else ""
    if not urm or _linie_noua(urm) or _CONSIDERENT.match(urm):
        return ""
    if len(urm) > 140 or re.match(r"^\(?\d+[.)]?$", urm):
        return ""
    return urm


def _curata_bloc(linii: list[str]) -> str:
    return _curata_text("\n".join(linii))


def provizii_din_text(celex: str, text: str, limba: str) -> list[ProvizieUE]:
    """Split one imported EU act into citeable blocks.

    The split is intentionally coarse: recitals before the articles, each article as one unit, and
    annexes as one unit. That is enough for the first EU-law search surface to cite a location
    without pretending we already understand every table row inside an annex.
    """
    celex = normalizeaza_celex(celex)
    limba = limba.strip().upper()
    linii = [linie.strip() for linie in normalizeaza(text).splitlines() if linie.strip()]
    iesire: list[ProvizieUE] = []
    folosite: dict[str, int] = {}
    curent: tuple[str, str, str] | None = None
    buf: list[str] = []
    in_articole = False

    def unic(locator: str) -> str:
        folosite[locator] = folosite.get(locator, 0) + 1
        return locator if folosite[locator] == 1 else f"{locator}-{folosite[locator]}"

    def emite() -> None:
        nonlocal buf, curent
        if not curent or not buf:
            buf = []
            return
        fel, locator, titlu = curent
        bloc = _curata_bloc(buf)
        if bloc:
            iesire.append(
                ProvizieUE(
                    celex=celex,
                    locator=unic(locator),
                    fel=fel,
                    titlu=titlu,
                    text=bloc,
                    ord=len(iesire) + 1,
                    limba=limba,
                )
            )
        buf = []

    for i, linie in enumerate(linii):
        inceput = _linie_noua(linie)
        if inceput:
            emite()
            fel, locator, _ = inceput
            curent = (fel, locator, _titlu_dupa(linii, i))
            buf = [linie]
            in_articole = True
            continue

        considerent = _CONSIDERENT.match(linie)
        if considerent and not in_articole:
            emite()
            curent = ("considerent", f"considerent-{considerent.group(1)}", "")
            buf = [linie]
            continue

        if curent is None:
            curent = ("preambul", "preambul", "")
            buf = [linie]
        else:
            buf.append(linie)

    emite()
    if not iesire and text.strip():
        iesire.append(
            ProvizieUE(
                celex=celex,
                locator="document",
                fel="document",
                titlu="",
                text=_curata_text(text),
                ord=1,
                limba=limba,
            )
        )
    return iesire


def _sterge_provizii(con: sqlite3.Connection, celex: str) -> None:
    randuri = con.execute(
        "SELECT rowid, text, titlu, celex, locator, limba FROM eu_provizii WHERE celex = ?",
        (celex,),
    ).fetchall()
    for r in randuri:
        con.execute(
            "INSERT INTO eu_provizii_fts(eu_provizii_fts, rowid, text, titlu, celex, locator,"
            " limba) VALUES('delete', ?, ?, ?, ?, ?, ?)",
            (r["rowid"], r["text"], r["titlu"], r["celex"], r["locator"], r["limba"]),
        )
    con.execute("DELETE FROM eu_provizii WHERE celex = ?", (celex,))


def _scrie_provizie(con: sqlite3.Connection, p: ProvizieUE) -> None:
    cur = con.execute(
        "INSERT INTO eu_provizii (celex, locator, fel, titlu, text, ord, limba)"
        " VALUES (?,?,?,?,?,?,?)",
        (p.celex, p.locator, p.fel, p.titlu, p.text, p.ord, p.limba),
    )
    con.execute(
        "INSERT INTO eu_provizii_fts(rowid, text, titlu, celex, locator, limba)"
        " VALUES (?,?,?,?,?,?)",
        (cur.lastrowid, p.text, p.titlu, p.celex, p.locator, p.limba),
    )


def scrie_provizii_celex(con: sqlite3.Connection, celex: str, text: str, limba: str) -> int:
    """Replace one CELEX act's citeable provisions and their FTS rows."""
    celex = normalizeaza_celex(celex)
    _sterge_provizii(con, celex)
    provizii = provizii_din_text(celex, text, limba)
    for p in provizii:
        _scrie_provizie(con, p)
    return len(provizii)


def indexeaza_stocate(con: sqlite3.Connection, celex: str | None = None) -> int:
    """Backfill `eu_provizii` from texts already stored in `eu_acte`."""
    params = (normalizeaza_celex(celex),) if celex else ()
    clauza = " WHERE celex = ?" if celex else ""
    total = 0
    for r in con.execute(f"SELECT celex, limba, text FROM eu_acte{clauza}", params).fetchall():
        total += scrie_provizii_celex(con, r["celex"], r["text"], r["limba"])
    return total


def termeni_cautare(text: str, *, maxim: int = 18) -> list[str]:
    """Content words for the EU provision FTS prefilter."""
    termeni: list[str] = []
    for cuvant in re.findall(r"[a-z0-9]+", cheie(text)):
        bun = (len(cuvant) > 4 and cuvant not in _CUVINTE_GOLE) or (
            cuvant.isdigit() and len(cuvant) >= 2
        )
        if bun and cuvant not in termeni:
            termeni.append(cuvant)
    return termeni[:maxim]


def _fts_query(text: str) -> str:
    return " OR ".join(f'"{t}"' for t in termeni_cautare(text))


def cauta_ue(
    con: sqlite3.Connection,
    text: str,
    *,
    limita: int = 12,
    limba: str | None = None,
) -> list[dict]:
    """Deterministic EU provision candidates for a draft or query.

    This is a retrieval helper, not a legality verdict. Every row is a CELEX locator and a snippet
    from the official text stored locally.
    """
    intrebare = _fts_query(text)
    if not intrebare:
        return []
    limita = max(1, min(limita, 50))
    params: list[object] = [intrebare]
    clauza = ""
    if limba:
        clauza = " AND p.limba = ?"
        params.append(limba.strip().upper())
    try:
        randuri = con.execute(
            "SELECT p.celex, p.locator, p.fel, p.titlu, p.limba,"
            " a.titlu AS act_titlu, a.sursa_url, a.item_url,"
            " snippet(eu_provizii_fts, 0, '<mark>', '</mark>', '…', 28) AS fragment,"
            " rank AS scor"
            " FROM eu_provizii_fts f"
            " JOIN eu_provizii p ON p.rowid = f.rowid"
            " JOIN eu_acte a ON a.celex = p.celex"
            f" WHERE eu_provizii_fts MATCH ?{clauza}"
            " ORDER BY rank LIMIT ?",
            (*params, limita),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "celex": r["celex"],
            "locator": r["locator"],
            "fel": r["fel"],
            "titlu": r["titlu"] or "",
            "limba": r["limba"],
            "act_titlu": r["act_titlu"] or "",
            "sursa_url": r["sursa_url"] or "",
            "item_url": r["item_url"] or "",
            "fragment": r["fragment"] or "",
            "scor": r["scor"],
            "termeni": termeni_cautare(text),
        }
        for r in randuri
    ]


def scrie_celex(
    con: sqlite3.Connection,
    celex: str,
    manifestari: Sequence[ManifestareUE],
    aleasa: ManifestareUE,
    text: str,
) -> int:
    """Atomically preserve old/new local observations and update the searchable act."""
    celex = normalizeaza_celex(celex)
    if aleasa.celex != celex:
        raise ValueError("Manifestarea nu apartine actului CELEX selectat.")
    if not con.in_transaction:
        con.execute("BEGIN")
    con.execute("SAVEPOINT import_ue")
    try:
        instantanee_ue.arhiveaza_curenta(con, celex)
        count = _scrie_celex(con, celex, manifestari, aleasa, text)
        instantanee_ue.arhiveaza_curenta(con, celex)
        con.execute("RELEASE import_ue")
        return count
    except Exception:
        con.execute("ROLLBACK TO import_ue")
        con.execute("RELEASE import_ue")
        raise


def _scrie_celex(
    con: sqlite3.Connection,
    celex: str,
    manifestari: Sequence[ManifestareUE],
    aleasa: ManifestareUE,
    text: str,
) -> int:
    """Store the selected text and all manifestations that justified the selection."""
    celex = normalizeaza_celex(celex)
    con.execute("DELETE FROM eu_manifestari WHERE celex = ?", (celex,))
    for m in manifestari:
        con.execute(
            "INSERT OR REPLACE INTO eu_manifestari (celex, work_uri, expression_uri,"
            " manifestation_uri, limba, format, titlu, data_document, tip_uri, in_vigoare,"
            " item_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                celex,
                m.work_uri,
                m.expression_uri,
                m.manifestation_uri,
                m.limba,
                m.format,
                m.titlu,
                m.data_document,
                m.tip_uri,
                None if m.in_vigoare is None else int(m.in_vigoare),
                m.item_url,
            ),
        )

    con.execute(
        "INSERT OR REPLACE INTO eu_acte (celex, work_uri, expression_uri, manifestation_uri,"
        " limba, format, titlu, data_document, tip_uri, in_vigoare, item_url, sursa_url, text,"
        " text_sha256, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            celex,
            aleasa.work_uri,
            aleasa.expression_uri,
            aleasa.manifestation_uri,
            aleasa.limba,
            aleasa.format,
            aleasa.titlu,
            aleasa.data_document,
            aleasa.tip_uri,
            None if aleasa.in_vigoare is None else int(aleasa.in_vigoare),
            aleasa.item_url,
            CELEX_URI.format(celex=celex),
            text,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    return scrie_provizii_celex(con, celex, text, aleasa.limba)


def importa_celex(
    celex: str,
    *,
    db: str = "eu.db",
    limbi: Sequence[str] = LIMBI_IMPLICITE,
    timeout: float = 60.0,
    opener=urllib.request.urlopen,
) -> dict:
    """Fetch one CELEX act and write it to the local EU database."""
    manifestari = manifestari_celex(celex, limbi=limbi, timeout=timeout, opener=opener)
    aleasa = alege_manifestare_text(manifestari, limbi=limbi)
    text = descarca_text(aleasa, manifestari=manifestari, timeout=timeout, opener=opener)
    with deschide(db) as con:
        prevederi = scrie_celex(con, aleasa.celex, manifestari, aleasa, text)
    return {
        "celex": aleasa.celex,
        "titlu": aleasa.titlu,
        "limba": aleasa.limba,
        "format": aleasa.format,
        "item_url": aleasa.item_url,
        "manifestari": len(manifestari),
        "prevederi": prevederi,
        "caractere": len(text),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("celex", nargs="*", help="CELEX id or URL, e.g. 32018R1805")
    ap.add_argument("--db", default="eu.db", help="SQLite database to write")
    ap.add_argument(
        "--indexeaza",
        action="store_true",
        help="Rebuild eu_provizii from already imported eu_acte rows instead of fetching",
    )
    ap.add_argument(
        "--limbi",
        default="RON,ENG",
        help="Comma-separated ISO 639-3 language preference order; default RON,ENG",
    )
    ap.add_argument("--timeout", type=float, default=60.0)
    a = ap.parse_args()
    limbi = tuple(x.strip() for x in a.limbi.split(",") if x.strip())
    if a.indexeaza:
        with deschide(a.db) as con:
            if a.celex:
                n = sum(indexeaza_stocate(con, celex=c) for c in a.celex)
            else:
                n = indexeaza_stocate(con)
        print(f"{n} prevederi UE indexate")
        raise SystemExit(0)
    if not a.celex:
        ap.error("celex este obligatoriu fără --indexeaza")
    for celex in a.celex:
        out = importa_celex(celex, db=a.db, limbi=limbi, timeout=a.timeout)
        print(
            f"{out['celex']} {out['limba']} {out['format']} · "
            f"{out['caractere']} caractere · {out['prevederi']} prevederi · {out['titlu']}"
        )
