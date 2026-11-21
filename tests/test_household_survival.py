from copy import deepcopy
from decimal import Decimal
import json

import pytest

from riskengine.finance import FinanceInputError, money, monthly_payment
from riskengine.household_survival import household_survival


def evaluate(fields=None, **options):
    finance = dict(purchase_price=240000, principal=120000, loan_funds=120000,
                   term_months=120, annual_rate_decimal=0, income_monthly=6000,
                   living_monthly=2200, other_debt_monthly=100, property_costs_annual=8400,
                   cash_after_settlement=3000, protected_reserve=1800, acquisition_costs=4000,
                   immediate_works=1000, cash_allocated=125000, funding_confirmed=True)
    finance.update(fields or {})
    return household_survival({"finance": finance, "as_of": "2026-10-07"}, {}, options)


def test_primary_shock_compares_dated_cash_flows_without_charging_twice():
    result = evaluate(lost_income_monthly=3000, repair_cost=1000, repair_month=2)
    base, combined = result["baseline"], result["combined"]
    assert result["settlement"]["state"] == "funded"
    assert base["timeline"][0]["cash"] == "3000.00"
    assert base["timeline"][1]["net"] == "2000.00"
    assert combined["timeline"][1]["mortgage"] == money(monthly_payment(120000, ".015", 120))
    timeline = combined["timeline"]
    assert [r["income"] for r in timeline[1:6]] == ["3000.00"] * 4 + ["6000.00"]
    assert [r["repair"] for r in timeline[1:4]] == ["0.00", "1300.00", "0.00"]
    assert combined["first_reserve_breach_month"] == 2
    assert combined["first_shortfall_month"] == 2
    assert combined["minimum_cash_month"] == 4
    assert combined["rebuild_month"] == 7
    assert combined["reserve_rebuild_month"] == 7
    assert combined["cash_shortfall"] == money(-Decimal(combined["minimum_cash"]))
    assert Decimal(combined["reserve_shortfall"]) == Decimal(combined["cash_shortfall"]) + 1800
    assert base["first_year"]["total_cash_out"] == "173000.00"
    assert combined["first_year"]["total_cash_out"] == money(
        Decimal(125000 + 12 * 3000 + 1300) + 12 * monthly_payment(120000, ".015", 120))
    assert combined["first_year"]["income_and_net_rent"] == "60000.00"
    difference = result["first_year_difference"]
    assert difference["additional_cash_used"] == money(Decimal(12000 + 1300)
                                                       + 12 * (monthly_payment(120000, ".015", 120) - 1000))
    json.dumps(result, allow_nan=False)


def test_reserve_is_protection_not_an_additional_bill():
    result = evaluate(lost_income_monthly=2500, repair_cost=0, rate_rise_bps=0)
    combined = result["combined"]
    assert combined["state"] == "reserve_breach"
    assert combined["first_reserve_breach_month"] == 3
    assert combined["first_shortfall_month"] is None
    assert combined["minimum_cash"] == "1000.00"
    assert combined["cash_shortfall"] == "0.00"
    assert combined["reserve_shortfall"] == "800.00"
    assert combined["reserve_rebuild_month"] == combined["rebuild_month"] == 5


def test_unknown_inputs_stay_unknown_and_provisional_settlement_is_explicit():
    missing = evaluate()
    assert {"lost_income_monthly", "repair_cost"} <= set(missing["missing_inputs"])
    assert missing["combined"]["minimum_cash"] is None
    assert missing["baseline"]["timeline"]
    provisional = evaluate({"funding_confirmed": False}, lost_income_monthly=0, repair_cost=0)
    assert provisional["state"] == "conditional"
    assert "If settlement is funded" in provisional["headline"]
    assert provisional["settlement"]["state"] == "unconfirmed"
    failed = evaluate({"cash_allocated": 124900}, lost_income_monthly=0, repair_cost=0)
    assert failed["state"] == "settlement_shortfall"
    assert failed["settlement"]["funding_gap"] == "100.00"
    assert not failed["combined"]["timeline"]
    invalid = evaluate({"total_liquid_cash": 126000}, lost_income_monthly=0, repair_cost=0)
    assert invalid["settlement"]["state"] == "inconsistent" and not invalid["combined"]["timeline"]


def test_month_zero_floor_and_explicit_longer_family_scenario():
    result = evaluate({"protected_reserve": 3500}, lost_income_monthly=500, loss_months=10,
                      extra_expense_monthly=1800, repair_cost=0, rate_rise_bps=0)
    scenario = result["combined"]
    assert scenario["first_reserve_breach_month"] == 0
    assert scenario["minimum_cash"] == "0.00"
    assert scenario["first_shortfall_month"] is None
    assert scenario["timeline"][10]["net"] == "-300.00"
    assert scenario["timeline"][11]["net"] == "2000.00"
    assert scenario["first_year"]["extra_expenses"] == "18000.00"


