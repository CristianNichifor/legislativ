"""Tests for catching a draft that re-enacts wording the Court has already struck.

`coliziune.py` asks whether a draft *cites* a struck provision. This asks whether it *re-enacts*
one, which is what article 147 (4) reaches: a decision binds erga omnes, so it catches a norm
identical in substance however it is renumbered or moved. A draft can therefore re-enact a struck
rule while citing nothing at all — `test_a_re_enactment_is_caught_with_no_citation_at_all` is the
whole reason this module exists next to the other one.

Three properties carry it.

**The metric needs both halves.** Containment alone called every whole-document row a match: a
200 KB act's 5-gram set holds nearly all of Romanian legal prose, so it contains everything.
Jaccard alone scored 0.799 for a struck norm embedded in a slightly longer article — the realistic
case. Containment plus a size guard is what survived measurement, and
`test_a_huge_passage_does_not_match_by_containing_everything` is the regression that made it
necessary.

**Findings are never blocking.** Whether a re-enacted norm is *the same norm* in the Court's sense
is a legal judgement about substance; this is a measurement about characters.

**Coverage travels with the answer.** An empty result means "nothing matched among the provisions
I can quote", and on screen that is indistinguishable from "there was nothing to match against"
unless the answer says which.
"""

from __future__ import annotations

from scripts.reluare import PRAG, acoperire, amprenta, continut, jaccard, raport, reluari, unitati

# A real struck provision: art. 224 of the 1969 Penal Code, theft against socialist property,
# struck by decizia 33/1993 for offending equal protection of property.
NORMA = (
    "Furtul săvîrșit în paguba avutului obștesc se pedepsește cu închisoare de la 6 luni la 4 "
    "ani. Cînd furtul a avut consecințe deosebit de grave, pedeapsa este închisoarea de la 5 la "
    "20 de ani și interzicerea unor drepturi."
)


def norma(**kw) -> dict:
    return {
        "act_id": "codul-penal-0-1969",
        "locator": "art224",
        "decizie": "decizie-33-1993",
        "publicat": "1993-07-12",
        "norma": NORMA,
        "norma_granularitate": "exact",
        "norma_nota": "",
    } | kw


def test_a_re_enactment_is_caught_with_no_citation_at_all():
    """The case the citation check cannot see. This draft names no act and no article; it simply
    passes the struck rule again, which is precisely what art. 147 (4) reaches."""
    draft = (
        "Articolul 1\n"
        "(1) Prezenta lege reglementează regimul juridic al bunurilor.\n"
        f"(2) {NORMA}\n"
        "(3) Prezenta lege intră în vigoare la 30 de zile de la publicare.\n"
    )
    (r,) = reluari(draft, [norma()])
    assert r.act_id == "codul-penal-0-1969"
    assert r.scor >= 0.95
    assert r.unitate == "art1.alin2", "did not point at the paragraph that carries it"
    assert "147" in r.motiv
    assert r.severitate == "material", "a wording measurement blocked a bill"


def test_a_lightly_redrafted_copy_still_matches():
    """Re-enactment is rarely character-perfect — a redrafter trims. One word in twelve dropped
    measured 0.885 against the original, which is why the threshold sits at 0.80."""
    cuvinte = NORMA.split()
    subtiat = " ".join(w for i, w in enumerate(cuvinte) if i % 12 != 0)
    draft = f"Articolul 1\n{subtiat}\n"
    (r,) = reluari(draft, [norma()])
    assert r.scor >= PRAG


def test_an_ordinary_draft_matches_nothing():
    draft = (
        "Articolul 1\n"
        "(1) Autoritatea contractantă publică anunțul de participare în SEAP.\n"
        "(2) Termenul de depunere a ofertelor este de 30 de zile de la publicarea anunțului.\n"
    )
    assert reluari(draft, [norma()]) == []


def test_a_huge_passage_does_not_match_by_containing_everything():
    """The regression that forced the size guard. Containment is trivially satisfied by anything
    large enough to contain everything, so an entire act scored ~0.8 against every struck norm and
    the first corpus-wide run reported nothing but whole documents.

    The filler has to be *varied*, and that is the non-obvious part: shingles are a set, so
    repeating one sentence sixty times adds no new 5-grams and the fingerprint stays small. The
    guard therefore measures vocabulary diversity rather than character count — which is the right
    thing to measure, and is why a real 200 KB act trips it while sixty copies of one clause
    would not.
    """
    import random

    r = random.Random(11)
    silabe = ["ora", "min", "leg", "pub", "cont", "jud", "fis", "urb", "san", "trans", "vam", "med"]
    umplutura = " ".join("".join(r.choice(silabe) for _ in range(3)) for _ in range(4000))
    assert reluari(f"Articolul 1\n{NORMA} {umplutura}\n", [norma()]) == [], (
        "a long passage matched merely by being long enough to contain the norm"
    )


