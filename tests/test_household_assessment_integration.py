import json
from pathlib import Path

from fastapi.testclient import TestClient

from riskengine.api import create_app
from riskengine.desktop import LocalDashboard
from riskengine.pipeline import import_observations, replay_assessment
from riskengine.storage import Store


ROOT = Path(__file__).resolve().parents[1]
KEY = "disposable-integration-token-for-homebuying"
AUTH = {"Authorization": f"Bearer {KEY}"}


def scenario():
    case = json.loads((ROOT / "examples/case.json").read_bytes())
    case["preoffer"] = {"offer_price": "900000", "lost_income_monthly": "5000",
                        "loss_months": 4, "repair_cost": "20000", "repair_month": 2}
    return case


def test_private_assessment_and_read_only_sensitivity(tmp_path):
    app = create_app(tmp_path, {KEY: "demo", KEY + "-other": "other"})
    with TestClient(app, headers=AUTH) as client:
        case = scenario()
        case.pop("demonstration")
        case["preoffer"]["underwriting"] = {"inspection_leads": {
            "source_id": "private-inspection", "source_ref": "Owner inspection receipt",
            "known_at": "2026-11-20", "permission_confirmed": True, "kind": "visual",
            "observation": "Ceiling stain by the study window",
        }}
        case["buyer_protection"] = {"career": {"goal_monthly": "700", "lost_income_monthly": "3500", "duration_months": 4}}
        assert client.post("/v1/cases", json=case).status_code == 201
        path = "/v1/cases/" + case["case_id"]
        saved = client.post(path + "/assessments").json()
        assert list(saved)[0] == "buyer_summary"
        brief = saved["preoffer_brief"]
        assert len(brief["survival"]["combined"]["timeline"]) == 13
        assert not brief["protection"]["illustrative"]
        assert "Ceiling stain by the study window" in str(brief["underwriting"])
        target = "/v1/assessments/" + saved["assessment_id"]
        assert client.get(target).json() == saved
        html = client.get(target + "/report").text
        assert html.index("Can the household carry") < html.index("Complete check register")
        assert brief["survival"]["headline"] in html
        req = {"assessment_id": saved["assessment_id"], "case_version": 1, "changes": {}}
        historical = client.get(path + "/audit").json()
        assert client.post(path + "/survival-preview", json=req).json() == brief["survival"]
        req["changes"] = {"repair_cost": "0", "lost_income_monthly": 0, "rate_rise_bps": 0}
        better = client.post(path + "/survival-preview", json=req).json()
        assert float(better["combined"]["minimum_cash"]) > float(brief["survival"]["combined"]["minimum_cash"])
        assert len(client.get(path + "/assessments").json()["assessments"]) == 1
        assert client.get(path + "/audit").json() == historical
        assert client.get(target).json() == saved
        assert client.post(path + "/survival-preview", json={**req, "case_version": 2}).status_code == 409
        assert client.post(path + "/survival-preview", json={**req, "changes": {"repair_cost": -1}}).status_code == 422
        assert client.post(path + "/survival-preview", json=req, headers={"Authorization": f"Bearer {KEY}-other"}).status_code == 404
        assert replay_assessment(app.state.store, "demo", saved["assessment_id"]) == (saved, saved)
        app.state.store.set_source_policy("demo", "private-inspection", {"display_raw": False})
        assert client.get(target).status_code == 403
        assert client.post(path + "/survival-preview", json=req).status_code == 403
        assert client.get(path).json()["preoffer"]["underwriting"] == {}
        withheld = client.post(path + "/assessments").json()
        assert withheld["preoffer_capture"]["private_underwriting_withheld"]
        assert "Ceiling stain" not in str(withheld)
        assert replay_assessment(app.state.store, "demo", withheld["assessment_id"]) == (withheld, withheld)


def test_shared_preview_protects_household_and_written_evidence(tmp_path, monkeypatch):
    dest = tmp_path / "runtime" / "buyer-preview"
    monkeypatch.setenv("RISK_PROJECT_ROOT", str(tmp_path))
    dashboard = LocalDashboard("preview", "127.0.0.1", 8127, "demo", dest)
    client = TestClient(create_app(dest, {KEY: "demo"}, dashboard=dashboard), headers=AUTH)
    case = scenario()
    case.pop("demonstration")
    del case["finance"]
    assert client.post("/v1/cases", json=case).status_code == 403
    case["finance_is_illustrative"] = True
    assert client.post("/v1/cases", json=case).status_code == 201
    case["buyer_protection"] = {"death": {"policy_number": "do-not-store"}}
    assert client.post("/v1/cases", json=case).status_code == 422
    case.pop("buyer_protection")
    case["preoffer"]["underwriting"] = {"road": []}
    assert client.post("/v1/cases", json=case).status_code == 403
    assert client.post("/v1/cases/demo-house/documents", json={"filename": "sample.txt", "content_base64": ""}).status_code == 403


def test_legacy_jardine_replays_against_archived_result(tmp_path):
    folder = ROOT / "tests/fixtures/jardine_public_replay"
    def read(name):
        return json.loads((folder / name).read_bytes())
    stored = read("assessment.json")
    assert stored["preoffer_version"] == "1.0.0"
    db = Store(tmp_path / "fixture.sqlite")
    case = db.save_case("demo", read("case-input.json"))
    import_observations(db, "demo", case["case_id"], read("public-observations.json"),
                        trusted_public=True, preserve_received_at=True)
    _, obs = db.assessment_inputs("demo", case["case_id"], 1)
    db.save_assessment("demo", case["case_id"], stored, observations=obs, case_version=1)
    assert replay_assessment(db, "demo", stored["assessment_id"]) == (stored, stored)


def test_jardine_typed_lookup_to_household_priorities_and_identity_limits(tmp_path):
    app = create_app(tmp_path, {KEY: "demo"})
    with TestClient(app, headers=AUTH) as client:
        point, = client.get("/v1/locations/search", params={"street": "3/9 Jardine St", "suburb": "Kingston"}).json()["matches"]
        assert point["retained_address_match"]
        case = scenario()
        case.update(property_id="act-address-140619", as_of="2026-11-22T00:00:00Z",
                    property={**point, "identity_confirmed": True})
        case["preoffer"]["repair_cost"] = 70000
        assert client.post("/v1/cases", json=case).status_code == 201
        url = "/v1/cases/demo-house/assessments"
        saved = client.post(url).json()
        home = saved["preoffer_capture"]["home"]["property"]
        assert home["units_plan_no"] == "402" and home["block_key"] == 12170260047
        assert "No separate unit polygon" in home["unit_polygon_status"]
        assert saved["decision_evidence"]["public_marketing"]["address_id"] == "140619"
        cards = saved["preoffer_brief"]["top_three"]
        assert cards[0]["id"] == "household_survival" and cards[0]["illustrative"]
        assert any(item["id"] in {"underwriting:strata", "underwriting:approvals"} for item in cards[1:])
        assert client.get("/v1/assessments/" + saved["assessment_id"] + "/report").status_code == 200
        # Explicit conflicting identity must never inherit the exact-match capture.
        case["property"]["unit_id"] = "4"
        assert client.post("/v1/cases", json=case).status_code == 201
        conflict = client.post(url).json()
        assert "issue" in conflict["preoffer_capture"]["home"]
        assert conflict["decision_evidence"]["public_marketing"] is None
        app.state.store.set_source_policy("demo", "act_unit", {"display_raw": False})
        assert client.get("/v1/assessments/" + saved["assessment_id"]).status_code == 403
