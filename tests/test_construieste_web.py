"""Tests for what the browser build ships.

One property, and it was a real bug before it was a test. The build slices the corpus — a few
hundred acts out of a quarter-million — because the whole thing cannot go to a browser. The
struck-but-unrepaired register must *not* be sliced with it: it is 183 rows and 97 KB over the
entire national corpus, and it is small because the Court struck few things, not because the
corpus is small. Building it from the slice ships an empty register, and an empty register turns
the constitutionality check into a feature that silently never fires — the exact failure mode this
package treats as unforgivable, since a reader cannot tell it from a clean bill of health.

The build already makes this call for `graf.db`, which it copies whole for the same reason.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.graf import construieste

DECIZIE = (
    "DECIZIE nr. 9 din 25 noiembrie 1994 EMITENT CURTEA CONSTITUȚIONALĂ "
    "Publicat în MONITORUL OFICIAL nr. 326 din 25 noiembrie 1994 "
    "CURTEA În numele legii DECIDE: "
    "Admite excepția și constată că art. 5 alin. (7) din Legea nr. 59/1993 este "
    "neconstituțional. Definitivă și general obligatorie."
)


def _rec(titlu, tip, numar, an, emitent, text, portal) -> Inregistrare:
    return Inregistrare(
        titlu=titlu,
        tip_act=tip,
        numar=numar,
        an=an,
        data_vigoare=date(an, 1, 1),
        emitent=emitent,
        publicatie="MO",
        link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{portal}",
        text=text,
    )


LEGE = _rec(
    "LEGE nr. 59/1993",
    "LEGE",
    "59",
    1993,
    "PARLAMENTUL",
    "Art. 5. - (7) Cererea se soluționează fără citarea părților.",
    "591993",
)
DEC = _rec(
    "DECIZIE nr. 9/1994",
    "DECIZIE",
    "9",
    1994,
    "Curtea Constituțională",
    DECIZIE,
    "91994",
)


def _corpus(cale: Path, *inregistrari) -> Path:
    cale.parent.mkdir(parents=True, exist_ok=True)
    with depozit.deschide(cale) as con:
        for r in inregistrari:
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
    construieste(str(cale), str(cale.parent / "graf.db"), log=lambda *_: None)
    return cale


def test_the_register_is_built_from_the_whole_corpus_not_the_shipped_slice(tmp_path, monkeypatch):
    """The slice holds the law but not the decision that struck it — as a real slice does, since
    almost no Curtea Constituțională decisions fall in the first few hundred acts. Building from
    it would ship a register with nothing in it and no sign anything was missing."""
    from scripts import construieste_web

    root, data = tmp_path / "root", tmp_path / "root" / "web" / "data"
    _corpus(root / "corpus.db", LEGE, DEC)  # the collected corpus: law + decision
    _corpus(data / "corpus.db", LEGE)  # the shipped slice: law only
    monkeypatch.setattr(construieste_web, "ROOT", root)
    monkeypatch.setattr(construieste_web, "DATA", data)

    construieste_web._neconstitutional_json()

    randuri = json.loads((data / "neconstitutional.json").read_text(encoding="utf-8"))
    assert len(randuri) == 1, "the register was built from the slice, so it shipped empty"
    assert randuri[0]["act_id"] == "lege-59-1993"
    assert randuri[0]["decizie"] == "decizie-9-1994"


def test_without_a_collected_corpus_the_register_ships_honestly_empty(tmp_path, monkeypatch):
    """CI and a fresh clone have no `corpus.db`. Falling back to the slice yields nothing, which is
    the truth about that build — not a crash, and not a fabricated register."""
    from scripts import construieste_web

    root, data = tmp_path / "root", tmp_path / "root" / "web" / "data"
    _corpus(data / "corpus.db", LEGE)
    monkeypatch.setattr(construieste_web, "ROOT", root)
    monkeypatch.setattr(construieste_web, "DATA", data)

    construieste_web._neconstitutional_json()

    assert json.loads((data / "neconstitutional.json").read_text(encoding="utf-8")) == []


def test_the_slice_does_not_select_acts_by_rowid(tmp_path, monkeypatch):
    """A rowid is a position in a file, not an identity.

    `scrie_act` deletes its row and inserts it again on every collection, so after a re-enrichment
    and the namesake recovery the lowest rowid in `acte` is far above any small N. `rowid <= 200`
    then matched nothing, and a build over a 203 353-act corpus shipped **five** acts — the curated
    ones — and called itself a corpus. Nothing failed; the numbers on the page were simply wrong.
    """
    import sqlite3

    from scripts import construieste_web as cw
    from scripts import depozit

    radacina = tmp_path / "radacina"
    radacina.mkdir()
    with depozit.deschide(str(radacina / "corpus.db")) as con:
        for n in range(1, 21):
            con.execute(
                "INSERT INTO acte (id, tip, numar, an, titlu, id_portal, citit_la)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"lege-{n}-2020", "lege", str(n), 2020, "T", str(n), "x"),
            )
        # Rewritten one at a time, exactly as `scrie_act` does it — delete, then insert. SQLite
        # only reuses a freed rowid when the table empties, so each rewrite moves that act to the
        # end and the low rowids are never handed out again. On the real corpus this leaves
        # `min(rowid) = 281` over 203 353 acts, and `rowid <= 200` matches none of them.
        for n in range(1, 16):
            con.execute("DELETE FROM acte WHERE id = ?", (f"lege-{n}-2020",))
            con.execute(
                "INSERT INTO acte (id, tip, numar, an, titlu, id_portal, citit_la)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"lege-{n}-2020", "lege", str(n), 2020, "T", str(n), "x"),
            )
        con.commit()
        assert con.execute("SELECT min(rowid) FROM acte").fetchone()[0] > 10
        assert con.execute("SELECT count(*) FROM acte WHERE rowid <= 10").fetchone()[0] == 0

    monkeypatch.setattr(cw, "ROOT", radacina)
    monkeypatch.setattr(cw, "DATA", tmp_path / "data")
    monkeypatch.setattr(cw, "CURATE", [])
    monkeypatch.setattr(cw, "N_ACTE", 10)
    (tmp_path / "data").mkdir()
    cw._slice_corpus()

    con = sqlite3.connect(tmp_path / "data" / "corpus.db")
    try:
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 10
    finally:
        con.close()


def test_worker_fara_depozit_nu_cere_corpusul(tmp_path, monkeypatch):
    """Without `--depozit` the worker must not reach for a corpus that was never published.

    The mount is guarded by `if (DEPOZIT)`, so an empty string has to stay empty: a stray
    placeholder would make the guard truthy and every visit would fetch a URL that is not there.
    """
    from scripts import construieste_web as cw

    monkeypatch.setattr(cw, "WEB", tmp_path)
    cw._worker()
    text = (tmp_path / "worker.js").read_text(encoding="utf-8")

    assert 'const DEPOZIT = "";' in text
    assert "__DEPOZIT__" not in text
    assert "__PYODIDE__" not in text


def test_worker_cu_depozit_monteaza_corpusul(tmp_path, monkeypatch):
    from scripts import construieste_web as cw

    monkeypatch.setattr(cw, "WEB", tmp_path)
    cw._worker("https://date.exemplu.ro/2026-09-08")
    text = (tmp_path / "worker.js").read_text(encoding="utf-8")

    assert 'const DEPOZIT = "https://date.exemplu.ro/2026-09-08";' in text
    # SQLite pages are 4 KB. A larger chunk fetches pages nobody asked for: measured against the
    # real corpus, 1 MiB cost 94 MB to open one law where 16 KB cost 1,19 MB.
    assert "const BUCATA = 16384;" in text
    # Both backends must survive the build — offline reads the same pages from disk.
    assert "prinRange" in text and "dinOpfs" in text and "monteaza" in text


def test_pagina_cu_depozit_incalzeste_banda_dupa_worker_ready(tmp_path, monkeypatch):
    """The first visible search must not be the call that pays for the mounted title engine."""
    from scripts import construieste_web as cw

    monkeypatch.setattr(cw, "WEB", tmp_path)
    cw._pagina("https://date.exemplu.ro/2026-09-08", felii_cautare=8)
    text = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert "let incalzireBanda = null;" in text
    assert 'const INCALZIRE_BANDA = "achizitii publice";' in text
    assert 'new URLSearchParams({q: INCALZIRE_BANDA, limita: "1", doar_titluri: "1"})' in text
    assert 'incalzireBanda = ready.then(() => call("/api/cauta", p.toString(), "")' in text
    assert "const pregatire = DEPOZIT_CAUTARE ? incalzesteBanda() : ready;" in text
    assert "new Promise(res => setTimeout(() => res(null), RABDARE_BANDA))" in text
    assert "incalzesteBanda().catch(()=>{});" in text
    assert "const BANDA_TITLURI = 8, RABDARE_BANDA = 25000;" in text