def test_repair_outside_first_year_and_no_income_shock():
    result = evaluate(loss_months=0, repair_month=13)
    assert "repair_cost" not in result["missing_inputs"]
    assert result["combined"]["first_year"]["urgent_repair"] == "0.00"
    assert result["combined"]["state"] == "holds"


def test_exit_equity_proceeds_hurdle_and_debt_remain_independent():
    result = evaluate(sale_price_3y=250000, selling_cost_fixed=1000, selling_cost_pct=2)
    three, five = result["exit_scenarios"]
    assert three["gross_equity"] == "166000.00"
    assert three["net_proceeds"] == "160000.00"
    assert three["break_even_resale"] == money(Decimal(240000 + 5000 + 36 * 700 + 1000) / Decimal(".98"))
    assert five["gross_equity"] is None and five["net_proceeds"] is None
    assert five["remaining_debt"] == "60000.00" and five["break_even_resale"]
    partial = evaluate(sale_price_3y=250000)["exit_scenarios"][0]
    assert partial["gross_equity"] == "166000.00" and partial["net_proceeds"] is None
    assert partial["break_even_resale"] is None


def test_rate_threshold_and_resets():
    result = evaluate({"income_monthly": 4000})
    assert result["break_even_rate_pct"] == "0.00"
    assert evaluate({"income_monthly": 3999})["break_even_rate_state"] == "deficit_even_at_zero_rate"
    reset = evaluate({"rate_schedule": [{"start_month": 2, "annual_rate_decimal": ".06"}]},
                     lost_income_monthly=0, repair_cost=0)
    assert reset["baseline"]["timeline"][2]["mortgage"] == money(monthly_payment(119000, ".06", 119))
    assert Decimal(reset["combined"]["timeline"][2]["mortgage"]) > Decimal(reset["baseline"]["timeline"][2]["mortgage"])


def test_changed_offer_pure_inputs_and_as_of_gate():
    case = {"finance": {"purchase_price": 100000, "principal": 80000, "loan_funds": 80000,
                        "term_months": 120, "annual_rate_decimal": 0, "cash_after_settlement": 2000,
                        "acquisition_costs": 1000, "immediate_works": 0, "funding_confirmed": True,
                        "cash_allocated": 21000}}
    before = deepcopy(case)
    result = household_survival(case, {}, {"offer_price": 95000})
    assert case == before
    assert result["settlement"]["state"] == "unconfirmed"
    assert result["settlement"]["cash_after_settlement"] == "3000.00"
    assert result["settlement"]["cash_required"] == "20000.00"
    future = evaluate({"received_at": "2026-10-08"})
    assert future["settlement"]["offer_price"] is None and future["baseline"]["minimum_cash"] is None
    assert "finance_not_known_as_of" in future["missing_inputs"]


def test_invalid_loss_rejected():
    with pytest.raises(FinanceInputError, match="cannot exceed"):
        evaluate(lost_income_monthly=6001)


def test_known_first_year_line_items_survive_a_partial_household_budget():
    result = evaluate({"income_monthly": None, "living_monthly": None}, lost_income_monthly=0, repair_cost=0)
    for scenario in (result["baseline"], result["combined"]):
        year = scenario["first_year"]
        assert year["property_running_costs"] == "8400.00"
        assert year["other_debt_payments"] == "1200.00"
        assert year["living_expenses"] is None and year["living_and_other_debt"] is None
        assert year["total_cash_out"] is None and year["income_and_net_rent"] is None
        assert year["net_cash_used_including_settlement"] is None and not scenario["timeline"]
    only_income_missing = evaluate({"income_monthly": None})["baseline"]["first_year"]
    assert only_income_missing["total_cash_out"] == "173000.00"
    assert only_income_missing["net_cash_used_including_settlement"] is None
    only_spending_missing = evaluate({"property_costs_annual": None})["baseline"]["first_year"]
    assert only_spending_missing["income_and_net_rent"] == "72000.00"
    assert only_spending_missing["property_running_costs"] is None and only_spending_missing["total_cash_out"] is None


def test_finance_overrides_apply_at_cutoff_without_reviving_future_base_fields():
    revised = evaluate(finance={"living_monthly": 1000, "received_at": "2026-10-07"})
    assert revised["baseline"]["first_year"]["living_expenses"] == "12000.00"
    assert revised["baseline"]["timeline"][1]["net"] == "3200.00"
    withheld = evaluate({"received_at": "2026-10-08"},
                        finance={"property_costs_annual": 6000, "received_at": "2026-10-06"})
    assert withheld["baseline"]["first_year"]["property_running_costs"] == "6000.00"
    assert withheld["baseline"]["first_year"]["mortgage"] is None
    assert withheld["settlement"]["cash_after_settlement"] is None and not withheld["baseline"]["timeline"]
    with pytest.raises(FinanceInputError, match="outside the assessment date"):
        evaluate(finance={"living_monthly": 1000, "received_at": "2026-10-08"})
