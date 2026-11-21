import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from pyproj import Transformer
from shapely.geometry import Point, shape

from riskengine import preoffer_locations as locations
from riskengine.engine import evaluate_case
from riskengine.paths import project_root


def case(address_id):
    return {"case_id": "preoffer-location-check", "property_id": f"act-address-{address_id}",
            "property": locations.retained_property(address_id), "as_of": "2026-11-21T23:59:59Z"}


def test_offline_exact_units_and_live_fallback(monkeypatch):
    calls = []

    def other(street, suburb):
        calls.append((street, suburb))
        return {"matches": [], "truncated": True}

    monkeypatch.setattr(locations.buyer_location, "lookup_addresses", other)
    for street, suburb, expected in (("11/14 Currie Cres", "Kingston", 793201),
                                    ("Unit 21, 28 Ringrose Crescent", "ISAACS", 165259)):
        response = locations.lookup_addresses(street, suburb)
        hit, = response["matches"]
        assert hit["address_id"] == expected and not response["truncated"]
        assert (hit["property_type"], hit["bedrooms"]) == ("townhouse", 3)
    assert not calls
    for street, suburb in (("28 Ringrose Crescent", "Isaacs"), ("22/28 Ringrose Cres", "Isaacs"),
                          ("21/28 Ringrose Crescent", "Kingston")):
        assert locations.lookup_addresses(street, suburb)["truncated"]
    assert len(calls) == 3
    assert {x["address_id"] for x in locations.examples()["matches"]} == {793201, 165259}


def test_dated_official_point_queries_have_different_results_and_register_schemes():
    pack = json.loads((project_root() / "config/preoffer_locations.json").read_bytes())
    to_mga = Transformer.from_crs(4326, 7855, always_xy=True)
    for aid, zone, count in ((793201, "RZ5", 0), (165259, "RZ2", 5)):
        subject = case(aid)
        prop = subject["property"]
        home = pack["homes"][str(aid)]
        for snap in home.values():
            assert hashlib.sha256(snap["response_text"].encode()).hexdigest() == snap["response_sha256"]
            assert urlsplit(snap["query_url"]).hostname == "services1.arcgis.com"
        mapped, bush = locations.retained_location_evidence(subject)
        assert mapped["zone_code"] == zone
        assert bush["nearby_designation"] is bool(count)
        assert (bush["count_within_200m"], bush["count_within_500m"]) == (0, count)
        for ref in mapped["public_sources"] + bush["public_sources"]:
            p = parse_qs(urlsplit(ref["query_url"]).query)
            assert ref["source_id"] in (set(mapped["source_ids"]) | set(bush["source_ids"]))
            assert ref["licence_url"] == "https://creativecommons.org/licenses/by/4.0/"
            point = tuple(map(float, p["geometry"][0].split(",")))
            if p["inSR"] == ["4326"]:
                assert point == (prop["longitude"], prop["latitude"])
            else:
                assert p["inSR"] == ["7855"] and shape(prop["parcel_geometry"]).contains(Point(*point))
        if aid == 793201:
            assert shape(prop["parcel_geometry"]).distance(
                Point(*to_mga.transform(prop["longitude"], prop["latitude"]))) == pytest.approx(14.25, abs=0.1)
            assert "14 m" in mapped["detail"]
        rows = locations.public_evidence(subject)
        assert all({"act_addresses", "act_blocks", "act_unit", "act_boundary", r["source_id"]}
                   <= set(r["source_ids"]) for r in rows)
        result = evaluate_case(subject, rows)
        check, = (r for r in result["check_results"] if r["check_id"] == "S002")
        assert check["complete"]
        if aid == 793201:
            assert {"S011", "S030", "S034", "S038", "S041", "S048", "S049", "S053"} <= {r["check_id"] for r in rows}


@pytest.mark.parametrize("change", [{"unit_id": "11"}, {"state": "NSW"}, {"suburb": "Kingston"},
                                  {"latitude": 0}, {"block_key": 12170240009},
                                  {"property_type": "house"}, {"ambiguous": True},
                                  {"identity_confirmed": False}, {"label": "22/28 Ringrose Crescent, Isaacs ACT"}])
def test_conflicting_or_unconfirmed_selection_has_no_retained_rows(change):
    subject = case(165259)
    subject["property"].update(change)
    assert locations.retained_location_evidence(subject) == locations.public_evidence(subject) == []


def test_pre_capture_and_foreign_property_have_no_retained_rows():
    subject = case(793201)
    for change in ({"as_of": "2026-11-21T11:00:00Z"}, {"property_id": "act-address-165259"}):
        assert locations.retained_location_evidence({**subject, **change}) == []
        assert locations.public_evidence({**subject, **change}) == []
    assert locations.retained_property(9999) is None
