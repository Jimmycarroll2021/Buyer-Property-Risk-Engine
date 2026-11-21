"""Seed the public Jardine brief and a separate fictional household in the loopback demo."""
import hashlib
import json

from riskengine.paths import project_root
from riskengine.pipeline import assess_case, import_observations
from riskengine.storage import Store


def main():
    preview = project_root() / "runtime" / "buyer-preview"
    pack = preview / "jardine-3-9-kingston"
    original = json.loads((pack / "case-input.json").read_text(encoding="utf-8"))
    if original["property_id"] != "act-address-140619" or str(original["property"]["unit_id"]) != "3":
        raise ValueError("The retained address must match Unit 3, 9 Jardine Street")
    observation_bytes = (pack / "public-observations.json").read_bytes()
    if hashlib.sha256(observation_bytes).hexdigest() != "d613baa67c5263809be30736048527889fd491334b8f6d5b9c3eb038ef85002b":
        raise ValueError("The retained public observation pack has changed")
    observations = json.loads(observation_bytes)
    for row in observations:
        if row["property_id"] != original["property_id"] or row["visibility_scope"] != "public" or row["evidence_basis"] != "official_record":
            raise ValueError("Expected official public evidence for the selected unit")
        for source in row["public_sources"]:
            if hashlib.sha256((pack / source["file"]).read_bytes()).hexdigest() != source["response_sha256"]:
                raise ValueError("A retained official source no longer matches its capture")
    store = Store(preview / "riskengine.sqlite3")
    common = {**original, "finance": {}, "requirements": [], "scenarios": [],
              "as_of": "2026-11-21T20:18:00+00:00", "preoffer": {"intended_use": "owner_occupier"}}
    public = {**common, "case_id": "jardine-first-home-public-v1", "finance_is_illustrative": False}
    options = {
        "offer_price": "1550000", "price_basis": "proposed_offer", "intended_use": "owner_occupier",
        "alternative_offer_price": "1475000", "horizon_months": 60, "selling_costs": "36000",
        "rate_delta_bps": 150, "income_factor": "0.55", "property_cost_factor": "1", "special_levy": "0", "levy_month": 1,
        "rate_rise_bps": 150, "lost_income_monthly": "8000", "loss_months": 4, "extra_expense_monthly": "350",
        "repair_cost": "25000", "repair_overrun_pct": "30", "repair_month": 2,
        "sale_price_3y": "1475000", "sale_price_5y": "1550000", "selling_cost_pct": "2", "selling_cost_fixed": "5000",
    }
    finance = {
        "purchase_price": "1550000", "principal": "1240000", "loan_funds": "1240000", "term_months": 360,
        "annual_rate_decimal": "0.06", "acquisition_costs": "65000", "immediate_works": "5000",
        "cash_allocated": "380000", "cash_after_settlement": "42000", "total_liquid_cash": "422000", "protected_reserve": "25000",
        "income_monthly": "17500", "living_monthly": "5100", "other_debt_monthly": "400", "property_costs_monthly": "2000",
        "funding_confirmed": False
    }
    protection = {
        "property": {"scope":"strata", "written_confirmed":False},
        "illness": {"policy_confirmed": True, "lost_income_monthly":"8000", "waiting_days":60, "net_benefit_monthly":"4200"},
        "career": {"goal_monthly":"1500", "lost_income_monthly":"6500", "duration_months":6},
        "disability": {"policy_confirmed":True, "benefit":"180000","remaining_income_monthly":"9500",
                       "ongoing_costs_monthly":"16000","one_off_costs":"50000","horizon_months":36,"payout_delay_months":6},
        "death": {"policy_confirmed":True, "benefit":"400000","remaining_income_monthly":"9500",
                  "ongoing_costs_monthly":"14500","one_off_costs":"20000","horizon_months":60,"payout_delay_months":3}
    }
    fictional = {**common, "case_id": "jardine-first-home-example-v1", "finance_is_illustrative": True,
                 "finance":finance, "preoffer":options, "buyer_protection":protection,
                 "input_note":"Real public address. All household, funding, offer, repair, policy and resale assumptions are fictional."}
    for case in [public, fictional]:
        versions = [row for row in store.list_cases("demo") if row["case_id"] == case["case_id"]]
        if versions and versions[0].get("property_id") != case["property_id"]:
            raise ValueError("The reserved example ID belongs to a different property.")
        store.save_case("demo",case,expected_version=versions[0]["case_version"] if versions else 0)
        import_observations(store,"demo",case["case_id"],observations,trusted_public=True,preserve_received_at=True)
        result=assess_case(store,"demo",case["case_id"])
        print(case["case_id"],result["assessment_id"],result["preoffer_brief"]["survival"]["headline"])


if __name__ == "__main__":
    main()
