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
