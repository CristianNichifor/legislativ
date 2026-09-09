import pytest

from scripts.diferente_versiuni import compara


def doc(text, **kw):
    return dict(
        plx_id="plx-1",
        status="extras",
        text=text,
        url="https://www.cdep.ro/a.pdf",
        preluat_la="2026-09-09",
        sha256="abc",
        **kw,
    )


def test_changes_and_provenance():
    out = compara(
        doc("Preambul vechi\nArt. 1. Unu\nArt. 2. Doi"),
        doc("Preambul nou\nArt. 1. UNU\nArt. 3. Trei"),
    )
    assert out["rezumat"] == {"adaugat": 1, "eliminat": 1, "modificat": 2}
    assert [c["locator"] for c in out["schimbari"]] == ["preambul", "art1", "art2", "art3"]
    assert "SHA-256: abc" in out["markdown"]
    assert "https://www.cdep.ro/a.pdf" in out["markdown"]
    assert "text" not in out["a"]
    c = out["schimbari"][1]
    assert "".join(f["a"] for f in c["fragmente"]) == c["a"]
    assert "".join(f["b"] for f in c["fragmente"]) == c["b"]


def test_whitespace_is_ignored_but_not_case_or_numbers():
    assert not compara(doc("Art. 1. Text  10"), doc("Art. 1. Text\n10"))["schimbari"]
    assert compara(doc("Art. 1. Text 10"), doc("Art. 1. text 11"))["schimbari"]


@pytest.mark.parametrize("text", ["Fără articole", "Art. 1. A\nArt. 1. B"])
def test_uncertain_structure(text):
    out = compara(doc(text), doc("Art. 1. C"))
    assert out["schimbari"][0]["locator"] == "document"
    assert any("incertă" in w for w in out["limitari"])


def test_renumbering_is_not_silently_aligned():
    out = compara(doc("Art. 1. Text identic"), doc("Art. 2. Text identic"))
    assert out["rezumat"] == {"adaugat": 1, "eliminat": 1, "modificat": 0}
    assert any("Renumerotare" in w for w in out["limitari"])


def test_signal_changes():
    a = (
        "Art. 1. Ministerul Mediului emite autorizația de funcționare.\n"
        "Art. 2. În termen de 30 de zile.\n"
        "Art. 3. Articolul 7 din Legea nr. 98/2016 se abrogă."
    )
    b = a.replace("Mediului", "Economiei").replace("30", "60").replace("Articolul 7", "Articolul 8")
    out = compara(doc(a), doc(b))
    assert {s["tip"] for s in out["semnale"]} == {
        "Ținte de amendare",
        "Termene explicite",
        "Autorități recunoscute",
    }


@pytest.mark.parametrize(
    "field,value", [("plx_id", "other"), ("status", "ocr_necesar"), ("text", "x" * 60001)]
)
def test_invalid_versions(field, value):
    a, b = doc("Text"), doc("Alt text")
    b[field] = value
    with pytest.raises(ValueError):
        compara(a, b)


def test_bounded_diff_and_partial_report():
    out = compara(doc("a " * 1100), doc("b " * 1100))
    assert out["schimbari"][0]["detaliu_limitat"]
    a = "\n".join(f"Art. {i}. A" for i in range(101))
    out = compara(doc(a), doc(a.replace(". A", ". B")))
    assert out["rezumat"]["modificat"] == 101
    assert len(out["schimbari"]) == 100 and out["trunchiat"]
    assert "Raport parțial" in out["markdown"]
