import pytest

from scripts import constatari_manuale as manual


def test_manual_finding_taxonomy_is_stable_and_user_facing():
    rows = manual.tipuri()

    assert [row["cheie"] for row in rows] == [
        "lacuna",
        "loophole",
        "contradictie",
        "necorelare",
        "risc_ue",
        "constitutionalitate",
    ]
    assert rows[0]["eticheta"] == "Lacună"
    assert rows[-1]["eticheta"] == "Constituționalitate"
    assert "ready_for_review" in manual.STARI


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lacuna", "lacuna"),
        ("risc-ue", "risc_ue"),
        (" constitutionalitate ", "constitutionalitate"),
    ],
)
def test_manual_finding_type_normalization(raw, expected):
    assert manual.normalize_tip(raw) == expected


@pytest.mark.parametrize("raw", ["", "gap", "risc ue", "ccr"])
def test_manual_finding_type_rejects_unknown_labels(raw):
    with pytest.raises(ValueError, match="Tip"):
        manual.normalize_tip(raw)


def test_manual_finding_status_normalization():
    assert manual.normalize_stare(None) == "draft"
    assert manual.normalize_stare("ready-for-review") == "ready_for_review"
    with pytest.raises(ValueError, match="Stare"):
        manual.normalize_stare("accepted")
