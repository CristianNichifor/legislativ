"""Tests for reading a bill's passage off its Fișa.

Both fixtures are real pages, saved from cdep.ro: one initiative still in committee with twenty
sponsors across two groups, one carried all the way to a recorded division and rejected. Between
them they cover every shape this module reads.

The load-bearing property is that **nothing is inferred**. A step with no date keeps `None`; an
opinion whose sense the page does not state stays `None` rather than being read as favourable. A
Fișa is a record of what happened, and its gaps are part of that record — filling them in would
turn "the committee has not answered yet" into "the committee approved".
"""

from __future__ import annotations

import gzip
import io
from pathlib import Path

from scripts.parcurs import (
    _fara_tabele_interne,
    parseaza_parcurs,
)

FIX = Path(__file__).resolve().parent / "fixtures"


def _fisa(nume: str) -> str:
    return gzip.decompress((FIX / nume).read_bytes()).decode("utf-8")


INITIATORI = _fisa("cdep_fisa_initiatori.html.gz")  # Pl-x 99/2021, in committee, 20 sponsors
PARCURS = _fisa("cdep_fisa_parcurs.html.gz")  # Pl-x 42/2021, rejected on a recorded vote


# --- initiatori --------------------------------------------------------------------------------


def test_every_sponsor_is_read_with_their_group():
    """The group is the answer to «who backed this». A flat list of names discards it."""
    p = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145")
    assert len(p.initiatori) == 20
    assert {i.grup for i in p.initiatori} == {"PNL", "neafiliati"}
    assert p.initiatori[0].nume == "Bola Bogdan-Alexandru"


def test_a_sponsor_carries_the_chambers_own_id():
    """Matching people by name merges two who share one and splits one spelled two ways. `idm` is
    what makes «everything this deputy signed» answerable later."""
    p = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145")
    assert all(i.idm and i.idm.isdigit() for i in p.initiatori)
    assert p.initiatori[0].idm == "45"


def test_the_chamber_is_read_from_the_link_when_the_heading_omits_it():
    """Some headings read `- neafiliati:` with no chamber word at all. The sponsor's own link
    carries `cam=2`, so the page does state it — just not where the heading is."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    (unic,) = p.initiatori
    assert unic.nume == "Cucșa Marian-Gheorghe"
    assert unic.camera == "Camera Deputaților"
    assert unic.grup == "neafiliati"


def test_sponsors_are_not_the_count_that_introduces_them():
    """`Initiator:` holds `20 deputati+senatori, din care:` and *then* the table of names. Read off
    the flattened page it returns the count as though it were a person."""
    p = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145")
    assert not any("deputati+senatori" in i.nume for i in p.initiatori)
    assert not any(i.nume.startswith("din care") for i in p.initiatori)


# --- etape -------------------------------------------------------------------------------------


def test_the_timeline_is_read_in_order_with_its_chamber():
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    assert len(p.etape) == 15
    assert p.etape[0].data == "2020-07-27"
    assert p.etape[0].camera == "Camera Deputaților"
    assert p.etape[0].actiune.startswith("prezentare în Biroul Permanent")
    # the chamber marker heads the steps under it and has to be carried down the table
    assert p.etape[1].camera == "Senat"


def test_a_step_with_no_date_keeps_none():
    """The Fișa leaves the date cell empty for a step that shares the day above it. Borrowing the
    previous row's date would state a date the page does not."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    assert any(e.data is None for e in p.etape)


def test_an_inner_table_does_not_truncate_the_step_it_sits_in():
    """The regression that cost six of fifteen steps. The committee table inside a step's cell has
    its own `<tr>`, so a non-greedy row match over the raw page ends the outer row at the inner
    row's close: the step came out reading `Adresa inițiatorului` — the label of a PDF link inside
    that table — instead of the step itself."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    assert not any(e.actiune.startswith("Adresa") for e in p.etape)
    assert any("primire punct de vedere de la Guvern" in e.actiune for e in p.etape)


def test_flattening_keeps_the_outer_table_intact():
    """Exactly one pass, and that is what protects the timeline. A second pass would find the
    timeline table innermost by then and flatten the page away."""
    plat = _fara_tabele_interne(PARCURS)
    assert plat.lower().count("<tr") < PARCURS.lower().count("<tr")
    assert "<table" in plat  # the outer table survives


# --- avize -------------------------------------------------------------------------------------


def test_an_opinion_is_read_with_its_source_number_and_sense():
    p = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145")
    primite = [a for a in p.avize if a.primit and a.de_la == "Consiliul Legislativ"]
    assert primite and primite[0].sens == "favorabil"
    assert primite[0].numar == "49"
    assert primite[0].data == "2021-02-17"


def test_a_deadline_is_not_part_of_the_body_that_was_asked():
    """`solicitare aviz de la Consiliul Legislativ termen: 16.02.2021` — the name stops before
    `termen`, which is the deadline the request was given."""
    p = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145")
    assert all(not a.de_la.endswith("termen") for a in p.avize)
    assert any(a.de_la == "Consiliul Legislativ" and not a.primit for a in p.avize)


def test_a_committee_opinion_names_the_committee():
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    assert any("Comisia pentru tehnologia informației" in a.de_la for a in p.avize)
    assert any("Comisia juridică" in a.de_la and a.sens == "respingere" for a in p.avize)


def test_an_opinion_with_no_stated_sense_stays_unknown():
    """`primire aviz de la:` with a committee and no verdict genuinely does not say. Reading it as
    favourable would invent an endorsement."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    tacute = [a for a in p.avize if a.primit and a.de_la.startswith("Comisia pentru")]
    assert tacute and all(a.sens is None for a in tacute)


