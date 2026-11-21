from copy import deepcopy
import json

from riskengine.engine import evaluate_case
from riskengine.purchase_decision import purchase_decision


def case():
    return {
        "case_id": "buyer", "property_id": "unit", "as_of": "2026-11-21", "owner_tenant_id": "test",
        "property": {"identity_confirmed": True},
        "finance": {
            "principal": 720000, "annual_rate_decimal": "0.06", "term_months": 360,
            "income_monthly": 11000, "living_monthly": 4800, "other_debt_monthly": 0,
            "property_costs_monthly": 900, "cash_after_settlement": 45000, "protected_reserve": 15000,
            "purchase_price": 900000, "loan_funds": 720000, "cash_allocated": 215000,
            "acquisition_costs": 25000, "immediate_works": 10000, "funding_confirmed": True,
        },
        "scenarios": [{"scenario_id": "combined", "duration_months": 6, "income_factor": "0.7",
                       "rate_delta_bps": 200, "required_review": True}],
    }


def decision(c, context=None, checks=None):
    if checks is None:
        checks = [{"check_id": cid, "rule_ids": [rule], "domain": "Buyer finance", "critical": True}
                  for cid, rule in (("S056", "FN01"), ("S057", "FN02"), ("S058", "FN03"), ("S065", "FN04"))]
    assessment = evaluate_case(c, [], checks)
    pinned = deepcopy(assessment)
    result = purchase_decision(c, assessment, context or {})
    assert assessment == pinned
    assert result == json.loads(json.dumps(purchase_decision(c, assessment, context or {})))
    return result


def test_cash_flow_changes_outcome_and_duplicate_stress_paths_remain_one_driver():
    c = case()
    assert decision(c)["state"] == "no_material_concern"
    c["scenarios"][0]["duration_months"] = 12
    outcome = decision(c)
    assert outcome["state"] == "review"
    assert len(outcome["drivers"]) == 1
    stress = outcome["drivers"][0]
    assert "month 10" in stress["title"] and "12 months" in stress["detail"]
    assert "A$9,397.26" in stress["detail"] and "A$15,000.00" in stress["detail"]
    assert {"S057", "S058"}.issubset(stress["references"])
    c["finance"]["income_monthly"] = 12500
    assert decision(c)["state"] == "no_material_concern"


def test_day_one_cash_overrides_monthly_surplus_only_with_confirmed_inputs():
    c = case()
    c["finance"]["cash_allocated"] -= 10000
    result = decision(c)
    assert result["state"] == "blocked"
    assert "A$10,000.00" in result["drivers"][0]["changes_outcome"]
    c["finance"]["funding_confirmed"] = False
    result = decision(c)
    assert result["state"] == "incomplete" and not result["drivers"]
    assert "provisional shortfall of A$10,000.00" in result["open_checks"][0]["detail"]
    del c["finance"]["acquisition_costs"]
    assert "acquisition costs" in decision(c)["open_checks"][0]["detail"]


def test_example_and_unknown_inputs_cannot_confirm_a_real_buyer_failure():
    c = case()
    c["finance_is_illustrative"] = True
    c["finance"]["cash_allocated"] = 10000
    example = decision(c)
    assert example["state"] == "incomplete" and example["drivers"][0]["illustrative"]
    assert "Illustrative" in example["summary"]
    assert any(gap["id"] == "buyer_inputs" for gap in example["open_checks"])
    del c["finance_is_illustrative"]
    c["finance"]["received_at"] = "2027-01-01"
    unknown = decision(c)
    assert unknown["state"] == "incomplete" and not unknown["drivers"]
    assert not any("A$" in gap["detail"] for gap in unknown["open_checks"])


def test_proximity_and_historical_context_neither_create_nor_clear_a_blocker():
    c = case()
    context = {
        "planning": [
            {"title": "Two eight-storey buildings | DA 101", "status": "On notification",
             "source_url": "https://example.test/record?da-number=101", "distance_m": 10,
             "as_of": "2026-11-19", "detail": "Application site lies 10 m from the address point."},
            {"title": "Proposed light rail Stage 2B", "distance_m": 300, "as_of": "2026-10-07",
             "source_url": "https://example.test/rail", "detail": "Proposal under assessment."}],
        "crime": [{"title": "Reported offences", "as_of": "2025-06-30", "status": "available",
                   "source_url": "https://example.test/crime", "detail": "Historic suburb counts."}],
    }
    result = decision(c, context)
    assert result["state"] == "no_material_concern" and not result["drivers"]
    check = result["open_checks"][0]
    assert check["id"] == "da:101" and check["as_of"] == "2026-11-19"
    assert "shadow" in check["action"] and "site-specific" in check["changes_outcome"]
    assert [(n["role"], n["priority"]) for n in result["context_notes"]] == [
        ("transport_context", None), ("historical_area_context", None)]
    c["finance"]["cash_allocated"] = 0
    assert decision(c, context)["state"] == "blocked"


