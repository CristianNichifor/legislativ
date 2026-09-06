"""Tests for reading the constitutional ground a provision was struck on.

The ground is the part of a strike that *transfers*. That art. 224 of the old Penal Code fell is a
fact about that article; that it fell on equality grounds is something a drafter can use on a rule
they are writing today. So this is the most useful of the three CCR layers and the easiest to get
subtly wrong.

Three properties carry it.

**A mention is not a holding.** A decision argues about the grounds it rejects as fully as the ones
it accepts — invoked runs to a median of 3 articles per decision and a p90 of 8, violations to a
median of 1. `fel` keeps them apart and `increderea` grades them: `verbatim` for a violation quoted
next to a verb, `derived` for a bare appearance in reasoning.

**The Court's own articles are not grounds.** Article 147 appears in 17 221 of 20 006 decisions
because it is the article that makes its rulings binding. Left in, the leading ground in Romanian
constitutional law would appear to be "the Constitutional Court exists".

**The Constitution was renumbered in 2003**, and naming articles from one table would mislabel two
decades of case law: property moved from article 41 to 44, and article 41 became labour.
`test_the_2003_renumbering_decides_what_an_article_is_called` is the one that matters most, because
a wrong ground is worse than a bare number — a number sends a reader to the text, a wrong label
stops them looking.
"""

from __future__ import annotations

from datetime import date

from scripts.temeiuri import PROCEDURALE, considerente, rezumat, temeiuri


# The shape a decision actually has: reasoning, then the operative part after a spaced `DECIDE`.
def decizie(considerente_text: str) -> str:
    return (
        "DECIZIA nr. 1 din 10 martie 2008 EMITENT CURTEA CONSTITUȚIONALĂ "
        f"{considerente_text} "
        "CURTEA În numele legii D E C I D E: "
        "Admite excepția de neconstituționalitate. Definitivă și general obligatorie."
    )


def test_a_violation_is_read_from_the_verb_next_to_the_article():
    t = temeiuri(
        decizie(
            "Textul criticat încalcă principiul egalității, consacrat în art. 16 din Constituție."
        ),
        date(2008, 3, 10),
    )
    assert [x.articol for x in t] == ["16"]
    assert t[0].fel == "incalcat"
    assert t[0].nume == "egalitatea în drepturi"
    assert t[0].increderea == "verbatim"
    assert "încalcă" in t[0].text


def test_a_mention_is_not_a_holding():
    """A decision discusses the grounds it rejects too, so a bare appearance is the weaker claim
    and has to be phrased as one."""
    t = temeiuri(
        decizie(
            "Autorul excepției susține că dispozițiile ar fi contrare art. 44 din Constituție."
        ),
        date(2008, 3, 10),
    )
    assert t[0].fel == "invocat"
    assert t[0].increderea == "derived"
    assert "invocate" in rezumat(t).lower()


def test_a_violated_article_is_not_also_reported_as_merely_invoked():
    """The stronger reading of one ground supersedes the weaker rather than sitting beside it."""
    t = temeiuri(
        decizie(
            "Se invocă art. 16 din Constituție. Curtea reține că textul încalcă art. 16 "
            "alin. (1) din Constituție."
        ),
        date(2008, 3, 10),
    )
    assert [(x.articol, x.fel) for x in t] == [("16", "incalcat")]


def test_one_row_per_article_however_often_it_is_named():
    """212 of the 443 striking decisions name an article more than once — bare, then with a
    paragraph. Three rows for one ground is noise on a card with room for a sentence."""
    t = temeiuri(
        decizie(
            "Se invocă art. 21 din Constituție, respectiv art. 21 alin. (1) din Constituție "
            "și art. 21 alin. (3) din Constituție."
        ),
        date(2008, 3, 10),
    )
    assert len(t) == 1
    assert t[0].alineate == ("1", "3")
    assert "alin. (1), (3)" in t[0].eticheta


def test_the_courts_own_articles_are_never_grounds():
    """Art. 147 is in 17 221 of 20 006 decisions because it is what makes rulings binding."""
    t = temeiuri(
        decizie(
            "Potrivit art. 147 alin. (4) din Constituție, deciziile sunt general obligatorii. "
            "Textul încalcă art. 21 din Constituție."
        ),
        date(2008, 3, 10),
    )
    assert [x.articol for x in t] == ["21"]
    assert "147" in PROCEDURALE


def test_the_2003_renumbering_decides_what_an_article_is_called():
    """The revision of 29 October 2003 moved property from art. 41 to art. 44, and art. 41 became
    labour. One naming table would mislabel two decades of case law."""
    text = decizie("Textul încalcă art. 41 din Constituție.")
    vechi = temeiuri(text, date(1998, 5, 1))[0]
    nou = temeiuri(text, date(2018, 5, 1))[0]
    assert vechi.nume == "protecția proprietății private"
    assert nou.nume == "munca și protecția socială a muncii"
    assert vechi.articol == nou.articol == "41"


def test_a_decision_on_the_revision_boundary_reads_as_post_revision():
    text = decizie("Textul încalcă art. 41 din Constituție.")
    assert temeiuri(text, date(2003, 10, 29))[0].nume == "munca și protecția socială a muncii"
    assert temeiuri(text, date(2003, 10, 28))[0].nume == "protecția proprietății private"


def test_an_article_this_module_will_not_name_keeps_its_number():
    """A wrong ground is worse than a bare number: a number sends a reader to the text."""
    t = temeiuri(decizie("Textul încalcă art. 137 din Constituție."), date(2008, 3, 10))
    assert t[0].nume == ""
    assert t[0].eticheta == "art. 137"


def test_the_reasoning_stops_where_the_operative_part_begins():
    """A ground stated only in the dispositive is not reasoning, and reading the operative part as
    considerente would pick up the provisions struck as though they were grounds."""
    text = decizie("Curtea reține că textul încalcă art. 16 din Constituție.")
    cons = considerente(text)
    assert "încalcă art. 16" in cons
    # What has to be excluded is the operative part's *content* — the provisions struck. The
    # `D E C I D E` marker itself stays on the reasoning side, because `dispozitiv` returns what
    # follows it; that is boilerplate and matches nothing.
    assert "Admite excepția" not in cons
    assert "general obligatorie" not in cons


def test_a_decision_without_a_locatable_dispositive_is_read_whole():
    """Cutting the reasoning at a guess costs the grounds; reading the operative part as reasoning
    costs a little noise. 5 of 20 006 decisions have no dispositive this can find."""
    text = "Curtea reține că textul încalcă art. 16 din Constituție. Fără dispozitiv detectabil."
    assert considerente(text) == text
    assert [x.articol for x in temeiuri(text, date(2008, 3, 10))] == ["16"]


def test_no_date_assumes_the_current_constitution():
    """Right for anything recent and wrong for the 1990s, so callers that have the date give it."""
    assert temeiuri(decizie("încalcă art. 44 din Constituție."), None)[0].nume == (
        "dreptul de proprietate privată"
    )


def test_violations_are_reported_before_mere_mentions():
    t = temeiuri(
        decizie("Se invocă art. 1 din Constituție. Textul încalcă art. 21 din Constituție."),
        date(2008, 3, 10),
    )
    assert [x.fel for x in t] == ["incalcat", "invocat"]
    assert rezumat(t).startswith("încalcă art. 21")


def test_a_decision_with_no_constitutional_reference_says_nothing():
    assert temeiuri(decizie("Curtea respinge ca inadmisibilă."), date(2008, 3, 10)) == []
    assert rezumat([]) == ""
