from fastapi.testclient import TestClient

from riskengine.api import create_app
from riskengine.buyer_location import example_case


def test_decision_brief_comes_from_saved_assessment(tmp_path, monkeypatch):
    key = "purchase-decision-preview-test-only"
    headers = {"Authorization": "Bearer " + key}
    with TestClient(create_app(tmp_path, {key: "one"})) as client:
        case = example_case()
        assert client.post("/v1/cases", json=case, headers=headers).status_code == 201
        base = "/v1/cases/" + case["case_id"]
        response = client.post(base + "/assessments", headers=headers)
        assert response.status_code == 201, response.text
        result = response.json()

        def unexpected_recalculation(*args):
            raise AssertionError("A saved decision must render its captured source context")

        monkeypatch.setattr("riskengine.buyer_context.buyer_context", unexpected_recalculation)
        params = {"version": 1, "assessment_id": result["assessment_id"]}
        brief = client.get(base + "/buyer-context", params=params, headers=headers)
        assert brief.status_code == 200, brief.text
        assert brief.json() == {**result["decision_evidence"], "assessment_id": result["assessment_id"]}
