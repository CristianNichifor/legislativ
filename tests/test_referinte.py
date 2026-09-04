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
