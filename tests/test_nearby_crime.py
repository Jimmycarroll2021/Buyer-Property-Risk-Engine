from datetime import date

import pytest

from riskengine.nearby_crime import crime_signals


def test_kingston_uses_reported_offences_and_matching_population():
    counts, rate = crime_signals("  Kingston ", date(2026, 11, 21))
    assert counts["as_of"] == rate["as_of"] == "2025-06-30"
    assert counts["source_url"].endswith("/2egm-dieb")
    assert "6 dwelling burglaries" in counts["detail"]
    assert "compared with 12" in counts["detail"]
    assert "20 and 29" in counts["detail"]
    assert "0.8 dwelling burglaries and 2.7 motor vehicle thefts per 1,000 residents" in rate["detail"]
    assert "7,465 and 7,472" in rate["detail"]
    assert rate["source_url"].endswith("/regional-population/2024-25")


def test_publication_time_limits_both_sources_independently():
    unavailable, = crime_signals("Kingston", "2025-07-08T10:26:29+10:00")
    assert unavailable["status"] == "unavailable"
    assert unavailable["as_of"] is None
    counts, rate = crime_signals("Kingston", "2025-07-08T10:26:30+10:00")
    assert counts["status"] == "available"
    assert rate["status"] == "unavailable"
    assert "7,465" not in rate["detail"]
    assert crime_signals("Kingston", "2026-03-31T11:29:59+11:00")[1]["status"] == "unavailable"
    assert crime_signals("Kingston", "2026-03-31T11:30:00+11:00")[1]["status"] == "available"


@pytest.mark.parametrize("suburb", ["Canberra", "Queanbeyan", "Kingston Beach", "", "Total"])
def test_unmatched_place_does_not_inherit_regional_totals(suburb):
    signal, = crime_signals(suburb, "2026-11-21")
    assert signal["status"] == "unavailable"
    assert signal["as_of"] is None


def test_other_suburbs_and_missing_or_zero_denominator():
    assert crime_signals("Braddon", "2026-11-21")[1]["status"] == "available"
    counts, rate = crime_signals("O\u2019Connor", "2026-11-21")
    assert counts["status"] == "available"
    assert rate["status"] == "unavailable"
    assert "matching suburb boundaries" in rate["detail"]
    counts, rate = crime_signals("Russell", "2026-11-21")
    assert counts["status"] == "available"
    assert rate["status"] == "unavailable"
    assert "estimated resident population was zero" in rate["detail"]


def test_ambiguous_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        crime_signals("Kingston", "2026-11-21T01:00:00")
