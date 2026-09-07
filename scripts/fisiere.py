"""Documents in and documents out, without taking a dependency to do it.

The editor could only be fed by pasting plain text into a box, and could only be read by copying
its output to the clipboard. Both are the wrong end of how legislative drafts actually travel:
they arrive as `.docx` from a ministry and leave as something a person can attach to an email.

**Everything here is standard library, and that is not an accident.** This package has no runtime
dependencies, which is what lets a research team clone it and run it rather than install it. Two
of the four conversions turn out to be easy once you look at the format rather than at the
ecosystem around it:

- **`.docx` is a ZIP.** `word/document.xml` holds the paragraphs, `zipfile` and
  `xml.etree.ElementTree` are both stdlib, and reading it is thirty lines. Writing one is the same
  four files in the other direction.
- **Markdown is text** with punctuation to remove.

**PDF is not here, and the asymmetry is the point.** Writing one needs a layout engine; reading one
needs a text-extraction engine that copes with two decades of generators. Both are real
dependencies. Export gets PDF anyway, because a browser already has a layout engine and a print
stylesheet turns "Save as PDF" into a feature that costs nothing. Import does not, and pretending
otherwise with a fragile extractor would put a mangled draft in front of somebody who then edits
the mangling.

**Ordered-list markers are left alone.** Stripping `1.` from Markdown is standard and would be
wrong here: in a legislative text `1.` is a *punct*, an addressable unit that `parsare_text` reads.
Only the syntax that cannot be legislative numbering is removed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from io import BytesIO

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# What one upload may cost, in memory, before it is refused. A `.docx` is a ZIP, and a ZIP is a
# lever: 707 KB of well-chosen input expands to 295 MB of `word/document.xml`, which this reader
# accepted in 6,7 seconds and held as text — plus several times that again as a parse tree. The
# limits are here rather than in the page because a browser-side check on `file.size` is a
# suggestion: the endpoint is reachable without the page.
MAX_INCARCARE = 20 * 1024 * 1024  # the uploaded file itself
MAX_DESFACUT = 40 * 1024 * 1024  # `word/document.xml` after decompression

# Markdown syntax that cannot also be legislative numbering. Ordered lists are deliberately absent
# — see the module note.
# Every repetition here is bounded, and every "any space" is `[ \t]` rather than `\s`.
#
# The link and image patterns were `\[([^\]]*)\]\([^)]*\)`, which is quadratic on input the
# uploader chooses: on a run of `[` the engine tries each one as a start and scans to the end from
# each. Measured on the shipped version — 2 000 characters 0,02 s, 4 000 0,08 s, 8 000 0,33 s,
# 16 000 1,28 s — clean O(n²), and the 20 MB upload ceiling then *permits* the worst case rather
# than limiting it. A bounded repetition caps the work per start position, which is what turns the
# curve back into a line.
#
# `\s` is avoided in the line-anchored patterns for a second reason: it matches a newline, so
# `^\s{0,3}` under `re.M` could consume across lines and match a heading that is not at a line
# start.
_TITLU_MD = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_CITAT_MD = re.compile(r"^[ \t]{0,3}>[ \t]?", re.M)
_GARD_MD = re.compile(r"^[ \t]*```[^\n]*$", re.M)
_LEGATURA_MD = re.compile(r"\[([^\]\n]{0,300})\]\([^)\n]{0,500}\)")
_IMAGINE_MD = re.compile(r"!\[([^\]\n]{0,300})\]\([^)\n]{0,500}\)")
_ACCENT_MD = re.compile(r"(\*\*|__|\*|_|`)")
_LINIE_MD = re.compile(r"^[ \t]*([-*_])[ \t]*\1[ \t]*\1[ \t\-*_]{0,200}$", re.M)
_MULTE_GOALE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Citit:
    """What a file yielded, and how it was read. `fel` is stated so the UI can say so."""

    text: str
    fel: str
    paragrafe: int


def din_markdown(text: str) -> str:
    """Markdown to the plain text underneath it.

    Conservative on purpose. Headings, blockquote markers, code fences, link and image syntax and
    emphasis characters go; everything that could be an addressable unit of a law stays. A `1.` at
    the start of a line is a point, not a list item, and a parser that removed it would silently
    renumber the act.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _GARD_MD.sub("", text)
    # Link syntax needs `](` to exist at all. Checking for it first costs one linear scan and makes
    # the adversarial input — a long run of `[` with no link in it — cost nothing instead of
    # driving the bounded lookahead at every position.
    if "](" in text:
        text = _IMAGINE_MD.sub(r"\1", text)
        text = _LEGATURA_MD.sub(r"\1", text)
    text = _LINIE_MD.sub("", text)
    text = _TITLU_MD.sub("", text)
    text = _CITAT_MD.sub("", text)
    text = _ACCENT_MD.sub("", text)
    return _MULTE_GOALE.sub("\n\n", text).strip()


