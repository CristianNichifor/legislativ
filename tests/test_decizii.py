"""Tests for reading a Curtea Constituțională decision's operative part.

Two of these are the ones that matter. The first is that `Respinge excepția de
neconstituționalitate a art. X` must strike nothing: the word `neconstituționalitate` appears in
every decision the Court ever rejected, and a parser keyed on the word rather than on the verb
would report the entire case law of Romania as struck down. The second is that a decision whose
object could not be read reports `ultra_petita is None` rather than an empty tuple — no finding
is the correct output when the comparison could not be made, and an empty tuple reads as "the
Court stayed within its referral", which is a claim nobody checked.
"""

from __future__ import annotations

from scripts.decizii import citeste, dispozitiv

# decizie-101-1996, as the portal serves it. One point, admitted, one provision struck.
D101 = (
    "DECIZIE Nr. 101*) din 25 octombrie 1995 EMITENT CURTEA CONSTITUȚIONALĂ "
    "Pe rol soluționarea excepției de neconstituționalitate a dispozițiilor art. 34 din "
    "Legea nr. 15/1994, invocată de Consiliul Județean Covasna în Dosarul nr. 525/1994 al "
    "Curții Supreme de Justiție - Secția de contencios administrativ. "
    "Pentru motivele arătate, în temeiul art. 144 lit. c) din Constituție, precum și al "
    "art. 13 alin. (1) lit. A.c), al art. 24 alin. (4) și al art. 25 alin. (1) din Legea "
    "nr. 47/1992, C U R T E A În numele legii D E C I D E: "
    "Admite excepția de neconstituționalitate invocată de Consiliul Județean Covasna în "
    "Dosarul nr. 525/1994 al Curții Supreme de Justiție - Secția de contencios administrativ "
    "și constata ca art. 34 din Legea nr. 15/1994 este neconstitutional. "
    "Cu recurs în termen de 10 zile de la comunicare. "
    "Pronunțată în ședința publică din 25 octombrie 1995. PREȘEDINTE, prof. univ. dr. Viorel "
    "Mihai Ciobanu"
)

# decizie-100-1996. Rejected, and the object is named in the operative part too — which is
# exactly where a word-matching parser goes wrong.
D100 = (
    "DECIZIE Nr. 100*) din 25 octombrie 1995 EMITENT CURTEA CONSTITUȚIONALĂ "
    "examinînd excepția de neconstituționalitate a Decretului-lege nr. 24/1990 privind "
    "sancționarea ocupării abuzive a locuințelor, invocată de Negru Ilie. "
    "în temeiul art. 144 lit. c) din Constituție, al art. 25 alin. (1) din Legea nr. 47/1992, "
    "în unanimitate, CURTEA În numele legii DECIDE: "
    "Respinge ca vadit nefondata excepția de neconstituționalitate a Decretului-lege "
    "nr. 24/1990 , invocată de Negru Ilie în Dosarul nr. 1.767/1995 al Judecătoriei Medias. "
    "Cu recurs în termen de 10 zile de la comunicare. Pronunțată la data de 25 octombrie 1995."
)

# decizie-4-2004 (pronounced 1992). A numbered operative part; point 3 is pure procedure and
# cites the Constitution, which is the standard of review and never the thing struck down.
D4 = (
    "DECIZIE nr. 4 din 3 iulie 1992 cu privire la constituționalitatea art. 27 și art. 34 din "
    "Legea privind regimul zonelor libere EMITENT CURTEA CONSTITUȚIONALĂ "
    "CURTEA În numele legii DECIDE: "
    "1. Declara neconstitutionala prevederea referitoare la naționalizarea investițiilor "
    "efectuate în zonele libere, cuprinsă în art. 27 din Legea privind regimul zonelor libere. "
    "2. Declara neconstitutional art. 34 din Legea privind regimul zonelor libere. "
    "3. Prezenta decizie se comunică Președintelui României, președintelui Camerei Deputaților "
    "și președintelui Senatului, în scopul deschiderii procedurii prevăzute de art. 145 "
    "alin. (1) din Constituție. "
    "Deliberarea a avut loc în data de 3 iulie 1992"
)

# A dissent runs on after the operative part and is not the Court's decision.
CU_OPINIE = (
    "CURTEA În numele legii DECIDE: "
    "Admite excepția și constată că art. 5 din Legea nr. 10/1999 este neconstituțional. "
    "Pronunțată în ședința publică din 1 martie 1999. "
    "OPINIE SEPARATĂ Consideram ca și art. 9 din Legea nr. 10/1999 este neconstitutional."
)


