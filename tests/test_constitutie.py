"""The Constitution is one document parsed from one layout, so the parse is the whole risk.

A partial constitution is worse than none: every article missed is a provision the tool will
silently fail to quote while still answering confidently about the rest.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts import depozit
from scripts.constitutie import ID_ACT, parseaza, scrie

# The shape cdep.ro actually serves: a marginal note in an anchor, the article number in bold, then
# numbered paragraphs separated by <p>.
PAGINA = """
<TD><B><A NAME="t1c0s0sba1">Statul rom&acirc;n</A></B></TD>
<TD><B>ARTICOLUL 1</B><BR>(1) Rom&acirc;nia este stat na&#355;ional.
<p>(2) Forma de guvern&#259;m&acirc;nt este republica.
<TD><B><A NAME="t1c0s0sba2">Suveranitatea</A></B></TD>
<TD><B>ARTICOLUL 2</B><BR>Suveranitatea apar&#355;ine poporului rom&acirc;n.
"""


def test_parseaza_articolele_alineatele_si_notele_marginale():
    p = parseaza(PAGINA)
    dupa_locator = {x.locator: x.text for x in p}

    # The marginal note is the article's own heading, kept as `artN` so it can be cited.
    assert dupa_locator["art1"] == "Statul român"
    assert dupa_locator["art1.alin1"] == "România este stat naţional."
    assert dupa_locator["art1.alin2"] == "Forma de guvernământ este republica."
    # An article with a single unnumbered paragraph still gets `alin1`, so every provision has a
    # locator a citation can point at.
    assert dupa_locator["art2.alin1"] == "Suveranitatea aparţine poporului român."


def test_refuza_sa_scrie_o_constitutie_partiala(tmp_path):
    """156 articles or nothing. A layout change that halves the parse must fail, not publish."""
    db = tmp_path / "corpus.db"
    with depozit.deschide(str(db)):
        pass
    with pytest.raises(SystemExit, match="incomplet"):
        scrie(str(db), parseaza(PAGINA))

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT count(*) FROM acte WHERE id = ?", (ID_ACT,)).fetchone()[0] == 0
    finally:
        con.close()


def test_refuza_sa_scrie_nimic(tmp_path):
    db = tmp_path / "corpus.db"
    with depozit.deschide(str(db)):
        pass
    with pytest.raises(SystemExit):
        scrie(str(db), [])
