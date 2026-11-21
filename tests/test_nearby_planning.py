from datetime import date

import pytest

from riskengine.nearby_planning import planning_signals


CURRIE_CRESCENT = (-35.315392351357914, 149.13901106665423)
CITY_WEST = (-35.2823, 149.1245)
SNAPSHOT = date(2026, 11, 21)


def test_kingston_address_has_specific_planning_and_proposed_rail():
    rows = planning_signals(*CURRIE_CRESCENT, SNAPSHOT)
    da = next(row for row in rows if "202645687" in row["title"])
    assert "151 homes" in da["title"]
    assert 875 < da["distance_m"] < 895
    assert "Dominion Circuit and Franklin Street" in da["detail"]
    assert da["status"] == "On notification"
    assert da["source_url"].endswith("?da-number=202645687")
    assert da["as_of"] == "2026-11-21"
    school = [row for row in rows if "202645688" in row["title"]]
    assert len(school) == 1
    assert school[0]["distance_m"] == pytest.approx(231, abs=2)
    rail = [row for row in rows if "light rail" in row["title"].lower()]
    assert len(rail) == 1
    assert rail[0]["title"].endswith("Sydney Avenue")
    assert rail[0]["status"] == "Environmental assessment"
    assert rail[0]["distance_m"] == 1100
    assert "reference point" in rail[0]["detail"]
    assert all(row["coverage"] and row["attribution"] for row in rows)


def test_parcel_distance_is_zero_on_the_application_land():
    # Coordinate on the Canberra Hospital staff parking application's block.
    # Use an official polygon vertex to check that the calculation uses its
    # extent, including the boundary, rather than the centre of the block.
    import json
    from riskengine.paths import project_root

    path = project_root() / "config/nearby_planning_data/application_blocks.geojson"
    feature = next(f for f in json.loads(path.read_bytes())["features"]
                   if f["properties"]["number"] == "202645413")
    lon, lat = feature["geometry"]["coordinates"][0][0]
    row = next(row for row in planning_signals(lat, lon, SNAPSHOT) if "202645413" in row["title"])
    assert row["distance_m"] == 0


def test_rail_states_and_distances_change_across_the_city():
    rows = planning_signals(*CITY_WEST, SNAPSHOT)
    rail = next(row for row in rows if "Stage 2A" in row["title"])
    assert rail["title"].endswith("Edinburgh Avenue")
    assert rail["status"] == "Under construction"
    assert rail["distance_m"] == pytest.approx(82, abs=2)
    assert rail["as_of"] == "2026-11-19"
    woden = planning_signals(-35.345, 149.088, SNAPSHOT)
    assert any("Proposed light rail Stage 2B | Woden Interchange" == row["title"] for row in woden)
    assert not any("Stage 2A" in row["title"] for row in woden)


def test_cutoff_applies_to_status_and_location_evidence():
    assert planning_signals(*CURRIE_CRESCENT, "2026-10-01") == []
    assert planning_signals(*CURRIE_CRESCENT, "2026-11-16") == []
    rows = planning_signals(*CURRIE_CRESCENT, "2026-11-20")
    assert [row["status"] for row in rows] == ["Environmental assessment"]
    assert not any("Stage 2A" in row["title"] for row in planning_signals(*CITY_WEST, "2026-11-18"))
    later = planning_signals(*CITY_WEST, "2027-01-15")
    assert all(row["as_of"] <= "2026-11-21" for row in later)


@pytest.mark.parametrize("lat,lon,as_of", [
    (-35.47, 149.1, SNAPSHOT), (-33.86, 151.21, SNAPSHOT),
    (float("nan"), 149.13, SNAPSHOT), (None, 149.13, SNAPSHOT),
    (149.13, -35.31, SNAPSHOT), (*CURRIE_CRESCENT, "bad date"),
])
def test_no_matching_evidence(lat, lon, as_of):
    assert planning_signals(lat, lon, as_of) == []
