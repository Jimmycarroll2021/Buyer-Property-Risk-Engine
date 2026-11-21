from copy import deepcopy
from decimal import Decimal as D
import json

import pytest

from riskengine.buyer_storms import evaluate_storms
from riskengine.finance import money, monthly_payment


def profile(**changes):
    return {
        "purchase_price": 400000, "deposit": 200000, "capitalized_lmi": 0,
        "cash_before_settlement": 305000, "acquisition_costs": 5000,
        "term_months": 240, "annual_rate_decimal": 0, "earner_incomes_monthly": [7000, 4500],
        "normal_living_monthly": 3200, "lean_living_monthly": 2500,
        "property_costs_monthly": 500, "locked_commitments_monthly": 200,
        "insurance_annual": 2400, "urgent_works": 1000, "first_year_works": 3000,
        "loss_duration_months": 4, "redundancy_available": 0, "leave_available": 0,
        "ip_wait_months": 2, "death_cover": 160000, "tpd_cover": 160000,
        "insurable": True, "primary_works_approved": True, "structural_clear": True,
        "illiquid": False, **changes,
    }


def result(**changes):
    return evaluate_storms(profile(**changes))


def test_full_green_is_reproducible_and_does_not_mutate_profile():
    request = profile()
    before = deepcopy(request)
    output = evaluate_storms(request)
    assert before == request and output == evaluate_storms(request)
    assert output["rule_version"] and output["assumptions"] and not output["missing_inputs"]
    assert output["verdict"] == "green"
    assert all(v["status"] == "green" for v in [*output["storms"].values(), *output["vetoes"].values()])
    assert output["baseline"]["cash_after_settlement"] == "100000.00"
    assert output["baseline"]["payment"] == "833.33"
    json.dumps(output, allow_nan=False)


def test_missing_evidence_is_not_zero_and_confirmed_failure_takes_precedence():
    result = evaluate_storms({})
    assert result["verdict"] == "unresolved"
    assert all(row["status"] == "unresolved" for row in result["storms"].values())
    for flag in ("insurable", "primary_works_approved", "structural_clear"):
        failed = evaluate_storms({flag: False})
        assert failed["vetoes"]["V1"]["status"] == failed["verdict"] == "red"
    assert evaluate_storms({"insurable": "false"})["vetoes"]["V1"]["status"] == "unresolved"


def test_day_two_after_urgent_and_base_burn_veto_boundaries_are_strict():
    # No borrowing: lean burn is precisely 3,000.
    exact = dict(deposit=400000, cash_before_settlement=411000, urgent_works=3000,
                 earner_incomes_monthly=[3000], normal_living_monthly=2500)
    output = result(**exact)
    assert all(v["status"] == "green" for v in output["vetoes"].values())
    for change, key in [({"cash_before_settlement": "410999.99"}, "V2"),
                        ({"urgent_works": "3000.01"}, "V3"),
                        ({"earner_incomes_monthly": ["2999.99"]}, "V4")]:
        assert result(**(exact | change))["vetoes"][key]["status"] == "red"


def test_storm_a_adds_only_incremental_premium_and_uses_larger_repair():
    changes = {"first_year_works": 20000, "capitalized_lmi": 4000}
    a = result(**changes)["storms"]["A"]
    payment = monthly_payment(204000, ".015", 240)
    assert a["stressed_payment"] == money(payment)
    assert a["incremental_premium_monthly"] == "40.00"
    assert a["works_month3"] == "25000.00"
    surplus = D(11500 - 2500 - 500 - 40) - payment
    assert a["cash_month3"] == money(100000 + 3 * surplus - 25000)
    assert a["cash_month12"] == money(100000 + 12 * surplus - 25000)
    assert a["normal_surplus"] == money(surplus - 700)
    assert len(a["monthly_cash"]) == 13
    assert a["monthly_cash"][3] == a["cash_month3"]
    assert result()["storms"]["A"]["works_month3"] == "15000.00"