def din_docx(octeti: bytes) -> str:
    """A `.docx` to its paragraphs, one per line.

    A `.docx` is a ZIP whose `word/document.xml` holds the body. Runs are `w:t`, and a paragraph is
    the join of its runs — a single sentence is routinely split across several because the writer
    changed the font halfway through, so joining per paragraph rather than per run is what keeps
    `Articolul 7` from arriving as `Articol` + `ul 7`.

    `w:tab` becomes a space and `w:br` a newline, because both are how a drafter separates units
    inside one paragraph.
    """
    with zipfile.ZipFile(BytesIO(octeti)) as z:
        nume = "word/document.xml"
        if nume not in z.namelist():
            raise ValueError("fișierul nu conține word/document.xml — nu pare un .docx")
        # Read to a ceiling rather than to the end. The declared `file_size` is checked first
        # because it is free, and then ignored: it is a number in the archive an attacker writes,
        # so the read is capped again on the way out. One byte over the cap is a refusal, not a
        # truncation — a silently shortened act is worse than one that did not import.
        if z.getinfo(nume).file_size > MAX_DESFACUT:
            raise ValueError("documentul e prea mare pentru a fi citit (peste 40 MB desfăcut)")
        with z.open(nume) as f:
            brut = f.read(MAX_DESFACUT + 1)
        if len(brut) > MAX_DESFACUT:
            raise ValueError("documentul e prea mare pentru a fi citit (peste 40 MB desfăcut)")
    _fara_dtd(brut)
    radacina = ET.fromstring(brut)

    linii: list[str] = []
    for p in radacina.iter(f"{W}p"):
        bucati: list[str] = []
        for nod in p.iter():
            if nod.tag == f"{W}t":
                bucati.append(nod.text or "")
            elif nod.tag == f"{W}tab":
                bucati.append(" ")
            elif nod.tag == f"{W}br":
                bucati.append("\n")
        # Trailing whitespace goes, leading whitespace stays. The parser tolerates an indented
        # `Articolul 7` either way, so stripping the front would be tidiness bought with fidelity:
        # a draft that leaves as a file and comes back re-indented is one the drafter has to check.
        linie = "".join(bucati).rstrip()
        linii.append(linie if linie.strip() else "")
    return _MULTE_GOALE.sub("\n\n", "\n".join(linii)).strip()


_DOCTYPE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


def _fara_dtd(brut: bytes) -> None:
    """Refuse a document that declares a DTD, before any parser sees it.

    Entity expansion is how a few kilobytes of XML become gigabytes of text. The expat this runs
    against caps the amplification factor and rejects the classic attack on its own — but that is a
    property of one build of one library, checked once, on one machine. A document part of a `.docx`
    has no legitimate reason to declare entities, so refusing outright costs nothing and does not
    depend on which expat is underneath.
    """
    if _DOCTYPE.search(brut[:8192]):
        raise ValueError("documentul declară entități XML și nu poate fi citit în siguranță")