def test_a_norm_too_short_to_be_distinctive_is_not_compared():
    """«Prezenta lege intră în vigoare» is not a norm anybody re-enacts; it is a sentence every
    act contains. Matching on it would fire on every draft ever written."""
    scurt = norma(norma="Prezenta lege intră în vigoare la 30 de zile.")
    assert reluari("Articolul 1\nPrezenta lege intră în vigoare la 30 de zile.\n", [scurt]) == []
    assert acoperire([scurt])["comparabile"] == 0


def test_one_finding_per_re_enactment_at_the_tightest_unit():
    """An article contains its own alineate, so a norm re-enacted in `art1.alin2` matches `art1`
    too. The narrower unit points at the sentence to change and its score is not diluted."""
    draft = f"Articolul 1\n(1) Dispoziții generale privind aplicarea prezentei legi.\n(2) {NORMA}\n"
    gasite = reluari(draft, [norma()])
    assert len(gasite) == 1
    assert gasite[0].unitate == "art1.alin2"


def test_two_articles_re_enacting_the_same_norm_are_two_findings():
    """Only nesting collapses. Two separate articles doing it are two separate problems."""
    draft = f"Articolul 1\n{NORMA}\nArticolul 2\n{NORMA}\n"
    assert len(reluari(draft, [norma()])) == 2


def test_an_unstructured_paste_is_still_compared():
    """The common case in the UI is one pasted article with no heading at all."""
    (r,) = reluari(NORMA, [norma()])
    assert r.scor >= 0.95
    assert r.unitate == ""


def test_the_answer_says_what_it_was_compared_against():
    """An empty list and an empty comparison set look identical on screen."""
    c = acoperire([norma(), norma(norma="prea scurt")])
    assert c == {"prevederi": 2, "comparabile": 1, "procent": 50}
    text = raport([], c)
    assert "1 din 2" in text
    assert "Nicio formulare" in text


def test_no_norms_shipped_means_no_findings():
    assert reluari(NORMA, []) == []
    assert acoperire([]) == {"prevederi": 0, "comparabile": 0, "procent": 0}


def test_an_article_level_recovery_says_so_on_the_finding():
    """Where the struck text is known only as the containing article, the reader must be told —
    the comparison was against more text than the Court actually struck."""
    (r,) = reluari(f"Articolul 1\n{NORMA}\n", [norma(norma_granularitate="articol")])
    assert "doar la nivel de articol" in r.motiv


def test_diacritics_do_not_decide_the_answer():
    """Romanian legal text is transcribed inconsistently; a re-enactment typed without diacritics
    is still a re-enactment, and `provizii_fts` already indexes this way."""
    fara = NORMA.replace("ă", "a").replace("î", "i").replace("ș", "s").replace("ț", "t")
    (r,) = reluari(f"Articolul 1\n{fara}\n", [norma()])
    assert r.scor >= 0.95


def test_the_metrics_behave_as_the_calibration_assumed():
    """The two halves, stated as a test so the docstring's numbers are checkable."""
    a, b = amprenta(NORMA), amprenta(NORMA)
    assert continut(a, b) == 1.0 and jaccard(a, b) == 1.0
    inglobat = amprenta("Articolul 1. — " + NORMA + " Prezenta lege intră în vigoare.")
    assert continut(inglobat, b) == 1.0, "containment must survive surrounding text"
    assert jaccard(inglobat, b) < 1.0, "jaccard must notice the surrounding text"


def test_units_are_cut_from_the_draft_before_comparing():
    """Provision to provision, never bill to norm: a whole bill contains every norm it touches."""
    u = dict(unitati("Articolul 1\n(1) Unu.\n(2) Doi.\nArticolul 2\nTrei.\n"))
    assert "art1.alin1" in u and "art1.alin2" in u and "art2" in u
    assert u["art1.alin2"].strip() == "Doi."