# --- voturi ------------------------------------------------------------------------------------


def test_the_division_is_read_with_the_question_that_was_put():
    """296 votes *for rejection* is not 296 votes for the bill. Storing the tally without the
    question inverts the meaning of every rejected initiative."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    (vot,) = p.voturi
    assert (vot.pentru, vot.contra, vot.abtineri) == (296, 1, 0)
    assert vot.intrebare == "pentru respingere"
    assert vot.data == "2021-06-08"
    assert vot.camera == "Camera Deputaților"


def test_an_initiative_still_in_committee_has_no_vote():
    p = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145")
    assert p.voturi == ()


def test_the_stenogram_lands_on_the_step_it_belongs_to():
    """The debate is the next question a reader asks after the tally, and it belongs to the step
    rather than to the bill: a sitting runs through dozens of items and the link says which one."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    cu_steno = [e for e in p.etape if e.steno_ids]
    assert cu_steno, "niciun pas nu poartă stenograma"
    assert all(e.steno_idm for e in cu_steno), "ședința fără punctul din ea nu localizează nimic"


# --- entități ----------------------------------------------------------------------------------


def test_entities_in_the_action_text_are_decoded():
    """The page writes `&#539;` for `ț` inside a sentence the reader is meant to read."""
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    assert not any("&#" in e.actiune for e in p.etape)
    assert any("urgență" in e.actiune for e in p.etape)


def test_a_page_with_no_passage_yields_empty_tuples_not_an_error():
    p = parseaza_parcurs("<html><body>nimic</body></html>", "plx-1-2000", "0")
    assert p.etape == () and p.avize == () and p.voturi == () and p.initiatori == ()


# --- stocare -----------------------------------------------------------------------------------


class _Resp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(html: str):
    def opener(cerere, timeout=40):
        return _Resp(html.encode("utf-8"))

    return opener


def _corpus_cu_initiativa(tmp_path: Path):
    from scripts import depozit
    from scripts.cdep import Initiativa

    cale = tmp_path / "corpus.db"
    ini = Initiativa(
        plx_id="plx-42-2021",
        cam=2,
        idp="18765",
        senat_id=None,
        tip="propunere legislativa",
        titlu="Propunere",
        obiect="obiect",
        urgenta=False,
        stadiu="respinsă",
        camera_decizionala="Camera Deputaților",
        data_inreg="2021-02-01",
        sursa_url="",
    )
    with depozit.deschide(cale) as con:
        depozit.scrie_initiativa(con, ini)
    return cale


def test_the_passage_is_stored_and_reads_back(tmp_path: Path):
    from scripts import depozit
    from scripts.parcurs import colecteaza_parcurs

    cale = _corpus_cu_initiativa(tmp_path)
    r = colecteaza_parcurs(str(cale), opener=_opener(PARCURS), log=lambda *_: None)
    assert r["citite"] == 1 and r["esuate"] == 0

    with depozit.deschide(cale, readonly=True) as con:
        etape = con.execute(
            "SELECT data, camera, actiune FROM initiativa_etapa WHERE plx_id='plx-42-2021'"
            " ORDER BY ord"
        ).fetchall()
        vot = con.execute(
            "SELECT pentru, contra, abtineri, intrebare FROM initiativa_vot"
        ).fetchone()
        initiatori = con.execute("SELECT nume, grup, idm FROM initiativa_initiator").fetchall()
    assert len(etape) == 15
    assert etape[0][2].startswith("prezentare în Biroul Permanent")
    assert tuple(vot) == (296, 1, 0, "pentru respingere")
    assert tuple(initiatori[0]) == ("Cucșa Marian-Gheorghe", "neafiliati", "88")


