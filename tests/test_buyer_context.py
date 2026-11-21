import pytest
from fastapi.testclient import TestClient

from riskengine.api import create_app
from riskengine.buyer_context import buyer_context
from riskengine.buyer_location import example_case, location_for_case


@pytest.mark.parametrize("change", [
    {"jurisdiction": "QLD"}, {"jurisdiction": None}, {"state": "NSW"},
    {"suburb": "Fyshwick"}, {"latitude": -27.666, "longitude": 153.105},
    {"latitude": -35.0, "longitude": None}, {"unit_id": "12"},
    {"label": "12/14 Currie Crescent, Kingston ACT"},
])
def test_conflicting_known_address_blocks_local_sources(change):
    case = {**example_case(), "case_version": 1}
    case["property"].update(change)
    brief = buyer_context(case, None)
    for group in ("planning", "spatial", "crime"):
        assert [r["status"] for r in brief[group]] == ["unknown"]
    assert "issue" in brief["location"]


def test_other_states_and_conflicting_coordinates_without_known_id():
    case = {**example_case(), "case_version": 1}
    prop = case["property"]
    del prop["address_id"]
    prop.update(jurisdiction="Queensland", suburb="Kingston", latitude=-27.666, longitude=153.105)
    assert buyer_context(case, None)["crime"][0]["status"] == "unknown"
    prop["jurisdiction"] = "ACT"
    assert "mapped ACT suburb" in location_for_case(case)["issue"]
    prop.update(suburb="Belconnen", latitude=-35.315392, longitude=149.139011)
    assert "disagree" in location_for_case(case)["issue"]
    prop["suburb"] = "KINGSTON"
    assert location_for_case(case)["suburb"] == "Kingston"


def test_stored_address_id_works_without_guessing_a_location_for_synthetic_cases():
    case = example_case()
    del case["property"]["latitude"], case["property"]["longitude"]
    point = location_for_case(case)
    assert point["latitude"] == pytest.approx(-35.315392, abs=1e-6)
    assert point["source_url"] and point["division_source_url"]
    case["property"] = {"label": "Synthetic garden property", "jurisdiction": "ACT"}
    assert location_for_case(case)["latitude"] is None


def test_assessment_pinning_and_tenant_access(tmp_path):
    secret = "integration-test-key-for-tenant-1"
    other = "integration-test-key-for-tenant-2"
    primary = {"Authorization": "Bearer " + secret}
    secondary = {"Authorization": "Bearer " + other}
    client = TestClient(create_app(tmp_path, {secret: "one", other: "two"}))
    case = example_case()
    url = "/v1/cases/" + case["case_id"]
    assert client.post("/v1/cases", json=case, headers=primary).status_code == 201
    assessment = client.post(url + "/assessments", json={}, headers=primary).json()
    params = {"version": 1, "assessment_id": assessment["assessment_id"]}
    brief = client.get(url + "/buyer-context", params=params, headers=primary).json()
    assert brief["illustrative_finance"] and all(brief[k] for k in ("planning", "spatial", "crime", "finance"))
    assert brief["location"]["address_id"] == 793201
    assert client.get("/v1/assessments/" + assessment["assessment_id"], headers=primary).json() == assessment
    assert client.get(url + "/buyer-context", params=params).status_code == 401
    assert client.get(url + "/buyer-context", params=params, headers=secondary).status_code == 404
    case["finance"]["income_monthly"] = None
    assert client.post("/v1/cases?expected_version=1", json=case, headers=primary).status_code == 201
    assert client.get(url + "/buyer-context", params={**params, "version": 2}, headers=primary).status_code == 409
