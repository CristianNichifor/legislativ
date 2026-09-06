"""Tests for citation and locator extraction.

Every act type is tested in the genitive as well as the nominative, because the genitive is the
commoner form in real legislative prose and a pattern written only for the nominative loses most
of the corpus without failing.
"""

from __future__ import annotations

import pytest

from scripts.referinte import Act, acte, locatori, referinte


@pytest.mark.parametrize(
    ("text", "asteptat"),
    [
        ("Legea nr. 98/2016", "lege-98-2016"),
        ("prevederile Legii nr. 98/2016", "lege-98-2016"),
        ("Ordonanța de urgență a Guvernului nr. 57/2019", "oug-57-2019"),
        ("art. 5 din Ordonanței de urgență a Guvernului nr. 57/2019", "oug-57-2019"),
        ("Ordonanța Guvernului nr. 26/2000", "og-26-2000"),
        ("Hotărârea Guvernului nr. 395/2016", "hg-395-2016"),
        ("în aplicarea Hotărârii Guvernului nr. 395/2016", "hg-395-2016"),
        ("H.G. nr. 395/2016", "hg-395-2016"),
        ("Decretul nr. 100/1990", "decret-100-1990"),
    ],
)
def test_each_act_type_is_read_in_both_cases(text, asteptat):
    assert [r.act.id for r in acte(text)] == [asteptat]


def test_an_urgent_ordinance_is_not_read_as_an_ordinary_one():
    """They are different instruments with different constitutional weight. If the shorter
    pattern is tried first it claims the prefix and the act comes out as `og`."""
    assert acte("Ordonanța de urgență a Guvernului nr. 57/2019")[0].act.tip == "oug"


def test_dotted_thousands_in_an_order_number_are_a_separator_not_a_number():
    """`nr. 1.802/2014` is order 1802. Read as order 1 it merges with an unrelated act."""
    assert acte("Ordinul ministrului finanțelor publice nr. 1.802/2014")[0].act.id == (
        "ordin-1802-2014"
    )


def test_codes_are_cited_by_name_and_carry_no_number():
    ids = [r.act.id for r in acte("termenele din Codul de procedură fiscală și din Codul muncii")]
    assert ids == ["cod-procedura-fiscala", "cod-muncii"]


def test_republication_does_not_split_an_act_into_two_nodes():
    """`republicată` says which version is meant, and version belongs to the edge's date. In the
    id it would make Legea 98/2016 and Legea 98/2016 republicată two different laws."""
    simpla = acte("Legea nr. 98/2016")[0].act
    republicata = acte("Legea nr. 98/2016, republicată, cu modificările ulterioare")[0].act
    assert republicata.republicata and republicata.cu_modificari
    assert simpla.id == republicata.id


def test_the_genitive_of_articolul_is_read_as_an_article():
    """`articolului` is `articol` + `ului`. A pattern for `articolul` matches `articol` + `ul`,
    then meets `ui`, fails, and returns a paragraph belonging to no article."""
    assert [lc[0].id for lc in locatori("articolului 8")] == ["art8"]


def test_a_position_written_inside_out_is_one_position():
    """`Alineatul (3) al articolului 8` — read as two, an abrogation of it reports the whole of
    article 8 repealed when one paragraph was."""
    gasite = referinte("Alineatul (3) al articolului 8 se abrogă")
    assert [r.locator.id for r in gasite] == ["art8.alin3"]


def test_a_three_level_locator_chains_all_the_way_down():
    gasite = referinte("lit. a) a alineatului (2) al articolului 12^1")
    assert [r.locator.id for r in gasite] == ["art12^1.alin2.lita"]


def test_an_internal_reference_has_no_act_rather_than_a_wrong_one():
    """Internal references are most references. Treating them as unresolved empties the graph;
    guessing an act for them fills it with edges nobody wrote."""
    gasite = referinte("La articolul 7, alineatul (2) se modifică")
    assert gasite[0].este_interna and gasite[0].locator.id == "art7.alin2"


def test_a_locator_binds_across_a_joining_word_and_not_across_a_sentence():
    """Adjacency is not binding: in `art. 5 se modifică. Legea nr. 50/1991 se abrogă` the two
    belong to different sentences, and joining them would invent an amendment."""
    legat = referinte("art. 5 din Legea nr. 98/2016")
    assert legat[0].act == Act("lege", "98", 2016) and legat[0].locator.id == "art5"

    separat = referinte("art. 5 se modifică. Legea nr. 50/1991 se abrogă")
    intern = [r for r in separat if r.locator.id == "art5"]
    assert intern and intern[0].act is None