def test_unconfirmed_identity_is_a_single_prerequisite_with_all_affected_checks():
    c = case()
    c["property"]["identity_confirmed"] = False
    result = decision(c, checks=[{"check_id": "S001", "critical": True},
                                 {"check_id": "S005", "critical": True}])
    assert result["state"] == "incomplete" and result["drivers"] == []
    assert len(result["open_checks"]) == 1
    assert {"S001", "S005"}.issubset(result["open_checks"][0]["references"])
    result = purchase_decision(c, None, {})
    assert result["state"] == "incomplete" and result["assessment_id"] is None
    assert result["open_checks"][0]["id"] == "assessment"


def test_observed_defect_survives_unknown_repair_cost_and_keeps_evidence_ids():
    c = case()
    checks = [{"check_id": "S021", "label": "Structural condition", "domain": "Building condition",
               "critical": True, "rule_ids": ["BD01"]}]
    obs = {"check_id": "S021", "property_id": "unit", "observation_id": "inspection-1",
           "source_id": "inspector", "snapshot_id": "report-1", "received_at": "2026-10-31",
           "evidence_basis": "private_inspection", "confidence": "High", "visibility_scope": "private",
           "owner_tenant_id": "test", "case_scope_id": "buyer",
           "rights": {"process": True, "display_derived": True, "retain_raw": True},
           "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED",
                       "complete": True, "current": True, "identity_match": True},
           "payload": {"kind": "inspection", "reviewed": True, "material_defect": True,
                       "statement": "The inspection identified a fractured support post."}}
    assessment = evaluate_case(c, [obs], checks)
    result = purchase_decision(c, assessment, {})
    assert result["state"] == "review"
    assert "fractured support post" in result["summary"]
    assert {"inspection-1", "report-1"}.issubset(result["drivers"][0]["references"])
    assert "itemised repair quote" in result["open_checks"][0]["action"]
    assert not result["coverage"]["complete"]


def test_shorter_horizon_kept_in_longer_stress_explanation():
    c = case()
    c["scenarios"].append({**c["scenarios"][0], "duration_months": 12, "scenario_id": "longer"})
    assert "shorter 6-month test" in decision(c)["drivers"][0]["detail"]


def test_legal_question_preserves_review_scope_without_adopting_legacy_claim_as_conclusion():
    c = case()
    checks = [{"check_id": "S018", "label": "Access rights", "domain": "Legal and planning",
               "critical": True, "rule_ids": ["LG01"]}]
    obs = {"check_id": "S018", "property_id": "unit", "observation_id": "map-review",
           "source_id": "easement-register", "snapshot_id": "map-v1", "published_at": "2026-10-31",
           "evidence_basis": "official_record", "confidence": "Medium", "visibility_scope": "public",
           "rights": {"process": True, "display_derived": True, "retain_raw": True},
           "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED",
                       "complete": True, "current": True, "identity_match": True},
           "payload": {"kind": "restriction", "reviewed": True, "conflict": False,
                       "material_question": True, "scope_complete": False,
                       "scope": "Mapped corridor and building boundary",
                       "statement": "A proposed corridor intersects the parcel."}}
    assessed = evaluate_case(c, [obs], checks)
    old = purchase_decision(c, assessed, {}, rule_version="1.0.0")
    current = purchase_decision(c, assessed, {})
    assert old["rule_version"] == "1.0.0" and old["drivers"][0]["detail"] == obs["payload"]["statement"]
    assert current["rule_version"] == "1.0.1" and current["state"] == old["state"] == "review"
    assert "intersects the parcel" not in current["summary"]
    assert obs["payload"]["scope"] in current["summary"] and "legal effect" in current["summary"]
    assert current["drivers"][0]["references"] == old["drivers"][0]["references"]
