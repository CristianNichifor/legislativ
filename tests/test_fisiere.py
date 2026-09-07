"""Tests for getting a draft in and out of the editor as a file.

The round trip is the load-bearing one: a `.docx` this package writes must be one it can read
back. It is not a proof that Word will open it, but it is the check that catches a malformed
package, and it costs nothing to keep.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from scripts import fisiere


def test_a_docx_this_package_writes_is_one_it_can_read():
    """Round trip. A draft that leaves as a file and comes back mangled is worse than one that
    never left, because the drafter edits the mangling."""
    text = "Articolul 1\n(1) Primul alineat.\na) prima literă;\nArticolul 2\nAl doilea articol."
    octeti = fisiere.catre_docx("LEGE nr. 1 din 2026", text)
    inapoi = fisiere.din_docx(octeti)
    assert inapoi.startswith("LEGE nr. 1 din 2026")
    for linie in text.split("\n"):
        assert linie in inapoi


def test_the_written_package_has_the_three_parts_a_reader_requires():
    octeti = fisiere.catre_docx("T", "corp")
    with zipfile.ZipFile(BytesIO(octeti)) as z:
        assert set(z.namelist()) == {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}


def test_two_exports_of_the_same_draft_are_the_same_bytes():
    """A fixed timestamp, so a diff of two exports is a diff of the law rather than of when the
    button was pressed."""
    a = fisiere.catre_docx("T", "corp")
    b = fisiere.catre_docx("T", "corp")
    assert a == b


def test_the_indentation_of_an_alineat_survives_the_export():
    """Without `xml:space="preserve"` a word processor drops leading spaces, and an alineat that
    was indented arrives flush with the article."""
    octeti = fisiere.catre_docx("T", "    (2) Alineatul indentat.")
    assert "    (2) Alineatul indentat." in fisiere.din_docx(octeti)


def test_markup_in_the_text_does_not_break_the_package():
    """A draft that quotes `<` or `&` — `art. 7 & 8`, `a < b` — must not produce invalid XML."""
    octeti = fisiere.catre_docx("Lege & altele", 'Condiția a < b și "citatul".')
    assert 'Condiția a < b și "citatul".' in fisiere.din_docx(octeti)


def _docx_din_paragrafe(*paragrafe: str) -> bytes:
    """A `.docx` written the way a word processor writes one: runs split mid-sentence."""
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    corp = "".join(
        "<w:p>" + "".join(f"<w:r><w:t>{bucata}</w:t></w:r>" for bucata in p.split("|")) + "</w:p>"
        for p in paragrafe
    )
    doc = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{corp}</w:body></w:document>'
    iesire = BytesIO()
    with zipfile.ZipFile(iesire, "w") as z:
        z.writestr("word/document.xml", doc)
    return iesire.getvalue()


def test_a_sentence_split_across_runs_comes_back_whole():
    """A word processor splits a run wherever the formatting changes, so `Articolul 7` routinely
    arrives as `Articol` + `ul 7`. Joining per run instead of per paragraph would import an act
    whose article headings the parser can no longer see."""
    octeti = _docx_din_paragrafe("Articol|ul 7", "(1) Primul| alineat.")
    assert fisiere.din_docx(octeti) == "Articolul 7\n(1) Primul alineat."


def test_a_file_that_is_not_a_docx_says_so_rather_than_half_reading_it():
    with pytest.raises(ValueError, match="word/document.xml"):
        iesire = BytesIO()
        with zipfile.ZipFile(iesire, "w") as z:
            z.writestr("altceva.txt", "nu e un document")
        fisiere.din_docx(iesire.getvalue())


# --- markdown -----------------------------------------------------------------------------------


def test_markdown_syntax_goes_and_the_text_stays():
    md = "# Titlu\n\nUn **articol** cu _accent_ și [o trimitere](http://x).\n\n> citat\n"
    curat = fisiere.din_markdown(md)
    assert "Titlu" in curat and "#" not in curat
    assert "Un articol cu accent și o trimitere." in curat
    assert curat.rstrip().endswith("citat")


def test_an_ordered_marker_is_a_point_and_is_not_stripped():
    """This is the one place the conservative choice matters. In Markdown `1.` is a list item and
    every converter removes it; in a legislative text it is a *punct*, an addressable unit the
    parser reads, and removing it silently renumbers the act."""
    curat = fisiere.din_markdown("Articolul 2\n\n1. prima definiție;\n2. a doua definiție;\n")
    assert "1. prima definiție;" in curat
    assert "2. a doua definiție;" in curat


def test_a_horizontal_rule_is_not_mistaken_for_a_dash_list():
    curat = fisiere.din_markdown("Articolul 1\n\n---\n\nArticolul 2")
    assert "---" not in curat
    assert "Articolul 1" in curat and "Articolul 2" in curat


# --- ce decide formatul --------------------------------------------------------------------------


def test_the_content_decides_the_format_and_not_the_name():
    """A `.docx` renamed `.txt` is still a ZIP. The signature is read before anything the caller
    claims, because the alternative is importing XML markup as though it were the law."""
    octeti = fisiere.catre_docx("T", "Articolul 1")
    citit = fisiere.citeste(octeti, nume="raport.txt")
    assert citit.fel == "docx"
    assert "Articolul 1" in citit.text


def test_a_pdf_is_refused_with_a_way_forward_rather_than_a_stack_trace():
    """Reading one needs a text-extraction dependency this package does not take. Saying so, and
    saying what to do instead, is better than a mangled draft somebody then edits."""
    with pytest.raises(ValueError, match="PDF"):
        fisiere.citeste(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", nume="proiect.pdf")


def test_plain_text_arrives_unchanged_and_says_how_it_was_read():
    citit = fisiere.citeste(b"Articolul 1\r\n(1) Text.\r\n", nume="p.txt")
    assert citit.fel == "text"
    assert citit.text == "Articolul 1\n(1) Text."
    assert citit.paragrafe == 2


def test_what_arrives_is_countable_so_a_bad_import_is_visible():
    """A `.docx` that yields two lines where the reader expected two hundred is a file to look at
    again, and the count is the cheapest way to notice."""
    octeti = fisiere.catre_docx("T", "unu\ndoi\ntrei")
    assert fisiere.citeste(octeti).paragrafe == 4  # titlul plus trei linii


# --- ce servește pagina ---------------------------------------------------------------------


def test_an_uploaded_file_comes_back_as_the_editors_block_tree(tmp_path):
    """One round trip, not two. A caller that got text back would immediately ask for the tree,
    and nothing else can be done with the text meanwhile."""
    import base64

    from scripts.servicii import _importa

    octeti = fisiere.catre_docx(
        "LEGE nr. 1 din 2026", "Articolul 7\n(1) Primul alineat.\n(2) Al doilea."
    )
    r = _importa("proiect.docx", base64.b64encode(octeti).decode())
    assert r["ok"] is True and r["fel"] == "docx"
    art = [n for n in r["noduri"] if n["numar"] == "7"]
    assert art, f"articolul 7 nu a fost recunoscut: {[n['numar'] for n in r['noduri']]}"
    assert len(art[0]["copii"]) == 2


def test_a_pdf_upload_is_told_what_to_do_instead(tmp_path):
    import base64

    from scripts.servicii import _importa

    r = _importa("proiect.pdf", base64.b64encode(b"%PDF-1.7\nrest").decode())
    assert r["ok"] is False
    assert "PDF" in r["eroare"] and ".docx" in r["eroare"]


def test_a_corrupt_upload_is_refused_rather_than_crashing():
    from scripts.servicii import _importa

    assert _importa("x.docx", "nu-e-base64!!")["ok"] is False
    assert _importa("x.docx", "")["ok"] is False


def test_the_draft_comes_back_as_a_docx_a_word_processor_opens():
    import base64

    from scripts.servicii import _docx

    r = _docx("LEGE nr. 2 din 2026", "Articolul 1\nTextul.")
    assert r["ok"] is True and r["nume"].endswith(".docx")
    octeti = base64.b64decode(r["continut_b64"])
    assert "Articolul 1" in fisiere.din_docx(octeti)


def test_exporting_nothing_says_so():
    from scripts.servicii import _docx

    assert _docx("T", "   ")["ok"] is False
