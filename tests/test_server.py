"""Tests for the backend wiring.

The server adds no logic — it routes to the engines — so the tests exercise the routing
functions directly over small temporary corpora rather than a live socket, which keeps them fast
and deterministic. The one thing worth asserting is that `lint` returns all three sections from
the two databases at once, and that search reaches the corpus FTS.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.cdep import Initiativa
from scripts.colector import act_din_inregistrare
from scripts.graf import construieste
from scripts.servicii import (
    Stare,
    _cauta,
    _lint,
    _norma,
    _prevedere,
    _redacteaza,
    _repealed,
    _targets,
    _vecini,
)


def _build(tmp_path: Path) -> Stare:
    corpus = tmp_path / "corpus.db"
    initiative = tmp_path / "initiative.db"
    rec = Inregistrare(
        titlu="LEGE nr. 98 din 2016",
        tip_act="LEGE",
        numar="98",
        an=None,
        data_vigoare=date(2016, 5, 26),
        emitent="PARLAMENTUL",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/178667",
        text="Art. 3. - În sensul prezentei legi, termenii de mai jos au următoarele "
        "semnificații:\na) achiziție publică - achiziția de lucrări sau servicii;",
    )
    with depozit.deschide(corpus) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    ini = Initiativa(
        plx_id="plx-1-2024",
        cam=2,
        idp="1",
        senat_id="L5/2024",
        tip="propunere legislativa",
        titlu="Lege pentru modificarea Legii nr. 98/2016",
        obiect="modificarea articolului 7 din Legea nr. 98/2016",
        urgenta=False,
        stadiu="pe ordinea de zi",
        camera_decizionala="Camera Deputaților",
        data_inreg="2024-01-01",
        sursa_url="",
    )
    with depozit.deschide(initiative) as con:
        depozit.scrie_initiativa(con, ini)
    return Stare(str(corpus), str(initiative))


def test_lint_reports_normative_register_apart_from_operation_form(tmp_path):
    """`limbaj` travels in its own key, partitioned out of `drafting` rather than added to it.

    The two answer different questions. `drafting` says the operation was named with the wrong verb;
    `limbaj` says the verb is right but the sentence is not written the way a norm is written.
    `conformitate` returns both in one list, so the split has to be a partition — computing `limbaj`
    separately would report every register finding twice, once under each heading.
    """
    stare = _build(tmp_path)
    draft = (
        "La articolul 7 din Legea nr. 98/2016 se modifică și va avea următorul cuprins: "
        "Normele metodologice se vor aproba de Guvern. "
        "Ofertantul trebuie să depună actele și/sau documentele, avizele etc."
    )
    out = _lint(draft, stare)
    gasite = {a["gasit"].lower() for a in out["limbaj"]}
    assert "se vor" in gasite  # future tense
    assert any("trebuie s" in g for g in gasite)  # obligation stated indirectly
    assert any("și/sau" in g or "si/sau" in g for g in gasite)  # ambiguous conjunction
    assert any(g.startswith("etc") for g in gasite)  # open enumeration
    # every finding explains itself and cites the rule, because the point is to fix the draft
    assert all(a["explicatie"] for a in out["limbaj"])
    # and none of this is also sitting in the operation-form pass — no finding is reported twice
    assert all(a["operatie"] != "limbaj" for a in out["drafting"])
    assert not {a["gasit"] for a in out["limbaj"]} & {a["gasit"] for a in out["drafting"]}
    # this draft names its operation correctly and supplies the cuprins clause, so the form pass has
    # nothing to say — which is the point: four findings, none of them about the verb
    assert out["drafting"] == []


def test_lint_still_reports_operation_form_errors_after_the_split(tmp_path):
    """The partition must not swallow the half it was meant to leave alone."""
    stare = _build(tmp_path)
    out = _lint("Articolul 7 din Legea nr. 98/2016 se elimină.", stare)
    assert any(a["operatie"] == "abroga" for a in out["drafting"])
    assert out["limbaj"] == []


def test_lint_limbaj_is_empty_for_a_draft_written_in_the_right_register(tmp_path):
    stare = _build(tmp_path)
    out = _lint("Autoritatea contractantă publică anunțul de participare.", stare)
    assert out["limbaj"] == []


def test_norma_carries_register_findings_alongside_coherence():
    """The composer asks both questions of one text, so one round trip answers both."""
    d = _norma("Normele metodologice se vor aproba de Guvern.")
    assert [a["gasit"].lower() for a in d["limbaj"]] == ["se vor"]
    # the coherence keys the badge already relies on are untouched
    assert {"dominanta", "coerent", "raport", "unitati", "abateri"} <= set(d)


def test_norma_register_findings_survive_a_neutral_text():
    """A text with no norm markers is `neutru`: the badge stays silent, «etc.» is still «etc.»."""
    d = _norma("Se depun actele, avizele etc.")
    assert d["dominanta"] == "neutru"
    assert any(a["gasit"].startswith("etc") for a in d["limbaj"])


def test_lint_returns_all_three_sections_from_both_databases(tmp_path):
    stare = _build(tmp_path)
    draft = (
        "La articolul 7 din Legea nr. 98/2016 privind achizițiile publice se modifică. "
        "În termen de 30 de zile de la intrarea în vigoare, Guvernul aprobă normele metodologice. "
        "Prezenta reglementează achizițiile de stat."
    )
    out = _lint(draft, stare)
    assert any(d["termen_zile"] == 30 for d in out["deadlines"])
    assert any(t["regula"] == "categorie-paralela" for t in out["terminology"])  # achiziții de stat
    assert out["duplicates"] and out["duplicates"][0]["plx_id"] == "plx-1-2024"
    assert out["duplicates"][0]["senat_id"] == "L5/2024"


NORMA_LOVITA = (
    "Cererea se soluționează fără citarea părților, în termen de 15 zile de la "
    "înregistrare, iar hotărârea pronunțată de instanță este definitivă și nu poate fi "
    "atacată cu recurs."
)


DECIZIE_CARE_LOVESTE = (
    "DECIZIE nr. 9 din 25 noiembrie 1994 EMITENT CURTEA CONSTITUȚIONALĂ "
    "Publicat în MONITORUL OFICIAL nr. 326 din 25 noiembrie 1994 "
    "CURTEA În numele legii DECIDE: "
    "Admite excepția și constată că art. 5 alin. (7) din Legea nr. 59/1993 este "
    "neconstituțional. Definitivă și general obligatorie."
)


def _cu_lovitura(tmp_path: Path) -> tuple[str, str]:
    """A corpus holding the struck law and the decision that struck it, plus its graph."""
    corpus, graf = tmp_path / "c.db", tmp_path / "g.db"
    acte = [
        Inregistrare(
            titlu="LEGE nr. 59/1993",
            tip_act="LEGE",
            numar="59",
            an=1993,
            data_vigoare=date(1993, 7, 1),
            emitent="PARLAMENTUL",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/591993",
            # Alineate run 1..7 because `parsare_text` only takes a marker that is the next one
            # expected — that sequence rule is what stops a cited `alin. (2)` in running text from
            # reading as a heading, and a fixture that skipped to (7) would parse to nothing.
            text=(
                "Articolul 5\n"
                "(1) Cererea se depune la instanța competentă.\n"
                "(2) Cererea se timbrează.\n"
                "(3) Cererea se comunică părților.\n"
                "(4) Termenul este de 15 zile.\n"
                "(5) Ședința este publică.\n"
                "(6) Hotărârea se motivează.\n"
                f"(7) {NORMA_LOVITA}\n"
            ),
        ),
        Inregistrare(
            titlu="DECIZIE nr. 9/1994",
            tip_act="DECIZIE",
            numar="9",
            an=1994,
            data_vigoare=date(1994, 11, 25),
            emitent="Curtea Constituțională",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/91994",
            text=DECIZIE_CARE_LOVESTE,
        ),
    ]
    with depozit.deschide(corpus) as con:
        for r in acte:
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
    construieste(str(corpus), str(graf), log=lambda *_: None)
    return str(corpus), str(graf)


DRAFT_PE_LOVITURA = "Art. I. — Se modifică art. 5 alin. (7) din Legea nr. 59/1993."


def test_a_draft_on_a_struck_provision_is_flagged_end_to_end(tmp_path, monkeypatch):
    """Decision → strike → register → shipped JSON → a finding on a pasted draft.

    Everything between the Court's words and the drafter's screen, with nothing stubbed. The
    corpus declares `lege` collected exhaustively, which is what earns the finding the right to
    block: see the next test for what happens when it cannot.
    """
    from scripts.servicii import construieste_neconstitutional

    corpus, graf = _cu_lovitura(tmp_path)
    randuri = construieste_neconstitutional(corpus, graf, complet_pentru=frozenset({"lege"}))
    assert randuri, "the register came back empty — the chain broke before the linter"

    monkeypatch.chdir(tmp_path)
    (tmp_path / "neconstitutional.json").write_text(
        json.dumps(randuri, ensure_ascii=False), encoding="utf-8"
    )
    initiative = tmp_path / "i.db"
    with depozit.deschide(initiative):
        pass
    stare = Stare(corpus, str(initiative), graf)

    out = _lint(DRAFT_PE_LOVITURA, stare)
    (c,) = out["neconstitutional"]
    assert c["act_id"] == "lege-59-1993"
    assert c["locator"] == "art5.alin7"
    assert c["potrivire"] == "exact"
    assert c["severitate"] == "blocking"
    assert c["decizie"] == "decizie-9-1994"
    # The quoted span is the provision as the decision names it — what makes the row checkable
    # against the Monitorul Oficial text without leaving the screen.
    assert c["citat"] == "art. 5 alin. (7) din Legea nr. 59/1993"


def test_a_corpus_that_claims_nothing_complete_warns_instead_of_blocking(tmp_path, monkeypatch):
    """The default, and the honest one. With no act type declared exhaustively collected, the
    register cannot tell an unrepaired provision from a repair it never collected — so the same
    draft, on the same strike, gets a warning rather than a verdict, and says why."""
    from scripts.servicii import construieste_neconstitutional

    corpus, graf = _cu_lovitura(tmp_path)
    randuri = construieste_neconstitutional(corpus, graf)  # complet_pentru empty by default
    assert all(r["severitate"] == "blocking" for r in randuri), "evidential severity was not set"

    monkeypatch.chdir(tmp_path)
    (tmp_path / "neconstitutional.json").write_text(
        json.dumps(randuri, ensure_ascii=False), encoding="utf-8"
    )
    initiative = tmp_path / "i.db"
    with depozit.deschide(initiative):
        pass
    stare = Stare(corpus, str(initiative), graf)

    (c,) = _lint(DRAFT_PE_LOVITURA, stare)["neconstitutional"]
    assert c["severitate"] == "material", "an unbacked register row blocked a draft"
    assert c["sustinut"] is False
    assert c["limitari"], "demoted without saying why"


def test_the_struck_text_itself_reaches_the_drafter(tmp_path, monkeypatch):
    """`lovituri.text` is the citation the decision used — a median of 24 characters, which names
    the provision and shows nobody what was struck. The words come from `prevedere.py`, recovered
    at build time so the browser can show them without holding the corpus they were cut out of."""
    from scripts.servicii import construieste_neconstitutional

    corpus, graf = _cu_lovitura(tmp_path)
    randuri = construieste_neconstitutional(corpus, graf, complet_pentru=frozenset({"lege"}))
    assert randuri[0]["norma"].strip() == NORMA_LOVITA
    assert randuri[0]["norma_granularitate"] == "exact"
    assert randuri[0]["norma_nota"] == "", "an exact recovery needs no caveat"

    monkeypatch.chdir(tmp_path)
    (tmp_path / "neconstitutional.json").write_text(
        json.dumps(randuri, ensure_ascii=False), encoding="utf-8"
    )
    initiative = tmp_path / "i.db"
    with depozit.deschide(initiative):
        pass
    stare = Stare(corpus, str(initiative), graf)

    (c,) = _lint(DRAFT_PE_LOVITURA, stare)["neconstitutional"]
    assert c["norma"].strip() == NORMA_LOVITA
    assert c["citat"] == "art. 5 alin. (7) din Legea nr. 59/1993", "the citation still travels too"


def test_lint_catches_a_re_enactment_that_cites_nothing(tmp_path, monkeypatch):
    """The pass `neconstitutional` cannot do. This draft names no act and no article — it just
    passes the struck wording again, which is what art. 147 (4) reaches. The citation check is
    silent; the wording check is not."""
    from scripts.servicii import construieste_norme_lovite

    corpus, graf = _cu_lovitura(tmp_path)
    norme = construieste_norme_lovite(corpus)
    assert norme and norme[0]["norma"], "no struck wording was recovered to compare against"

    monkeypatch.chdir(tmp_path)
    (tmp_path / "norme_lovite.json").write_text(
        json.dumps(norme, ensure_ascii=False), encoding="utf-8"
    )
    initiative = tmp_path / "i.db"
    with depozit.deschide(initiative):
        pass
    stare = Stare(corpus, str(initiative), graf)

    draft = (
        "Articolul 1\n"
        "(1) Prezenta lege reglementează procedura în fața instanțelor.\n"
        f"(2) {NORMA_LOVITA}\n"
    )
    out = _lint(draft, stare)
    assert out["neconstitutional"] == [], "the draft cites nothing; the citation pass must be quiet"
    (r,) = out["reluare"]["gasite"]
    assert r["act_id"] == "lege-59-1993"
    assert r["severitate"] == "material", "a wording measurement blocked a bill"
    assert out["reluare"]["acoperire"]["comparabile"] >= 1


def test_lint_says_what_the_re_enactment_check_compared_against(tmp_path, monkeypatch):
    """With no comparison set shipped, «nothing matched» would be a lie of omission."""
    monkeypatch.chdir(tmp_path)
    stare = _build(tmp_path)
    out = _lint(f"Articolul 1\n{NORMA_LOVITA}\n", stare)
    assert out["reluare"]["gasite"] == []
    assert out["reluare"]["acoperire"] == {"prevederi": 0, "comparabile": 0, "procent": 0}


def test_lint_is_silent_about_constitutionality_with_no_register_shipped(tmp_path, monkeypatch):
    """A localhost that was never built has no register. Silence, not a clean bill of health —
    and not a crash."""
    monkeypatch.chdir(tmp_path)
    stare = _build(tmp_path)
    assert stare.neconstitutional == []
    assert _lint(DRAFT_PE_LOVITURA, stare)["neconstitutional"] == []


def test_search_reaches_the_corpus_fts(tmp_path):
    stare = _build(tmp_path)
    assert _cauta("achizitie", stare)["results"]  # diacritic-folded
    assert _cauta("", stare)["results"] == []


def test_the_terminology_dictionary_is_built_from_the_corpus(tmp_path):
    stare = _build(tmp_path)
    assert any(t.termen == "achiziție publică" for t in stare.termeni)


def test_targets_report_how_amended_each_touched_act_is(tmp_path):
    """The graph turns "you amend Legea X" into "Legea X is on its Nth revision" — the fact most
    worth surfacing to someone about to patch it."""
    stare = _build(tmp_path)
    # build a graph where one act amends Legea 98/2016
    corpus2 = tmp_path / "corpus.db"
    from datetime import date

    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    with depozit.deschide(corpus2) as con:
        rec = Inregistrare(
            titlu="LEGE nr. 200 din 2024",
            tip_act="LEGE",
            numar="200",
            an=None,
            data_vigoare=date(2024, 1, 1),
            emitent="X",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/2000",
            text="Articolul 7 din Legea nr. 98/2016 se modifică.",
        )
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus2), str(graf_db))
    stare.graf = str(graf_db)

    out = _targets("Propunere pentru modificarea Legii nr. 98/2016.", stare)
    l98 = next((t for t in out if t["act_id"] == "lege-98-2016"), None)
    assert l98 and l98["amendat_de"] >= 1


def test_targets_are_empty_without_a_graph(tmp_path):
    stare = _build(tmp_path)
    stare.graf = str(tmp_path / "nonexistent.db")
    assert _targets("modificarea Legii nr. 98/2016", stare) == []


def test_lint_flags_a_citation_to_a_repealed_article(tmp_path):
    """The highest-severity thing the linter says: do not build on law that is gone."""
    from scripts.graf import construieste

    stare = _build(tmp_path)
    corpus2 = tmp_path / "corpus.db"
    from datetime import date

    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    with depozit.deschide(corpus2) as con:
        rec = Inregistrare(
            titlu="LEGE nr. 200",
            tip_act="LEGE",
            numar="200",
            an=None,
            data_vigoare=date(2024, 1, 1),
            emitent="X",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/2000",
            text="Articolul 7 din Legea nr. 98/2016 se abrogă.",
        )
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus2), str(graf_db))
    stare.graf = str(graf_db)

    out = _repealed("Se aplică art. 7 din Legea nr. 98/2016.", stare)
    assert out and out[0]["act_id"] == "lege-98-2016" and "abrogat" in out[0]["motiv"]
    # and it rides in the full lint answer
    assert "repealed" in _lint("Se aplică art. 7 din Legea nr. 98/2016.", stare)


def test_vecini_returns_deduped_neighbours(tmp_path):
    """Click-to-explore: one act's amenders and targets, one node per act even when it amends
    several of its articles."""
    from datetime import date

    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare
    from scripts.graf import construieste

    stare = _build(tmp_path)
    corpus2 = tmp_path / "corpus.db"
    with depozit.deschide(corpus2) as con:
        for numar, text in [
            (
                "200",
                "Articolul 7 din Legea nr. 98/2016 se modifică. "
                "Articolul 8 din Legea nr. 98/2016 se modifică.",
            ),
            ("201", "Se abrogă Legea nr. 98/2016."),
        ]:
            rec = Inregistrare(
                titlu=f"LEGE nr. {numar}",
                tip_act="LEGE",
                numar=numar,
                an=None,
                data_vigoare=date(2024, 1, 1),
                emitent="X",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}0",
                text=text,
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus2), str(graf_db))
    stare.graf = str(graf_db)

    v = _vecini("lege-98-2016", stare)
    ids = [m["act_id"] for m in v["inbound"]]
    assert "lege-200-2024" in ids and "lege-201-2024" in ids
    assert ids.count("lege-200-2024") == 1  # deduped despite two amended articles


def test_lint_flags_non_standard_drafting(tmp_path):
    """A draft that says the right thing the wrong way — the drafting-technique pass."""
    stare = _build(tmp_path)
    out = _lint("Articolul 7 din Legea nr. 98/2016 se schimbă.", stare)
    assert "drafting" in out
    assert out["drafting"] and out["drafting"][0]["operatie"] == "modifica"


def test_redacteaza_generates_mandated_form():
    """The draft assistant: a structured intent to the phrasing Legea 24/2000 requires. Pure —
    no corpus needed."""
    out = _redacteaza(
        {
            "op": ["modifica"],
            "act": ["Legea nr. 98/2016"],
            "articol": ["7"],
            "alineat": ["2"],
            "text": ["Autoritatea publică decide."],
        }
    )
    assert out["text"].startswith("La articolul 7 din Legea nr. 98/2016, alineatul (2) se modifică")
    assert "va avea următorul cuprins" in out["text"]
    assert out["titlu"] == "Lege pentru modificarea art. 7 din Legea nr. 98/2016"


def test_a_citation_to_the_constitution_finds_it(tmp_path):
    """It is stored as `constitutie-0-1991`, cited as `constitutie`, and before the resolver the
    two never met — 95 768 citations pointing at an act the corpus held and could not reach."""
    from scripts.servicii import Stare

    corpus = tmp_path / "corpus.db"
    with depozit.deschide(corpus) as con:
        con.executemany(
            "INSERT INTO acte (id, tip, titlu, citit_la) VALUES (?,?,?,'2020-01-01')",
            [
                ("constitutie-0-1991", "constitutie", "CONSTITUȚIA ROMÂNIEI"),
                ("constitutie-0-2003", "constitutie", "CONSTITUȚIA ROMÂNIEI republicată"),
                ("lege-98-2016", "lege", "Legea achizițiilor"),
            ],
        )
        con.commit()
    st = Stare(str(corpus), str(tmp_path / "i.db"))

    assert st.cunoscut("constitutie")  # was False
    assert st.rezolva_nume("constitutie") == "constitutie-0-2003"
    assert "CONSTITU" in st.titlu("constitutie").upper()  # was ""
    # an ordinary act is untouched, so callers can apply the resolver blindly
    assert st.rezolva_nume("lege-98-2016") == "lege-98-2016"
    assert not st.cunoscut("lege-1-1900")


def test_the_word_constitutie_is_recognised_after_a_preposition():
    """`din Constituție` — the commonest way an act cites it — matched nothing at all, because the
    pattern took only `Constituția`/`Constituției`."""
    from scripts.referinte import referinte

    assert [r.act.id for r in referinte("potrivit art. 1 din Constituție") if r.act] == [
        "constitutie"
    ]


def test_prevedere_returns_a_provisions_stored_text(tmp_path):
    """What a citation chip shows when its target is not among the rows on screen. The
    consolidation view lists only the provisions an amendment touched, so most citations inside it
    point at articles of the same act that are simply not rendered."""
    stare = _build(tmp_path)
    d = _prevedere({"act": ["lege-98-2016"], "loc": ["text"]}, stare)
    assert d["gasit"] and "achiziție publică" in d["text"]
    assert d["act_id"] == "lege-98-2016" and d["locator"] == "text"


def test_prevedere_says_so_for_an_act_with_no_article_tree(tmp_path):
    """The fixture act is the flattened case — the SOAP text arrives as one row under `text`, with
    nothing below the act addressable. Asking it for `art. 3` has to answer `gasit=False` even
    though those words are in the corpus, because no provision carries that locator.

    `gasit=False` rather than an empty string: a chip that quietly showed nothing would be
    indistinguishable from a provision that says nothing.
    """
    stare = _build(tmp_path)
    d = _prevedere({"act": ["lege-98-2016"], "loc": ["art3"]}, stare)
    assert d["gasit"] is False and d["text"] == ""


def test_prevedere_refuses_an_incomplete_request(tmp_path):
    stare = _build(tmp_path)
    assert _prevedere({"act": ["lege-98-2016"]}, stare)["gasit"] is False
    assert _prevedere({"loc": ["art3"]}, stare)["gasit"] is False
