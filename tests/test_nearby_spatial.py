import json
from datetime import date, datetime, timezone
from shutil import copyfile

import pytest

from riskengine.nearby_spatial import spatial_signals
from riskengine.paths import project_root


DAY = date(2026, 11, 21)
CURRIE = (-35.315392351357914, 149.13901106665423)


@pytest.mark.parametrize(("latitude", "longitude", "code"), [
    (*CURRIE, "RZ5"),
    (-35.314, 149.141, "CZ2"),
    (-35.316, 149.141, "CZ1"),
])
def test_offline_point_matches_act_government_point_query(latitude, longitude, code):
    result, = spatial_signals(latitude, longitude, DAY)
    assert result["status"] == "mapped"
    assert [zone["code"] for zone in result["zones"]] == [code]
    assert result["as_of"] == "2026-11-05T18:03:28Z"
    assert result["retrieved_at"].startswith("2026-11-21")
    assert "Australian Capital Territory" in result["attribution"]
    assert "creativecommons.org/licenses/by/4.0/" in result["licence_url"]


def test_shared_polygon_vertex_reports_all_intersecting_zones():
    result, = spatial_signals(-35.3198796, 149.13493855, DAY)
    assert result["status"] == "multiple_zones"
    assert {"DES", "TSZ1"} <= {row["code"] for row in result["zones"]}


def test_gap_and_outside_coverage_are_explicit():
    gap, = spatial_signals(-35.31989628506559, 149.1345369878046, DAY)
    outside, = spatial_signals(-35.28, 149.13, DAY)
    assert gap["status"] == "unknown"
    assert "No gazetted zone" in gap["detail"]
    assert outside["status"] == "outside_coverage"
    assert "zones" not in gap and "zones" not in outside


@pytest.mark.parametrize("as_of", ["2021-01-01", "2026-11-06T04:00:00+11:00"])
def test_pre_version_assessments_exclude_later_layer(as_of):
    result, = spatial_signals(*CURRIE, as_of)
    assert result["status"] == "unknown"
    assert result["as_of"] is None


def test_timezone_aware_datetime_selects_version_and_later_date_does_not_refresh_it():
    result, = spatial_signals(*CURRIE, datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert result["status"] == "mapped"
    assert result["as_of"].startswith("2026-11-05")
    assert "snapshot retrieved 2026-11-21" in result["detail"]


@pytest.mark.parametrize(("lat", "lon", "as_of"), [
    (float("nan"), 149, DAY),
    (True, 149, DAY),
    (-35, 181, DAY),
    (-35, 149, "unknown"),
    (-35, 149, datetime(2026, 11, 21)),
])
def test_invalid_input_fails_closed(lat, lon, as_of):
    result, = spatial_signals(lat, lon, as_of)
    assert result["status"] == "unknown"
    assert "zones" not in result


def test_corrupt_data_cannot_produce_zoning_result(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    copyfile(project_root() / "config/nearby_spatial_metadata.json", config / "nearby_spatial_metadata.json")
    (config / "nearby_spatial_zones.json").write_text(json.dumps({"features": []}))
    monkeypatch.setenv("RISK_PROJECT_ROOT", str(tmp_path))
    result, = spatial_signals(*CURRIE, DAY)
    assert result["status"] == "unknown"
    assert "could not be verified" in result["detail"]