def test_the_operative_part_starts_at_decide_and_excludes_the_legal_basis():
    d = dispozitiv(D101)
    assert d is not None
    assert d.startswith("Admite excepția")
    # `art. 144 din Constituție` and `Legea nr. 47/1992` are the Court's own authority to rule.
    # They sit before DECIDE, and a slice that kept them would strike the Court's organic law.
    assert "temeiul" not in d
    assert "47/1992" not in d


def test_the_operative_part_stops_before_a_dissent():
    d = dispozitiv(CU_OPINIE)
    assert d is not None
    assert "art. 9" not in d


def test_an_admitted_exception_strikes_the_provision_it_names():
    dec = citeste("decizie-101-1996", D101)
    assert dec.solutii == ("admite",)
    assert [(p.act, p.locator) for p in dec.neconstitutionale] == [("lege-15-1994", "art34")]


def test_a_rejected_exception_strikes_nothing():
    dec = citeste("decizie-100-1996", D100)
    assert dec.solutii == ("respinge",)
    assert dec.neconstitutionale == ()


def test_a_numbered_operative_part_is_read_point_by_point():
    dec = citeste("decizie-4-2004", D4)
    assert len(dec.puncte) == 3
    assert [p.solutie for p in dec.puncte] == ["constata", "constata", "altele"]


def test_the_constitution_is_the_standard_of_review_and_is_never_struck():
    dec = citeste("decizie-4-2004", D4)
    assert all(p.act != "constitutie" for p in dec.neconstitutionale)


def test_a_provision_whose_act_cannot_be_identified_is_a_limitation_not_a_guess():
    # `Legea privind regimul zonelor libere` carries no number and no year, so it cannot be
    # keyed. Reporting `art. 27` against a guessed law is the failure this repository exists
    # to avoid; the provision is still counted, and it says it is unresolved.
    dec = citeste("decizie-4-2004", D4)
    neidentificate = [p for p in dec.neconstitutionale if p.act is None]
    assert neidentificate, "the struck provisions were dropped instead of reported"
    assert any("neidentificat" in lim for lim in dec.limitari)


def test_ultra_petita_is_none_when_the_object_could_not_be_read():
    # D4 has no `Pe rol` and no readable referral object. `()` would read as "the Court stayed
    # inside its referral", which is a claim nobody made.
    dec = citeste("decizie-4-2004", D4)
    assert dec.ultra_petita is None


def test_a_decision_that_strikes_exactly_what_was_referred_is_not_ultra_petita():
    dec = citeste("decizie-101-1996", D101)
    assert dec.obiect
    assert dec.ultra_petita == ()


def test_striking_a_provision_outside_the_referral_is_ultra_petita():
    text = D101.replace(
        "și constata ca art. 34 din Legea nr. 15/1994 este neconstitutional",
        "și constata ca art. 34 și art. 35 din Legea nr. 15/1994 sunt neconstitutionale",
    )
    dec = citeste("decizie-101-1996", text)
    assert dec.ultra_petita is not None
    assert [(p.act, p.locator) for p in dec.ultra_petita] == [("lege-15-1994", "art35")]


def test_striking_a_whole_article_when_only_a_paragraph_was_referred_is_ultra_petita():
    text = D101.replace(
        "a dispozițiilor art. 34 din Legea nr. 15/1994",
        "a dispozițiilor art. 34 alin. (2) din Legea nr. 15/1994",
    )
    dec = citeste("decizie-101-1996", text)
    assert [(p.act, p.locator) for p in dec.ultra_petita or ()] == [("lege-15-1994", "art34")]


# decizie-16-1994. The art. 150 (1) route: the provision was abrogated by the Constitution
# itself, and the Court records it rather than striking it. A quarter of the early docket.
D16 = (
    "DECIZIE nr. 16 din 1994 EMITENT CURTEA CONSTITUȚIONALĂ CURTEA În numele legii DECIDE: "
    "Constata ca, potrivit Deciziei Curții Constituționale nr. 33 din 26 mai 1993, rămasă "
    "definitivă, art. 224 din Codul penal este abrogat parțial, conform art. 150 alin. (1) din "
    "Constituție. Definitivă. Pronunțată la 1 martie 1994."
)


