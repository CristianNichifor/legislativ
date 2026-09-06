"""Tests for citation anchors — the spans a chip is drawn over.

The property that matters throughout: an anchor's `text` is exactly the slice of the *returned*
text its offsets cut. A chip drawn from offsets that were measured against a different string lands
on the wrong words, and nothing downstream can detect that.
"""

from __future__ import annotations

from scripts.ancore import ancore, ca_dict


def _spans(text):
    curat, gasite = ancore(text)
    return [a.text for a in gasite]


def _tinte(text):
    _, gasite = ancore(text)
    return [[(t.locator, t.act_id) for t in a.tinte] for a in gasite]


def test_offsets_cut_the_text_that_is_returned():
    """The load-bearing invariant. `normalizeaza` collapses whitespace, so offsets taken from it do
    not line up with the string the caller passed in — which is why that string is returned too."""
    brut = "  Se aplică   art. 7 lit. a)-c)\n\n\n din prezenta lege.  "
    curat, gasite = ancore(brut)
    assert gasite
    for a in gasite:
        assert curat[a.start : a.end] == a.text
    assert brut[gasite[0].start : gasite[0].end] != gasite[0].text  # and why it has to be returned


def test_a_range_is_one_chip_over_every_member():
    """`extinde_serii` reads the middle and the last member off the same `c)` — that is the only
    place the text names them — so drawn literally they are two chips on the same characters."""
    assert _spans("Se aplică art. 7 lit. a)-c) din prezenta lege.") == ["art. 7 lit. a)-c)"]
    assert _tinte("Se aplică art. 7 lit. a)-c) din prezenta lege.") == [
        [("art7.lita", None), ("art7.litb", None), ("art7.litc", None)]
    ]


def test_an_enumeration_stays_one_chip_per_member():
    """Each member is written out, so each is worth pointing at on its own: hovering `8`
    highlights `art. 8` and nothing else."""
    assert _spans("Se abrogă art. 7, 8 și 9.") == ["art. 7", "8", "9"]
    assert _tinte("Se abrogă art. 7, 8 și 9.") == [
        [("art7", None)],
        [("art8", None)],
        [("art9", None)],
    ]


def test_anchors_never_overlap():
    text = (
        "art. 5 alin. (1)-(3) din Legea nr. 98/2016 și art. 7 lit. a)-c) se aplică art. 7, 8 și 9."
    )
    _, gasite = ancore(text)
    for precedent, urmator in zip(gasite, gasite[1:], strict=False):
        assert precedent.end <= urmator.start


def test_an_act_without_a_position_is_not_anchored():
    """A chip over `Legea nr. 98/2016` would promise a jump to a provision the citation never
    named. Nothing to highlight, so nothing to draw."""
    assert _spans("Se aplică Legea nr. 98/2016 în continuare.") == []


def test_a_text_with_no_citation_yields_no_anchors():
    curat, gasite = ancore("Prezenta lege intră în vigoare la 30 de zile.")
    assert gasite == [] and curat


def test_the_genitive_form_anchors_both_halves_separately():
    """`lit. a)-c) ale art. 7` — the letters are one chip, the article another. They are separate
    words on screen and the reader points at them separately."""
    assert _spans("lit. a)-c) ale art. 7 se modifică") == ["lit. a)-c)", "art. 7"]


def test_a_bound_act_travels_with_the_target():
    """A chip has to know whether it points inside this act or at another one — the first is a
    scroll, the second is a link somewhere else."""
    (tinte,) = _tinte("Se modifică art. 5 din Legea nr. 98/2016.")
    assert tinte == [("art5", "lege-98-2016")]


def test_a_repeated_citation_is_one_target_not_two():
    _, gasite = ancore("art. 7 lit. a)-c), respectiv lit. a)-c) ale art. 7")
    for a in gasite:
        assert len(a.tinte) == len({(t.locator, t.act_id) for t in a.tinte})


def test_the_wire_form_is_plain_types():
    """The browser build ships this through Pyodide, so it has to survive a JSON round trip."""
    import json

    d = ca_dict("art. 7 lit. a)-c) din Legea nr. 98/2016")
    assert json.loads(json.dumps(d)) == d
    assert d["text"] and d["ancore"][0]["tinte"][0]["act_id"] == "lege-98-2016"


def test_a_provision_does_not_anchor_its_own_heading():
    """A provision's text opens with its own heading, which is written exactly like a citation.
    Left in, every row on screen carries a chip on its first two words pointing at itself."""
    _, gasite = ancore("Articolul 154 Prezentul articol se aplică.", propriu="art154")
    assert gasite == []


def test_a_self_reference_next_to_a_real_one_keeps_its_chip():
    """Dropped only when every target is the provision itself — the half that points elsewhere is
    still worth following."""
    _, gasite = ancore("Articolul 154 se aplică împreună cu art. 187.", propriu="art154")
    assert [a.text for a in gasite] == ["art. 187"]


def test_the_own_heading_of_another_provision_is_kept():
    assert _spans("Articolul 154 se modifică") == ["Articolul 154"]
