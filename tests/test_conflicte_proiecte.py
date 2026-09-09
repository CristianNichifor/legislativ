import pytest

from scripts.conflicte_proiecte import compara, operatii

TINTA = {"lege-98-2016"}
HEADER = "Legea nr. 98/2016 se modifică și se completează după cum urmează:\n"


def _ops(text):
    return operatii(HEADER + text, TINTA)[0]


def test_repeal_against_modification_including_child_not_sibling():
    repeal = _ops("1. Articolul 7 se abrogă.")
    modify = _ops(
        '1. La articolul 7, alineatul (2) se modifică și va avea următorul cuprins: "Nou."'
    )
    assert compara(repeal, modify)[0][0]["tip"] == "abrogare_modificare"
    assert compara(modify, repeal)[0]
    assert not compara(_ops("1. Articolul 70 se abrogă."), modify)[0]
    assert not compara(_ops("1. Articolul 8 se abrogă."), modify)[0]


def test_replacements_need_different_quoted_payloads():
    def mod(text):
        return _ops(f'1. Articolul 7 se modifică și va avea următorul cuprins: "{text}"')

    assert compara(mod("Text nou."), mod("Alt text."))[0][0]["tip"] == "inlocuiri_diferite"
    assert not compara(mod("TEXT NOU."), mod("Text nou."))[0]
    assert not compara(mod("Text nou."), _ops("1. Articolul 7 se modifică."))[0]


@pytest.mark.parametrize(
    "unitate,locator",
    [
        ('1. După articolul 7 se introduce articolul 7^1 cu următorul cuprins: "Text."', "art7^1"),
        (
            "1. La articolul 7, după alineatul (2) se introduce alineatul (3) "
            + 'cu următorul cuprins: "Text."',
            "art7.alin3",
        ),
    ],
)
def test_insertions_compare_new_number_not_anchor(unitate, locator):
    ops = _ops(unitate)
    assert ops[0]["locator"] == locator
    assert compara(ops, ops)[0][0]["tip"] == "numerotare_dublata"


def test_missing_targets_and_other_acts_are_not_inferred():
    assert not operatii("Articolul 7 se abrogă.", TINTA)[0]
    assert not operatii(HEADER.replace("98/2016", "99/2016") + "1. Articolul 7 se abrogă.", TINTA)[
        0
    ]


def test_candidate_and_operation_limits_report_partial_results():
    a = _ops("1. Articolul 7 se abrogă.\n2. Articolul 8 se abrogă.")
    b = _ops("1. Articolul 7 se modifică.\n2. Articolul 8 se modifică.")
    pairs, partial = compara(a, b, limita=1)
    assert len(pairs) == 1 and partial
    text = HEADER + "\n".join(f"{i}. Articolul {i} se abrogă." for i in range(1, 202))
    ops, partial = operatii(text, TINTA)
    assert len(ops) == 200 and partial