def citeste(octeti: bytes, nume: str = "") -> Citit:
    """One uploaded file into text, deciding by content first and by name second.

    The extension is a hint and not evidence: a `.docx` renamed `.txt` is still a ZIP, and a file
    the browser labelled `application/octet-stream` still has a signature. `PK\\x03\\x04` decides
    it before anything the caller claims.
    """
    if len(octeti) > MAX_INCARCARE:
        raise ValueError("fișierul e prea mare (peste 20 MB)")
    jos = (nume or "").lower()
    if octeti[:4] == b"PK\x03\x04":
        return _citit(din_docx(octeti), "docx")
    if octeti[:5] == b"%PDF-":
        raise ValueError(
            "PDF-urile nu pot fi citite fără o dependență de extragere a textului. "
            "Deschide-l și lipește textul, sau salvează-l ca .docx."
        )
    text = octeti.decode("utf-8", errors="replace")
    if jos.endswith((".md", ".markdown")):
        return _citit(din_markdown(text), "markdown")
    return _citit(text.replace("\r\n", "\n").replace("\r", "\n").strip(), "text")


def _citit(text: str, fel: str) -> Citit:
    """`paragrafe` is reported so the panel can say what arrived. A `.docx` that yields two lines
    is a file the reader should look at again, and a count is the cheapest way to notice."""
    return Citit(text, fel, sum(1 for linie in text.split("\n") if linie.strip()))


# --- ieșire ------------------------------------------------------------------------------------

# The OOXML namespaces, split only because they are long. A reader requires all three parts:
# what the package contains, the relationship that points at the document, and the document.
_OO = "http://schemas.openxmlformats.org/"
_CT = f"{_OO}package/2006/content-types"
_REL = f"{_OO}package/2006/relationships"
_DOC_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_RELS_CT = "application/vnd.openxmlformats-package.relationships+xml"
_OFICIU = f"{_OO}officeDocument/2006/relationships/officeDocument"
_WML = f"{_OO}wordprocessingml/2006/main"

_ANTET = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

_TIPURI = (
    f'{_ANTET}<Types xmlns="{_CT}">'
    f'<Default Extension="rels" ContentType="{_RELS_CT}"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    f'<Override PartName="/word/document.xml" ContentType="{_DOC_CT}"/>'
    "</Types>"
)

_RELS = (
    f'{_ANTET}<Relationships xmlns="{_REL}">'
    f'<Relationship Id="rId1" Type="{_OFICIU}" Target="word/document.xml"/>'
    "</Relationships>"
)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def catre_docx(titlu: str, text: str) -> bytes:
    """A title and a body into a `.docx` a word processor will open.

    The four parts a reader actually requires: the content types, the package relationship, and the
    document. Nothing else is written — no styles, no fonts, no settings — because every one of
    those is a claim about how the text should look, and this is a draft somebody else will format.

    `xml:space="preserve"` on every run, or a word processor drops the leading spaces that indent
    an alineat.
    """
    linii = [titlu, ""] + (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragrafe = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(linie)}</w:t></w:r></w:p>'
        for linie in linii
    )
    document = f'{_ANTET}<w:document xmlns:w="{_WML}"><w:body>{paragrafe}</w:body></w:document>'
    iesire = BytesIO()
    # Deterministic: a fixed timestamp, so the same draft exported twice is the same bytes and a
    # diff of two exports is a diff of the law rather than of when the button was pressed.
    with zipfile.ZipFile(iesire, "w", zipfile.ZIP_DEFLATED) as z:
        for nume, continut in (
            ("[Content_Types].xml", _TIPURI),
            ("_rels/.rels", _RELS),
            ("word/document.xml", document),
        ):
            info = zipfile.ZipInfo(nume, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, continut)
    return iesire.getvalue()
