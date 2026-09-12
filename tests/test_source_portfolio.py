import pytest

from scripts import source_portfolio


def family_keys(out):
    return {item["key"] for item in out["families"]}


def event_keys(out):
    return {item["key"] for item in out["tracker_events"]}


def test_portfolio_contract_names_priority_sources_and_monitor_policy():
    out = source_portfolio.portfolio()

    assert out["contract"] == "source-portfolio-v1"
    assert family_keys(out) >= {
        "legislatie_ro",
        "camera",
        "senat",
        "consultare_econsultare",
        "ue_cellar",
        "ccr",
        "avize",
        "monitorul_oficial_pi",
        "monitorul_oficial_other_parts",
        "monitorul_oficial_local",
    }
    assert out["monitorul_oficial_policy"] == {
        "part_i": "ingest",
        "part_ii": "metadata_or_selective",
        "parts_iii_vii": "do_not_full_ingest_by_default",
        "local": "registry_first_opt_in_packs",
    }


def test_portfolio_contract_names_legislative_tracker_events():
    out = source_portfolio.portfolio()

    assert event_keys(out) >= {
        "public_consultation_opened",
        "public_consultation_closed",
        "committee_assignment",
        "opinion_received",
        "report_filed",
        "plenary_agenda",
        "vote_recorded",
        "published_in_monitor",
    }
    vote = next(item for item in out["tracker_events"] if item["key"] == "vote_recorded")
    assert vote["source_family"] == "camera/senat"
    assert vote["fields"] == [
        "chamber",
        "vote_date",
        "result",
        "for",
        "against",
        "abstain",
        "nominal_url",
    ]


@pytest.mark.parametrize(
    ("profile", "gb_min", "gb_max", "usd_min", "usd_max"),
    [
        ("v1", 55, 310, 0.68, 4.5),
        ("serious", 120, 630, 1.65, 9.3),
        ("everything", 320, 3630, 4.65, 54.3),
    ],
)
def test_storage_estimates_are_bounded_profiles(profile, gb_min, gb_max, usd_min, usd_max):
    out = source_portfolio.estimate_storage(profile)

    assert out["contract"] == "source-storage-estimate-v1"
    assert out["profile"] == profile
    assert out["gb_min"] == gb_min
    assert out["gb_max"] == gb_max
    assert out["r2_standard_usd_month_min"] == usd_min
    assert out["r2_standard_usd_month_max"] == usd_max
    assert (
        "operation costs depend on object count/read pattern and are not included"
        in out["assumptions"]
    )


def test_storage_estimate_rejects_unknown_profile():
    with pytest.raises(ValueError, match="Profil necunoscut"):
        source_portfolio.estimate_storage("bulk")
