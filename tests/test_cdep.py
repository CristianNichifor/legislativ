"""Tests for the initiative collector, offline.

The Fișa parse and the year enumeration are the judgement; both run against recorded cdep pages
through the injected opener, so nothing here touches the network. The cross-chamber join — a
Chamber-of-Deputies Pl-x carrying the Senate's id — is the fact the whole duplicate-check leans
on, so it is asserted explicitly.
"""

from __future__ import annotations

import gzip
import io
import re
from pathlib import Path

from scripts import depozit
from scripts.cdep import colecteaza_cdep, idp_din_an, parseaza_fisa

FIX = Path(__file__).resolve().parent / "fixtures"
FISA = gzip.decompress((FIX / "cdep_fisa.html.gz").read_bytes()).decode("utf-8")
LISTA = (FIX / "cdep_lista.html").read_text(encoding="utf-8")


class _Resp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(pages: dict[str, str]):
    def opener(cerere, timeout=40):
        url = cerere.full_url if hasattr(cerere, "full_url") else cerere
        if "lista" in url:
            body = LISTA
        else:
            # each idp is a distinct bill, so give each a distinct Chamber number -> distinct plx,
            # the way the real portal does; otherwise the fixture collapses three idps into one.
            m = re.search(r"idp=(\d+)", url)
            idp = m.group(1) if m else "0"
            body = FISA.replace("33/03.02.2025", f"{idp}/03.02.2025")
        for frag, txt in pages.items():
            if frag in url:
                body = txt
        return _Resp(body.encode("utf-8"))

    return opener


def test_a_fisa_parses_into_its_fields():
    ini = parseaza_fisa(FISA, "21949", 2, url="u")
    assert ini.plx_id == "plx-33-2025"
    assert ini.tip == "propunere legislativa"
    assert ini.data_inreg == "2025-02-03"
    assert "cumul" in ini.obiect.lower()


def test_the_fisa_carries_the_senate_id_the_bill_has_in_the_other_chamber():
    """One initiative, a number in each chamber. The Pl-x Fișa naming L576/2024 is what lets a
    duplicate found under one number be recognised under the other."""
    ini = parseaza_fisa(FISA, "21949", 2)
    assert ini.senat_id == "L576/2024"


def test_the_stage_is_kept_so_a_dead_bill_is_not_offered_as_a_live_duplicate():
    ini = parseaza_fisa(FISA, "21949", 2)
    assert ini.stadiu and "raport" in ini.stadiu.lower()


def test_a_year_enumerates_to_initiative_handles():
    idps = idp_din_an(2025, opener=_opener({}))
    assert idps and all(i.isdigit() for i in idps)
    assert len(idps) == len(set(idps))  # de-duplicated


def test_a_run_stores_initiatives_and_makes_them_searchable(tmp_path: Path):
    db = tmp_path / "c.db"
    n = colecteaza_cdep(str(db), ani=[2025], pauza=0.0, opener=_opener({}))
    assert n >= 1
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["initiative"] == n
        rows = con.execute(
            "SELECT plx_id FROM initiative_fts WHERE initiative_fts MATCH 'cumul*'"
        ).fetchall()
        assert rows  # obiect is full-text searchable, diacritic-folded


def test_a_second_run_resumes_and_refetches_nothing(tmp_path: Path):
    db = tmp_path / "c.db"
    colecteaza_cdep(str(db), ani=[2025], pauza=0.0, opener=_opener({}))
    again = colecteaza_cdep(str(db), ani=[2025], pauza=0.0, opener=_opener({}))
    assert again == 0
