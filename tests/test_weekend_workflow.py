"""Regression checks for the buyer worksheet through the ordinary local API."""
from uuid import uuid4

from fastapi.testclient import TestClient

from riskengine.api import create_app
from riskengine.desktop import LocalDashboard

TEST_KEY = "disposable-weekend-workflow-test"


def client_for(tmp_path):
    return TestClient(create_app(tmp_path, {TEST_KEY: "demo", TEST_KEY + "-other": "other"}),
                      headers={"Authorization": f"Bearer {TEST_KEY}"})


def test_five_offline_examples_and_signed_sensitivity(tmp_path):
    client = client_for(tmp_path)
    rows = client.get("/v1/weekend/examples").json()["examples"]
    assert len(rows) == 5 and all("expected" not in row for row in rows)
    assert client.get("/weekend").status_code == 200
    assert "/weekend" in client.get("/static/offer-form.html").text
    statuses = []
    for row in rows:
        study = client.post("/v1/weekend/preview", json={"example_id": row["id"]}).json()
        model = study["result"]
        statuses.append(model["verdict"])
        assert set(model["storms"]) == set("ABC")
        assert set(model["vetoes"]) == {"V1", "V2", "V3", "V4"}
        assert study["bid_policy_hash"].startswith("sha256:")
    assert statuses == ["green", "amber", "red", "red", "unresolved"]
    edited = client.post("/v1/weekend/preview", json={"example_id": "kambah-repairs",
                         "changes": {"cash_before_settlement": 1000}}).json()
    assert float(edited["result"]["baseline"]["cash_after_settlement"]) < 0
    out_of_range = client.post("/v1/weekend/preview", json={"example_id": rows[0]["id"],
                               "changes": {"purchase_price": 1}}).json()
    assert out_of_range["price_issue"] and out_of_range["profile"]["deposit"] is None
    blank = client.post("/v1/weekend/preview", json={"example_id": rows[0]["id"],
                        "changes": {"purchase_price": None}}).json()
    assert blank["result"]["baseline"]["principal"] is None
    assert client.get("/v1/weekend/history").json() == {"assessments": []}


def test_saved_versions_replay_export_and_source_note_scope(tmp_path):
    client = client_for(tmp_path)
    example_id = "braddon-downsizers"
    body = {"example_id": example_id, "worksheet": str(uuid4()), "expected_version": 0}
    original = client.post("/v1/weekend/assessments", json=body).json()
    ident = original["assessment_id"]
    url = "/v1/assessments/" + ident
    snapshot = client.get(url).json()
    assert snapshot["case_version"] == 1 and snapshot["buyer_summary"]["household_decision"] == "unresolved"
    assert client.post("/v1/weekend/assessments", json=body).json()["assessment_id"] == ident
    body.update(based_on=ident, expected_version=1, changes={"structural_clear": True},
                source_notes={"structural_clear": "Fictional engineer report dated 21 Nov"})
    updated = client.post("/v1/weekend/assessments", json=body).json()
    assert updated["case_version"] == 2 and updated["weekend"]["result"]["verdict"] == "green"
    assert client.get(url).json() == snapshot
    html = client.get(url + "/report").text
    assert "Unresolved household result" in html and "A forced sale in two years" in html
    assert client.post("/v1/weekend/assessments/" + ident + "/replay").json()["exact_match"] is True
    assert len(client.get("/v1/weekend/history").json()["assessments"]) == 2
    other = {"Authorization": "Bearer " + TEST_KEY + "-other"}
    assert client.post("/v1/weekend/preview", headers=other, json={"example_id": example_id, "based_on": ident}).status_code == 404
    assert client.post("/v1/weekend/assessments/" + ident + "/replay", headers=other).status_code == 404


def test_shared_sample_disallows_personal_evidence(tmp_path, monkeypatch):
    directory = tmp_path / "runtime/buyer-preview"
    monkeypatch.setenv("RISK_PROJECT_ROOT", str(tmp_path))
    dashboard = LocalDashboard("preview", "127.0.0.1", 8141, "demo", directory)
    app = create_app(directory, {TEST_KEY: "demo"}, dashboard=dashboard)
    from riskengine import weekend_routes
    monkeypatch.setattr(weekend_routes, "examples", lambda: [{"id": "sample"}])
    client = TestClient(app, headers={"Authorization": "Bearer " + TEST_KEY})
    private = {"example_id": "sample", "changes": {"structural_clear": True},
               "source_notes": {"structural_clear": "Private household evidence"}}
    assert client.post("/v1/weekend/preview", json=private).status_code == 403
    assert client.get("/v1/weekend/history").json() == {"assessments": []}