def test_rereading_a_fisa_replaces_rather_than_duplicates(tmp_path: Path):
    """A Fișa is the authority on its own passage. A bill that was in committee last month has
    moved, and its steps have no identity of their own to merge on — several share a date and some
    carry none, so the page's order is all that distinguishes them."""
    from scripts import depozit
    from scripts.parcurs import colecteaza_parcurs

    cale = _corpus_cu_initiativa(tmp_path)
    for _ in range(2):
        colecteaza_parcurs(
            str(cale), doar_lipsa=False, opener=_opener(PARCURS), log=lambda *_: None
        )
    with depozit.deschide(cale, readonly=True) as con:
        (n_etape,) = con.execute("SELECT count(*) FROM initiativa_etapa").fetchone()
        (n_vot,) = con.execute("SELECT count(*) FROM initiativa_vot").fetchone()
    assert n_etape == 15 and n_vot == 1


def test_a_second_run_skips_what_is_already_read(tmp_path: Path):
    from scripts.parcurs import colecteaza_parcurs

    cale = _corpus_cu_initiativa(tmp_path)
    colecteaza_parcurs(str(cale), opener=_opener(PARCURS), log=lambda *_: None)
    r = colecteaza_parcurs(str(cale), opener=_opener(PARCURS), log=lambda *_: None)
    assert r["citite"] == 0


# --- inițiativa Guvernului ----------------------------------------------------------------------

GUVERN = _fisa("cdep_fisa_guvern.html.gz")  # Pl-x 1/2021, an OUG: no list of sponsors at all


def test_a_government_bill_names_the_government_not_a_list_of_documents():
    """The regression the two committee fixtures could not show. A Government bill has no sponsor
    table — the Fișa says `Initiator: | Guvern` — so searching forward for the next table found the
    unrelated `Consultati:` block and stored `Expunerea de motive` and `Forma inițiatorului` as
    initiators of an ordonanță de urgență."""
    p = parseaza_parcurs(GUVERN, "plx-1-2021", "19122")
    assert [i.nume for i in p.initiatori] == ["Guvern"]
    assert p.initiatori[0].idm is None


def test_a_table_of_documents_is_never_read_as_sponsors():
    p = parseaza_parcurs(GUVERN, "plx-1-2021", "19122")
    nume = {i.nume for i in p.initiatori}
    assert not any("Expunerea" in n or "Forma" in n or "Avizul" in n for n in nume)


# --- rezultatul votului --------------------------------------------------------------------------


def test_an_adoption_vote_states_that_it_adopted():
    """`adoptat de Camera Deputatilor rezultat vot pentru=275` carries no parenthetical, so before
    this the only thing separating 275 votes *for* a bill from 296 votes to throw one out was a
    null question. The sentence says which it is; that is read, not inferred."""
    p = parseaza_parcurs(GUVERN, "plx-1-2021", "19122")
    (vot,) = p.voturi
    assert vot.rezultat == "adoptat"
    assert vot.intrebare is None
    assert (vot.pentru, vot.contra, vot.abtineri) == (275, 34, 0)


def test_a_rejection_vote_states_that_it_rejected():
    p = parseaza_parcurs(PARCURS, "plx-42-2021", "18765")
    (vot,) = p.voturi
    assert vot.rezultat == "respins"
    assert vot.intrebare == "pentru respingere"


def test_the_members_who_did_not_vote_are_kept():
    """`nu au votat=3` is on the page and was being dropped."""
    p = parseaza_parcurs(GUVERN, "plx-1-2021", "19122")
    assert p.voturi[0].absenti == 3


def test_a_signature_carries_the_legislature_its_id_is_scoped_to():
    """`idm` is not a person. The Chamber reuses it between legislatures: measured on the collected
    corpus, 349 distinct values covered 1 044 distinct people, and `idm=56` alone was Buzoianu
    (USR), Ghica (USR), Ciobanu (PNL) and Lavric (AUR). Keyed on the id alone a profile merges
    strangers and reports one deputy sitting in three parties at once."""
    a = parseaza_parcurs(INITIATORI, "plx-99-2021", "19145").initiatori[0]
    b = parseaza_parcurs(PARCURS, "plx-42-2021", "18765").initiatori[0]
    assert a.leg == "2020" and a.idm == "45"
    assert b.leg == "2016" and b.idm == "88"
    assert (a.leg, a.idm) != (b.leg, b.idm)


def test_a_rate_ceiling_is_shared_by_every_worker():
    """Concurrency and politeness are separate dials. Three connections that each wait their turn
    against one clock is three times the throughput at the same load; three that each sleep
    between their own requests is three times the load."""
    import time as _t

    from scripts.parcurs import Ritm

    r = Ritm(20.0)
    t0 = _t.monotonic()
    for _ in range(4):
        r.asteapta()
    assert _t.monotonic() - t0 >= 0.15, "cererile nu au fost distanțate"