def test_storm_a_normal_lifestyle_and_threshold_use_distinct_budgets():
    a = result(earner_incomes_monthly=[5000], normal_living_monthly=4500)["storms"]["A"]
    assert D(a["lean_surplus"]) > 0 > D(a["normal_surplus"])
    assert a["status"] == "amber"
    rate = D(a["break_even_rate_decimal"])
    assert abs(monthly_payment(200000, rate, 240) - D(2000)) < D(".01")
    a = result(earner_incomes_monthly=[3900], first_year_works=None)["storms"]["A"]
    assert a["status"] == "red" and a["cash_month3"] is None
    assert D(a["rate_margin_decimal"]) < D(".015")
    a = result(earner_incomes_monthly=[3100])["storms"]["A"]
    assert a["status"] == "red" and a["break_even_state"] == "deficit_even_at_zero_rate"


def test_storm_a_checkpoint_rules_and_repair_timing():
    # Cash after settlement and the month-three shock are the only movements.
    values = dict(deposit=400000, earner_incomes_monthly=[3000], normal_living_monthly=2500,
                  insurance_annual=0, acquisition_costs=0)
    def check(cash):
        return result(**values, cash_before_settlement=400000 + D(cash))["storms"]["A"]
    assert check("14999.99")["status"] == "red"
    assert check(15000)["status"] == "amber"
    assert check("23999.99")["status"] == "amber"
    assert check(24000)["status"] == "green"
    assert check(24000)["monthly_cash"][:4] == ["24000.00", "24000.00", "24000.00", "9000.00"]


def test_highest_earner_runway_thresholds_and_illness_cover_do_not_cross_fund():
    # No mortgage, B burn = 3,000 + 200, survivor income = 1,200, gap = 2,000.
    values = dict(deposit=400000, acquisition_costs=0, cash_before_settlement=404000,
                  earner_incomes_monthly=[1200, 7000], ip_wait_months=2, leave_available=1000)
    def check(**changes):
        return result(**(values | changes))["storms"]["B"]
    failed = check(redundancy_available="2999.99")
    assert failed["status"] == "red" and failed["nominated_earner_index"] == 1
    amber = check(redundancy_available=3000)
    assert amber["monthly_gap"] == "2000.00" and D(amber["runway_months"]) == 4
    assert amber["status"] == "amber"
    assert check(redundancy_available=7000)["status"] == "green"
    separate = check(redundancy_available=7000, ip_wait_months=3)
    assert separate["status"] == "amber" and separate["illness_wait_gap"] == "2000.00"
    assert check(redundancy_available=None)["status"] == "unresolved"
    assert check(redundancy_available=0, ip_wait_months=None)["status"] == "red"


def test_covers_are_separate_for_nominated_earner_and_cannot_pay_job_loss_bills():
    b = result(tpd_cover="159999.99", death_cover=400000)["storms"]["B"]
    assert b["status"] == "amber" and b["tpd_cover_gap"] == "0.01" and b["death_cover_gap"] == "0.00"
    assert result(tpd_cover=None)["storms"]["B"]["status"] == "unresolved"
    assert result(earner_incomes_monthly=[7000, 7000])["storms"]["B"]["nominated_earner_index"] == 0
    self_funding = result()["storms"]["B"]
    assert self_funding["runway_state"] == "self_funding" and self_funding["runway_months"] is None
    json.dumps(self_funding, allow_nan=False)


def test_exit_single_haircut_capitalized_lmi_and_signed_buffer():
    c = result(illiquid=True, capitalized_lmi=4000)["storms"]["C"]
    assert c["sale_price"] == "340000.00" and c["selling_costs"] == "12000.00"
    assert c["balance_month24"] == "183600.00"  # zero rate, 24 repayments of 850
    assert c["net_sale_equity"] == "144400.00"
    assert c["cash_month24"] == money(D(100000) + 24 * D(11500 - 3200 - 500 - 850) - 3000)
    assert D(c["cash_after_sale"]) == D(c["cash_month24"]) + D("144400")
    assert abs(D(c["wealth_loss_fraction"]) - D(205000 - 144400) / 305000) < D(".00000001")
    deficit = result(earner_incomes_monthly=[2000], normal_living_monthly=5100)["storms"]["C"]
    assert D(deficit["cash_month24"]) < 0 < D(deficit["net_sale_equity"])
    assert deficit["status"] == "red" and deficit["first_presale_shortfall_month"] < 24