def test_the_article_150_abrogation_is_read_and_kept_apart_from_a_strike():
    dec = citeste("decizie-16-1994", D16)
    lovite = dec.neconstitutionale
    assert [(p.act, p.locator, p.fel) for p in lovite] == [
        ("cod-penal", "art224", "abrogat_constitutional")
    ]


def test_a_decision_still_open_to_recourse_says_its_strike_is_not_settled():
    dec = citeste("decizie-101-1996", D101)
    assert dec.definitiva is False
    assert any("recurs" in lim for lim in dec.limitari)


def test_a_decision_final_by_non_appeal_is_marked_final():
    dec = citeste("decizie-16-1994", D16.replace("Definitivă.", "Definitivă prin nerecurare."))
    assert dec.definitiva is True


def test_a_declaration_naming_no_readable_provision_is_reported_not_dropped():
    # decizie-141-1994 strikes `Legea pentru aprobarea Ordonanței Guvernului nr. 50 din 12
    # august 1994` — a law named descriptively and dated in words. Silence here would read as
    # "this decision struck nothing".
    text = (
        "CURTEA În numele legii DECIDE: Declara ca Legea pentru aprobarea Ordonanței "
        "Guvernului nr. 50 din 12 august 1994 privind instituirea unei taxe este "
        "neconstitutionala. Pronunțată la 1 decembrie 1994."
    )
    dec = citeste("decizie-141-1994", text)
    assert dec.neconstitutionale == ()
    assert any("nu s-a putut citi nicio prevedere" in lim for lim in dec.limitari)


def test_a_decision_with_no_operative_part_says_so_instead_of_reporting_nothing():
    dec = citeste("hg-6-1992", "examinarea contestației înregistrate sub nr. 202 la 3 septembrie")
    assert dec.solutii == ()
    assert dec.neconstitutionale == ()
    assert any("dispozitiv" in lim for lim in dec.limitari)


def test_the_law_named_in_an_amending_laws_title_is_not_struck_too():
    """`Legea nr. 249/2006 pentru modificarea și completarea Legii nr. 393/2004` names two acts
    and the Court struck one. The second is in the *title* of the first — what the amending law
    is called — and counting it repeals a statute on the strength of a title.

    This is the real decizie-61-2007, whose dispozitiv is word-for-word its referral.
    """
    text = (
        "DECIZIE nr. 61 din 15 februarie 2007 EMITENT CURTEA CONSTITUȚIONALĂ "
        "CURTEA În numele legii DECIDE: "
        "Admite excepția de neconstituționalitate invocată din oficiu de Tribunalul Mehedinți "
        "și constată că dispozițiile art. II alin. (1) și (3) din Legea nr. 249/2006 pentru "
        "modificarea și completarea Legii nr. 393/2004 privind Statutul aleșilor locali sunt "
        "neconstituționale. Definitivă și general obligatorie."
    )
    dec = citeste("decizie-61-2007", text)
    lovite = [(p.act, p.locator) for p in dec.neconstitutionale]
    assert ("lege-249-2006", "artII.alin1") in lovite, lovite
    assert not any(act == "lege-393-2004" for act, _ in lovite), (
        "the amended law was struck because it appears in the amending law's title"
    )
    assert not any(act == "lege-249-2006" and loc == "" for act, loc in lovite), (
        "the act also came through bare, which reads as the whole law struck"
    )


def test_the_post_2003_finality_formula_is_recognised():
    """`Definitivă și general obligatorie` is how 84% of the case law states finality.

    Recognising only `Definitivă prin nerecurare` — the 1990s formula, 1% of decisions — marked
    16 999 of 20 006 decisions "finality unknown", and the register then warned on every one of
    them that a recourse might have reversed the strike. There is no recourse to search: article
    147 (4) makes a decision generally binding from publication, and the appeal to the plenum was
    abolished with the 2003 revision.
    """
    text = (
        "CURTEA În numele legii DECIDE: "
        "Admite excepția și constată că art. 5 din Legea nr. 10/1999 este neconstituțional. "
        "Definitivă și general obligatorie. "
        "Pronunțată în ședința publică din 1 martie 2015."
    )
    dec = citeste("decizie-1-2015", text)
    assert dec.definitiva is True
    assert not any("recurs" in lim for lim in dec.limitari)


def test_a_decision_still_open_to_recourse_is_unaffected():
    """The 1990s form must keep saying what it says — 218 decisions are genuinely not final."""
    assert citeste("decizie-101-1996", D101).definitiva is False