def test_every_reference_carries_the_span_it_was_read_from():
    """Findings quote the law rather than paraphrasing it, which needs the offsets."""
    text = "Se aplică prevederile Legii nr. 98/2016 în continuare."
    ref = acte(text)[0]
    assert text[ref.start : ref.end] == ref.text


# --- articole numerotate cu cifre romane -------------------------------------------------------
#
# `art. I` / `art. II` / `art. III` is the skeleton of every Romanian amending law: the Roman
# articles carry the amendments, the Arabic ones the substantive text, and both live in the same
# act. Reading only the Arabic ones cost the CCR register 109 of 215 rows, which came out claiming
# whole laws had been struck when the Court had struck a single article.


def test_a_roman_article_is_read():
    (ref,) = [r for r in referinte("art. II din Legea nr. 249/2006") if r.act]
    assert ref.act.id == "lege-249-2006"
    assert ref.locator.id == "artII"


def test_a_roman_article_is_not_the_arabic_one_of_the_same_value():
    """The load-bearing case. `art. II` and `art. 2` are different provisions of the same act,
    they routinely coexist, and collapsing them merges two unrelated texts into one locator —
    the same class of error as a citation-key collision."""
    (roman,) = locatori("art. II")
    (arab,) = locatori("art. 2")
    assert roman[0].id == "artII"
    assert arab[0].id == "art2"
    assert roman[0].id != arab[0].id


def test_a_roman_article_carries_its_sub_locators():
    (loc, _, _) = locatori("art. II alin. (1)")[0]
    assert loc.id == "artII.alin1"


@pytest.mark.parametrize(
    ("text", "asteptat"),
    [
        ("art. I", "artI"),
        ("art. IV", "artIV"),
        ("art. V", "artV"),
        ("art. VI", "artVI"),
        ("art. VIII", "artVIII"),
        ("art. IX", "artIX"),
        ("art. X", "artX"),
        ("art. XIV", "artXIV"),
        ("articolul II", "artII"),
    ],
)
def test_the_numerals_that_actually_appear(text, asteptat):
    assert locatori(text)[0][0].id == asteptat


@pytest.mark.parametrize(
    "text",
    [
        "art. viitor",  # `vii` would read as VII
        "articolul ivit",  # `iv` would read as IV
        "art. ii",  # lowercase is not how legal Romanian writes a numeral
    ],
)
def test_a_word_beginning_with_numeral_letters_is_not_an_article(text):
    """`re.IGNORECASE` on the locator pattern makes this the real risk: without a case rule and
    a trailing boundary, `art. viitor` becomes article VII."""
    assert [loc.id for loc, _, _ in locatori(text)] == [] or all(
        not loc.articol for loc, _, _ in locatori(text)
    )


def test_the_arabic_form_is_unaffected():
    assert locatori("art. 175 alin. (1) lit. b)")[0][0].id == "art175.alin1.litb"
    assert locatori("art. 12^1")[0][0].id == "art12^1"


# --- locatorul nu se citește din interiorul unui cuvânt ----------------------------------------
#
# The locator pattern has four optional parts, so it also matches the empty string and a plain
# `search` never skips — it evaluated the alternation once per character, which was both the
# 95-minute graph build and a steady source of false positives from `art` inside other words.


@pytest.mark.parametrize(
    "text",
    [
        "EN 12953-7:2002, Shell boilers-Part 7: Requirements",  # `Part 7` -> art7
        "Flanges and their joints-Bolting-Part 1: Classification",
        "Gerhart I. Hutter, profesor, director adjunct",  # `Gerhart I.` -> art I
        "conform standardului, compartimentul 3 se aplică",
    ],
)
def test_a_locator_is_not_read_from_inside_a_word(text):
    assert [loc.id for loc, _, _ in locatori(text)] == []


def test_a_locator_after_a_newline_is_still_found():
    """Real corpus text wraps mid-sentence; the position must not depend on the preceding space."""
    assert [loc.id for loc, _, _ in locatori("pe destinațiile prevăzute la\npct. 1-8")] == ["pct1"]
    assert [loc.id for loc, _, _ in locatori("imobilul transmis potrivit\nalin. (1)")] == ["alin1"]


# --- enumerarea nu trebuie să rupă legarea locatorului de act ----------------------------------


