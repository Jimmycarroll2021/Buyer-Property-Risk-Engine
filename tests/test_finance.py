"""Cash acceptance cases PR-AT-012, PR-AT-013 and PR-AT-014."""
from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from riskengine.finance import (FinanceInputError, evaluate_finance, loan_schedule,
                                money, monthly_payment, remaining_balance)


@pytest.fixture
def finance():
    return {"principal":"720000", "annual_rate_decimal":"0.06", "term_months":360,
            "income_monthly":"11000", "living_monthly":"4800", "other_debt_monthly":"0",
            "property_costs_monthly":"900", "cash_after_settlement":"45000", "protected_reserve":"15000",
            "purchase_price":"900000", "acquisition_costs":"25000", "immediate_works":"10000",
            "loan_funds":"720000", "cash_allocated":"215000", "funding_confirmed":True}


def test_pr_at_012_amortisation_reference_values():
    assert money(monthly_payment("720000", ".06", 360)) == "4316.76"
    assert money(monthly_payment("720000", ".08", 360)) == "5283.10"
    assert money(monthly_payment("720000", "0", 360)) == "2000.00"
    assert money(remaining_balance("720000", ".06", 360, 36)) == "691805.30"
    assert remaining_balance("720000", "0", 360, 360) == Decimal(0)


def test_pr_at_012_missing_income_preserves_repayment(finance):
    del finance["income_monthly"]
    result = evaluate_finance(finance)
    assert result["repayment"]["monthly_payment"] == "4316.76"
    assert result["baseline"]["state"] == "NOT_ASSESSED"
    assert result["baseline"]["priority"] is None
    assert "income_monthly" in result["baseline"]["missing_inputs"]


@pytest.mark.parametrize("change", [{"annual_rate_decimal":"6"}, {"repayment_type":"interest_only"},
                                   {"offset_balance":"10000"}, {"loan_splits":[{}]},
                                   {"term_months":0}, {"principal":"NaN"}, {"rate_schedule":"invalid"}])
def test_pr_at_012_invalid_or_unsupported_terms_withhold_model(finance, change):
    finance.update(change)
    assert evaluate_finance(finance)["repayment"]["state"] == "NOT_ASSESSED"


def test_rate_units_must_be_explicit(finance):
    finance.pop("annual_rate_decimal")
    finance["annual_rate"] = "6"
    assert evaluate_finance(finance)["repayment"]["state"] == "NOT_ASSESSED"
    finance["rate_unit"] = "percent"
    assert evaluate_finance(finance)["repayment"]["monthly_payment"] == "4316.76"


def test_rate_reset_uses_remaining_balance_and_term(finance):
    finance["rate_schedule"] = [{"start_month":25,"annual_rate_decimal":"0.08"}]
    rows = loan_schedule(finance, 360)
    expected_balance = remaining_balance("720000", ".06", 360, 24)
    expected_payment = monthly_payment(expected_balance, ".08", 336)
    assert money(rows[24]["opening_balance"]) == money(expected_balance)
    assert money(rows[24]["payment"]) == money(expected_payment)
    assert money(rows[24]["payment"]) != money(monthly_payment("720000", ".08", 360))
    assert rows[-1]["closing_balance"] == Decimal(0)


def test_pr_at_013_stress_duration_changes_result(finance):
    scenarios = [{"scenario_id":f"combined_{n}","duration_months":n,"rate_delta_bps":200,
                  "income_factor":"0.70","required_review":True} for n in (6,12)]
    outputs = {s["scenario_id"]:s for s in evaluate_finance(finance,scenarios)["scenarios"]}
    six,twelve = outputs["combined_6"],outputs["combined_12"]
    assert six["ending_cash"] == "25301.37"
    assert six["reserve_breached"] is False and six["priority"] == 0
    assert twelve["ending_cash"] == "5602.74"
    assert twelve["first_breach_month"] == 10
    assert twelve["continuous_equivalent_months_to_reserve"] == "9.14"
    assert twelve["priority"] == 3
    assert len(twelve["monthly_schedule"]) == 12


def test_pr_at_013_essential_and_exploratory_thresholds(finance):
    s = {"scenario_id":"shock", "duration_months":12,"rate_delta_bps":200,"income_factor":"0.7"}
    assert evaluate_finance(finance,[s])["scenarios"][0]["priority"] == 2
    s["requirement_id"] = "survive_shock"
    req = [{"requirement_id":"survive_shock","essential":True}]
    assert evaluate_finance(finance,[s],req)["scenarios"][0]["priority"] == 4
    s["requirement_id"] = "not_a_real_requirement"
    assert evaluate_finance(finance,[s],req)["scenarios"][0]["priority"] == 2


def test_pr_at_014_rental_deductions_and_annual_costs_once(finance):
    finance.pop("property_costs_monthly")
    finance.update(property_costs_annual="10800", intended_use="investment", gross_rent_monthly="3000",
                   vacancy_fraction="0.10", management_fraction="0.08")
    baseline = evaluate_finance(finance)["baseline"]
    assert baseline["rental"] == {"rent_gross":"3000.00","rent_vacancy":"300.00", "rent_management":"216.00","rent_net":"2484.00"}
    assert baseline["property_costs_monthly"] == "900.00"
    assert baseline["monthly_surplus"] == "3467.24"
    finance["property_costs_include_management"] = True
    assert evaluate_finance(finance)["baseline"]["state"] == "NOT_ASSESSED"


def test_pr_at_014_exit_pays_remaining_principal_not_original_loan(finance):
    finance["exit"] = {"sale_month":36,"sale_price":"1000000","selling_costs":"25000", "tax_treatment":"before_personal_tax"}
    result = evaluate_finance(finance)["exit"]
    assert result["remaining_principal"] == "691805.30"
    assert result["net_sale_proceeds"] == "283194.70"
    assert result["tax_costs"] is None
    finance["exit"]["tax_treatment"] = "explicit_tax"
    assert evaluate_finance(finance)["exit"]["state"] == "NOT_ASSESSED"


def test_settlement_is_separate_from_cashflow(finance):
    finance["cash_allocated"] = "200000"
    result = evaluate_finance(finance)
    assert result["baseline"]["priority"] == 0
    assert result["settlement"]["funding_gap"] == "15000.00"
    assert result["settlement"]["priority"] == 4
    finance["funding_confirmed"] = False
    assert evaluate_finance(finance)["settlement"]["priority"] is None


def test_cash_cannot_be_allocated_twice(finance):
    finance["total_liquid_cash"] = "230000"
    result = evaluate_finance(finance,[{"scenario_id":"base","duration_months":6}])
    assert result["settlement"]["reason"] == "CASH_DOUBLE_ALLOCATION"
    assert result["buffer"]["state"] == "NOT_ASSESSED"
    assert result["scenarios"][0]["state"] == "NOT_ASSESSED"


def test_buffer_months_use_all_essential_outgoings(finance):
    finance["minimum_buffer_months"] = "6"
    result = evaluate_finance(finance)["buffer"]
    assert result["months_of_essential_outgoings"] == "4.49"
    assert result["priority"] == 2


def test_decimal_precision_is_not_callers_default_context(finance):
    with localcontext() as ctx:
        ctx.prec = 8
        result = evaluate_finance(finance)
    assert result["repayment"]["monthly_payment"] == "4316.76"
