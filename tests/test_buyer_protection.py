from copy import deepcopy
import json

import pytest

from riskengine.buyer_protection import buyer_protection


def budget():
    return {"settlement": {"cash_after_settlement": 12000, "protected_reserve": 10000, "funding_gap": 0},
            "baseline": {"timeline": [{"month": 0, "cash": 12000}, {"month": 1, "income": 8500, "net": 1000}]}}


def rows(inputs, survival=None):
    result = buyer_protection({"buyer_protection": inputs}, budget() if survival is None else survival)
    return {r["id"]: r for r in result["rows"]}


def test_unanswered_checks_and_untrusted_input_shape_stay_unknown():
    result = rows({})
    assert set(result) == {"property", "illness", "disability", "death", "career", "job_loss"}
    assert all(r["status"] == "unknown" and "moneysmart.gov.au/" in r["source_url"] for r in result.values())
    malformed = {"property": {"scope": [], "written_confirmed": True}, "illness": 55, "career": {"goal_monthly": "nan"}}
    assert all(r["status"] == "unknown" for r in rows(malformed, {}).values())


def test_building_terms_match_owner_or_scheme_and_use_only_accessible_cash():
    terms = dict(scope="owner", written_confirmed=True, annual_premium=1900, excess=3000,
                 sum_insured=400000, rebuild_cost=450000)
    result = rows({"property": terms})["property"]
    assert result["metrics"]["rebuild_gap"] == "50000.00"
    assert result["metrics"]["excess_cash_gap"] == "1000.00"
    assert result["status"] == "gap" and "this address" in result["action"]
    terms.update(scope="strata", excess=1000, sum_insured=8000000, rebuild_cost=8000000)
    result = rows({"property": terms})["property"]
    assert result["status"] == "modelled" and "whole scheme" in result["detail"] and "levy share" in result["detail"]
    assert "lot improvements" in result["action"]
    for bad in ({"scope": None}, {"written_confirmed": "true"}, {"rebuild_cost": 0}):
        assert rows({"property": {**terms, **bad}})["property"]["status"] == "unknown"


def test_income_cover_wait_and_conditional_benefit_do_not_fund_job_loss():
    inputs = {"illness": {"policy_confirmed": True, "waiting_days": 45, "net_benefit_monthly": 2000,
                         "lost_income_monthly": 4000},
              "career": {"goal_monthly": 600, "lost_income_monthly": 4000, "duration_months": 2}}
    result = rows(inputs)
    assert result["illness"]["metrics"] == {"monthly_gap_before_benefit": "3000.00", "waiting_days": 45,
                                            "waiting_cash_required": "4500.00", "waiting_cash_gap": "2500.00",
                                            "monthly_gap_if_paid": "1000.00"}
    assert result["job_loss"]["metrics"]["cash_gap"] == "4000.00"
    assert result["career"]["metrics"] == {"monthly_goal": "600.00", "flexibility_after_goals": "400.00",
                                           "flexibility_during_change": "-3600.00", "transition_gap": "5200.00"}
    inputs["illness"].update(policy_confirmed=False, net_benefit_monthly=10000)
    assert rows(inputs)["illness"]["status"] == "unknown"
    assert rows(inputs)["job_loss"] == result["job_loss"]


def test_chosen_income_and_goals_determine_career_mobility():
    data = {"career": {"goal_monthly": 600, "lost_income_monthly": 350, "duration_months": 5}}
    first = rows(data)
    assert first["career"]["metrics"]["flexibility_during_change"] == "50.00"
    assert first["career"]["status"] == "modelled"
    data["career"]["occupation"] = "high income profession"
    assert rows(data) == first
    data["career"]["lost_income_monthly"] = 8501
    assert rows(data)["job_loss"]["status"] == "unknown"
    assert rows(data)["career"]["status"] == "unknown"


def test_death_and_tpd_have_independent_cash_bridge_and_end_balance():
    terms = {"policy_confirmed": True, "benefit": 40000, "remaining_income_monthly": 3500,
             "ongoing_costs_monthly": 5000, "one_off_costs": 3000, "horizon_months": 12, "payout_delay_months": 2}
    data = {"death": terms, "disability": {**terms, "benefit": 3000, "ongoing_costs_monthly": 6500}}
    result = rows(data)
    assert result["death"]["status"] == "gap"
    assert result["death"]["metrics"]["gap_without_benefit"] == "19000.00"
    assert result["death"]["metrics"]["bridge_gap"] == "4000.00"
    assert result["death"]["metrics"]["horizon_gap_if_paid"] == "0.00"
    assert result["disability"]["metrics"]["bridge_gap"] == "7000.00"
    assert result["disability"]["metrics"]["horizon_gap_if_paid"] == "34000.00"
    assert rows({"death": {**terms, "payout_delay_months": 13}})["death"]["metrics"]["horizon_gap_if_paid"] == "19000.00"
    assert rows({"death": {**terms, "payout_delay_months": 0}})["death"]["status"] == "unknown"
    assert rows({"death": {**terms, "policy_confirmed": False}})["death"]["status"] == "unknown"
    no_cover = rows({"death": {**terms, "benefit": 0, "payout_delay_months": None}})["death"]
    assert no_cover["metrics"]["horizon_gap_if_paid"] == "19000.00"


def test_monthly_surplus_can_fund_later_costs_but_cannot_meet_day_one_costs():
    terms = {"policy_confirmed": True, "benefit": 1000, "remaining_income_monthly": 5000,
             "ongoing_costs_monthly": 4000, "one_off_costs": 4000, "horizon_months": 6, "payout_delay_months": 2}
    metrics = rows({"death": terms})["death"]["metrics"]
    assert metrics["bridge_gap"] == "2000.00" and metrics["horizon_gap_if_paid"] == "0.00"


@pytest.mark.parametrize("funding_gap", [None, 100])
def test_unfunded_or_unreconciled_settlement_prevents_cash_assurance(funding_gap):
    survival = budget()
    survival["settlement"]["funding_gap"] = funding_gap
    data = {"illness": {"lost_income_monthly": 3000, "policy_confirmed": True, "net_benefit_monthly": 1000,
                       "waiting_days": 30}}
    assert rows(data, survival)["illness"]["status"] == "unknown"


def test_assessment_is_json_replayable_and_preserves_user_data():
    case = {"finance_is_illustrative": True, "buyer_protection": {"career": {"goal_monthly": 100}}}
    survival = budget()
    original = deepcopy((case, survival))
    result = buyer_protection(case, survival)
    assert result == json.loads(json.dumps(buyer_protection(case, survival)))
    assert result["illustrative"] and original == (case, survival)