def test_an_enumeration_between_locator_and_act_does_not_orphan_it():
    """`art. II alin. (1) și (3) din Legea nr. 249/2006` is one citation, not two halves.

    With the enumeration in the way, the locator failed to bind and the act arrived with an
    empty locator — so the register read it as *the whole law struck*. That single failure is
    what produced most of the whole-act rows in the CCR list, `Legea nr. 249/2006` included.
    """
    refs = referinte("art. II alin. (1) și (3) din Legea nr. 249/2006")
    legat = [(r.act.id if r.act else None, r.locator.id) for r in refs]
    assert ("lege-249-2006", "artII.alin1") in legat
    # the act must NOT also appear bare, which is what reads as "whole act"
    assert ("lege-249-2006", "") not in legat


def test_a_comma_enumeration_binds_too():
    refs = referinte("art. 5, 6 din Legea nr. 98/2016")
    assert ("lege-98-2016", "art5") in [(r.act.id if r.act else None, r.locator.id) for r in refs]


def test_a_full_stop_between_them_still_does_not_bind():
    """Widening the joiner must not start binding across sentences."""
    refs = referinte("art. 5 se modifică. Legea nr. 50/1991 se abrogă")
    assert ("lege-50-1991", "") in [(r.act.id if r.act else None, r.locator.id) for r in refs]


# --- article enumerations: `la articolele 7 și 8` names two articles ---------------------------
#
# `ref-10` in the gold set. The locator pattern stops at the first number because there is no
# `art`/`alin` keyword in front of the second, so everything after it used to be dropped and an
# amendment to two articles was recorded against one.


def test_an_article_enumeration_is_expanded():
    assert [r.locator.id for r in referinte("La articolele 7 și 8 se fac completări.")] == [
        "art7",
        "art8",
    ]


def test_a_longer_enumeration_is_expanded_to_its_last_conjunction():
    assert [r.locator.id for r in referinte("art. 7, 8 și 9 se abrogă")] == [
        "art7",
        "art8",
        "art9",
    ]


def test_the_enumeration_extends_the_innermost_unit_named():
    """`art. 5 alin. (1), (2) și (3)` lists paragraphs of article 5, not articles."""
    assert [r.locator.id for r in referinte("art. 5 alin. (1), (2) și (3)")] == [
        "art5.alin1",
        "art5.alin2",
        "art5.alin3",
    ]


def test_every_member_of_an_enumeration_binds_to_the_act():
    """A sibling that came back unbound while its own first half was bound would read as a
    citation of a paragraph of nothing."""
    refs = referinte("art. II alin. (1) și (3) din Legea nr. 249/2006")
    assert [(r.act.id if r.act else None, r.locator.id) for r in refs] == [
        ("lege-249-2006", "artII.alin1"),
        ("lege-249-2006", "artII.alin3"),
    ]


def test_superscript_articles_enumerate():
    assert [r.locator.id for r in referinte("art. 7^1 și 8^2 se abrogă")] == ["art7^1", "art8^2"]


# The reason the conjunction is required. Each of these has a number after a comma that is not an
# article, and reading it as one invents a citation — the failure this package exists against.
def test_a_deadline_after_a_comma_is_not_an_enumeration():
    assert [r.locator.id for r in referinte("art. 5, 30 de zile de la publicare")] == ["art5"]


def test_a_year_after_a_comma_is_not_an_enumeration():
    assert [r.locator.id for r in referinte("art. 7, 2024 a fost anul")] == ["art7"]


def test_a_percentage_after_a_comma_is_not_an_enumeration():
    assert [r.locator.id for r in referinte("art. 5, 10% din valoare")] == ["art5"]


def test_a_comma_only_run_is_left_unread_rather_than_guessed():
    """`art. 7, 8, 9` is almost certainly an enumeration, but nothing distinguishes it from
    `art. 5, 30 de zile`. Missing one is a gap; inventing one is a false citation."""
    assert [r.locator.id for r in referinte("art. 7, 8, 9 se abrogă")] == ["art7"]


def test_the_run_stops_at_its_last_conjunction():
    """In `art. 7, 8 și 9, 10 zile` the list is 7, 8, 9 — the 10 belongs to the sentence."""
    assert [r.locator.id for r in referinte("art. 7, 8 și 9, 10 zile mai târziu")] == [
        "art7",
        "art8",
        "art9",
    ]


def test_letter_enumerations_stay_unexpanded():
    """The tail read here is numeric; writing a digit into `litera` would invent a position."""
    assert [r.locator.id for r in referinte("lit. a) și b) ale articolului 7")] == ["lita", "art7"]