def test_presale_shortfall_even_if_cash_recovers_by_sale_and_missing_exit_facts():
    c = result(cash_before_settlement=205100, first_year_works=90000, illiquid=None)["storms"]["C"]
    assert c["first_presale_shortfall_month"] == 12
    assert D(c["cash_month24"]) > 0 and c["net_sale_equity"] is None and c["status"] == "red"


def test_negative_opening_cash_and_known_prefix_survive_missing_future_inputs():
    failed = result(cash_before_settlement=204999, earner_incomes_monthly=None)
    c = failed["storms"]["C"]
    assert failed["verdict"] == c["status"] == "red" and c["first_presale_shortfall_month"] == 0
    assert c["cash_month24"] is None and c["monthly_cash"][0] == "-1.00"
    failed = result(cash_before_settlement=206000, earner_incomes_monthly=[2000], first_year_works=None)
    c = failed["storms"]["C"]
    assert c["first_presale_shortfall_month"] == 1 and c["status"] == "red"
    assert c["monthly_cash"][11] is not None and c["monthly_cash"][12] is None
    # With an unknown normal budget and very high known property costs, even
    # setting all unknown expenses to zero proves a pre-sale shortfall.
    c = result(cash_before_settlement=206000, property_costs_monthly=4000,
               normal_living_monthly=None, earner_incomes_monthly=[1000])["storms"]["C"]
    assert c["first_presale_shortfall_month"] is None and c["presale_shortfall_by_month"] == 1
    assert c["status"] == "red"


def test_exit_exact_lvr_and_wealth_loss_classification_edges():
    values = dict(purchase_price=500000, deposit=100000, acquisition_costs=80000,
                  cash_before_settlement=261875)
    c = result(**values)["storms"]["C"]
    assert D(c["lvr_decimal"]) == D(".80") and D(c["wealth_loss_fraction"]) == D(".40")
    assert c["status"] == "amber"
    just_inside = result(**(values | {"cash_before_settlement": "261875.01"}))["storms"]["C"]
    assert just_inside["status"] == "green"
    large = dict(deposit=40000, term_months=1200, acquisition_costs=0, cash_before_settlement=60400)
    c = result(**large)["storms"]["C"]
    assert D(c["wealth_loss_fraction"]) == D(".75") and c["status"] == "amber"
    just_beyond = result(**(large | {"cash_before_settlement": "60399.99"}))["storms"]["C"]
    assert just_beyond["status"] == "red"


def test_short_loan_stops_payments_after_maturity():
    out = result(term_months=2, annual_rate_decimal=".06", purchase_price=210000)
    c, a = out["storms"]["C"], out["storms"]["A"]
    assert c["balance_month24"] == "0.00"
    assert D(c["monthly_cash"][3]) - D(c["monthly_cash"][2]) == D(7800)
    assert D(a["monthly_cash"][4]) - D(a["monthly_cash"][3]) == D(8460)


@pytest.mark.parametrize("changes,field", [
    ({"annual_rate_decimal": "NaN"}, "annual_rate_decimal"),
    ({"cash_before_settlement": "1e999999"}, "cash_before_settlement"),
    ({"deposit": True}, "deposit"), ({"purchase_price": 0}, "purchase_price"),
    ({"term_months": "1.1"}, "term_months"), ({"loss_duration_months": 5}, "loss_duration_months"),
    ({"earner_incomes_monthly": [5000, None]}, "earner_incomes_monthly"),
    ({"cash_after_settlement": 99999}, "cash_after_settlement"),
    ({"principal": 190000}, "principal"), ({"deposit": 400001}, "deposit"),
])
def test_invalid_or_conflicting_inputs_are_auditable_and_never_green(changes, field):
    out = result(**changes)
    assert out["verdict"] != "green" and field in out["input_issues"]
    json.dumps(out, allow_nan=False)
