from html import unescape

import pytest
from fastapi.testclient import TestClient

from riskengine import pipeline
from riskengine.api import create_app
from riskengine.storage import Forbidden


KEY = "local-test-key-for-preoffer-assessments"
HEADERS = {"Authorization": f"Bearer {KEY}"}


def start_case(match):
    return {"property_id": f"act-address-{match['address_id']}", "as_of": "2026-11-22T00:00:00Z",
            "property": {**match, "jurisdiction": "ACT", "identity_confirmed": True},
            "preoffer": {"offer_price": "850000", "price_basis": "proposed_offer", "intended_use": "owner_occupier"}}


def test_address_price_cases_reports_replay_and_policy(tmp_path, monkeypatch):
    app = create_app(tmp_path, {KEY: "buyer"})
    with TestClient(app, headers=HEADERS) as client:
        matches = client.get("/v1/locations/examples").json()["matches"]
        assert {row["address_id"] for row in matches} == {793201, 165259}
        assessments = []
        for point in matches:
            street = point["label"].split(",")[0]
            search = client.get("/v1/locations/search", params={"street": street, "suburb": point["suburb"]})
            assert search.json()["matches"] == [point]
            saved = client.post("/v1/cases?expected_version=0", json=start_case(point))
            assert saved.status_code == 201, saved.text
            case = saved.json()
            url = f"/v1/cases/{case['case_id']}/assessments"
            response = client.post(url, params={"expected_version": case["case_version"]})
            assert response.status_code == 201, response.text
            assessment = response.json()
            assessments.append(assessment)
            brief = assessment["preoffer_brief"]
            assert brief["assessment_id"] == assessment["assessment_id"]
            assert len(brief["top_three"]) == 3
            assert {c["check_id"] for c in assessment["check_results"]} == {f"S{n:03}" for n in range(1, 66)}
            assert brief["costs"]["price_evidence"]["status"] == "insufficient_evidence"
            assert next(c for c in assessment["check_results"] if c["check_id"] == "S002")["complete"]
            assert assessment["preoffer_capture"]["home"]["property"]["address_id"] == point["address_id"]
            assert all(row["monthly_repayment"] is None for row in brief["costs"]["offer_comparison"])
            resource = "/v1/assessments/" + assessment["assessment_id"]
            assert client.get(resource).json() == assessment
            html = unescape(client.get(resource + "/report").text)
            assert all(item["title"] in html and item["action"] in html for item in brief["top_three"])
            assert client.post(url + "?expected_version=2").status_code == 409
        assert assessments[0]["preoffer_brief"]["top_three"] != assessments[1]["preoffer_brief"]["top_three"]
        monkeypatch.setattr(pipeline, "sales_inputs", lambda *_: pytest.fail("Replay read the current sales capture"))
        monkeypatch.setattr(pipeline, "capture_home", lambda *_: pytest.fail("Replay read the current register"))
        for saved in assessments:
            assert pipeline.replay_assessment(app.state.store, "buyer", saved["assessment_id"]) == (saved, saved)
        app.state.store.set_source_policy("buyer", "act_unit", {"display_derived": False})
        for saved in assessments:
            assert client.get("/v1/assessments/" + saved["assessment_id"]).status_code == 403
            with pytest.raises(Forbidden):
                pipeline.replay_assessment(app.state.store, "buyer", saved["assessment_id"])


def test_private_sale_permissions_and_new_case_version(tmp_path):
    app = create_app(tmp_path, {KEY: "buyer", KEY + "-other": "other"})
    with TestClient(app, headers=HEADERS) as client:
        point = client.get("/v1/locations/examples").json()["matches"][0]
        case = start_case(point)
        investor = {**case, "preoffer": {**case["preoffer"], "intended_use": "investment"}}
        assert client.post("/v1/cases", json=investor).status_code == 422
        sale = {"address": "99 Fixture Street", "suburb": point["suburb"], "jurisdiction": "ACT",
                "property_type": point["property_type"], "settled_on": "2026-10-01", "known_at": "2026-10-10",
                "price": 800000, "source_ref": "local test receipt", "source_id": "private-transfer-test",
                "status": "settled", "permission_confirmed": False}
        case["preoffer"]["comparable_sales"] = [sale]
        assert client.post("/v1/cases", json=case).status_code == 422
        sale["permission_confirmed"] = True
        case = client.post("/v1/cases", json=case).json()
        url = "/v1/cases/" + case["case_id"]
        first = client.post(url + "/assessments").json()
        price = first["preoffer_brief"]["costs"]["price_evidence"]
        assert price["comparables"][0]["difference_from_offer"] == "50000.00"
        case["preoffer"]["offer_price"] = "810000"
        assert client.post("/v1/cases?expected_version=1", json=case).json()["case_version"] == 2
        second = client.post(url + "/assessments?expected_version=2").json()
        assert second["assessment_id"] != first["assessment_id"]
        assert second["preoffer_brief"]["costs"]["price_evidence"]["comparables"][0]["difference_from_offer"] == "10000.00"
        assert client.get(url, headers={"Authorization": f"Bearer {KEY}-other"}).status_code == 404
        app.state.store.set_source_policy("buyer", "private-transfer-test", {"display_raw": False})
        assert client.get("/v1/assessments/" + first["assessment_id"]).status_code == 403
        assert client.get(url).json()["preoffer"]["comparable_sales"] == []
        third = client.post(url + "/assessments").json()
        assert not third["preoffer_brief"]["costs"]["price_evidence"]["comparables"]
        assert "99 Fixture Street" not in str(third)
        assert pipeline.replay_assessment(app.state.store, "buyer", third["assessment_id"]) == (third, third)
