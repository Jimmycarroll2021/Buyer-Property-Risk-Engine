from copy import deepcopy
from decimal import Decimal

import pytest

from riskengine.finance import FinanceInputError, evaluate_finance
from riskengine.preoffer_costs import preoffer_costs


CASE = {
    "as_of": "2026-11-20T12:00:00Z",
    "property": {"jurisdiction": "ACT", "suburb": "Kingston", "property_type": "unit",
                 "label": "11/14 Currie Crescent, Kingston ACT 2604", "units_plan_no": "212",
                 "bedrooms": 2, "latitude": -35.31, "longitude": 149.14},
    "finance": {"purchase_price": 100000, "principal": 80000, "loan_funds": 80000,
                "annual_rate_decimal": 0, "term_months": 100, "acquisition_costs": 1000,
                "immediate_works": 500, "income_monthly": 3000, "living_monthly": 1000,
                "other_debt_monthly": 100, "property_costs_monthly": 200,
                "cash_after_settlement": 4000, "protected_reserve": 3500, "cash_allocated": 21500}
}
SALE = {"status": "settled", "permission_confirmed": True, "address": "3/14 Currie Crescent",
        "settled_on": "2026-06-12", "known_at": "2026-06-14T10:00:00Z", "price": 98000,
        "source_url": "https://example.org/transfer/3", "jurisdiction": "ACT", "suburb": "Kingston",
        "units_plan_no": 212, "bedrooms": 1, "property_type": "apartment"}


def costs(case=None, **options):
    return preoffer_costs(case or deepcopy(CASE), {}, options)


def test_baseline_matches_engine_and_price_sensitivity():
    quote, lower, shock = costs(selling_costs=2000, horizon_months=2)["offer_comparison"]
    existing = evaluate_finance(CASE["finance"])
    assert quote["monthly_repayment"] == existing["repayment"]["monthly_payment"] == "800.00"
    assert quote["monthly_surplus"] == existing["baseline"]["monthly_surplus"] == "900.00"
    assert quote["cash_required"] == "21500.00"
    assert quote["reserve_status"] == "held"
    assert quote["break_even_resale"] == "103900.00"  # price + 1500 entry + 400 holding + 2000 exit
    assert quote["break_even_detail"]["remaining_debt"] == "78400.00"
    assert lower["monthly_repayment"] == "760.00" and lower["cash_required"] == "20500.00"
    assert lower["cash_after_settlement"] == "5000.00" and lower["break_even_resale"] == "98900.00"
    assert Decimal(shock["monthly_repayment"]) > Decimal(quote["monthly_repayment"])
    assert Decimal(shock["break_even_resale"]) > Decimal(quote["break_even_resale"])
    assert shock["first_breach_month"] == 1


def test_levy_hits_once_in_named_month_and_does_not_change_payment():
    q, _, shock = costs(selling_costs=0, horizon_months=3, rate_delta_bps=0,
                        property_cost_factor=1, income_factor=1, special_levy=3000, levy_month=2)["offer_comparison"]
    assert shock["first_breach_month"] == 2 and shock["minimum_cash"] == "2800.00"
    assert shock["ending_cash"] == "3700.00"
    assert shock["monthly_surplus"] == q["monthly_surplus"] == "900.00"
    assert Decimal(shock["break_even_resale"]) - Decimal(q["break_even_resale"]) == 3000


def test_rent_interest_and_net_advances_handled_without_double_counting():
    case = deepcopy(CASE)
    case["finance"].update(principal=81000, annual_rate_decimal="0.06", intended_use="investment",
                           gross_rent_monthly=1000, vacancy_fraction="0.2", management_fraction="0.05")
    q = costs(case, horizon_months=1, selling_costs=0)["offer_comparison"][0]
    assert q["break_even_detail"]["net_rent"] == "760.00"
    assert q["break_even_detail"]["interest_within_payments"] == "405.00"
    assert q["break_even_resale"] == "102345.00"  # +1000 financed fee, +405 interest, +200 ownership, -760 rent


def test_incomplete_metrics_do_not_contaminate_independent_metrics():
    case = deepcopy(CASE)
    del case["finance"]["income_monthly"]
    del case["finance"]["protected_reserve"]
    q = costs(case)["offer_comparison"][0]
    assert q["monthly_repayment"] == "800.00" and q["cash_required"] == "21500.00"
    assert q["monthly_surplus"] is None and q["reserve_status"] == "unknown"
    assert q["break_even_resale"] is None and "selling_costs" in q["missing_inputs"]
    assert costs(case, selling_costs=0)["offer_comparison"][0]["break_even_resale"] == "103900.00"
    case["finance"]["total_liquid_cash"] = 21500
    q = costs(case)["offer_comparison"][0]
    assert q["cash_after_settlement"] is None and "reconcile_cash_double_allocation" in q["missing_inputs"]


def test_future_finance_is_withheld():
    case = deepcopy(CASE)
    case["finance"]["received_at"] = "2026-11-20T12:00:01Z"
    q = costs(case, selling_costs=0)["offer_comparison"][0]
    assert all(q[k] is None for k in ("offer_price", "monthly_surplus", "monthly_repayment", "cash_after_settlement",
                                      "first_breach_month", "break_even_resale"))


def test_comparison_filters_dates_scope_permission_and_duplicate_transactions():
    invalid_changes = [dict(known_at="2026-11-20T12:01:00Z"), dict(status="listed"), dict(price=None),
                       dict(settled_on="2020-01-01"), dict(suburb="Barton"), dict(jurisdiction="NSW"),
                       dict(permission_confirmed=False), dict(address="11/14 Currie Crescent"),
                       dict(source_url="javascript:alert(1)"), dict(property_type="house"), dict(synthetic=True)]
    valid = dict(SALE, address="2 Other Street", units_plan_no=213, latitude=-35.31, longitude=149.14)
    inputs = [SALE, valid, dict(SALE), *(dict(SALE, **p) for p in invalid_changes)]
    result = costs(comparable_sales=inputs)["price_evidence"]
    assert [r["address"] for r in result["comparables"]] == [SALE["address"], valid["address"]]
    same_plan = result["comparables"][0]
    assert same_plan["difference_from_offer"] == "2000.00"
    assert same_plan["matches"] == ["Same suburb", "Same dwelling type", "Units plan matches (212)"]
    assert same_plan["differences"] == ["Bedrooms: subject 2, sale 1"]
    assert same_plan["known_at"] == SALE["known_at"] and same_plan["source_url"] == SALE["source_url"]
    assert len(same_plan["record_id"]) == 64
    assert result["comparables"][1]["distance_m"] == 0
    assert costs(comparable_sales=[SALE, dict(SALE, price=90000)])["price_evidence"]["conflicting_records"] == 1


def test_capture_gap_and_private_document_reference():
    result = costs()["price_evidence"]
    assert result["status"] == "insufficient_evidence" and result["comparables"] == []
    assert result["capture_version"] and result["source_url"].startswith("https://www.accesscanberra.act.gov.au")
    record = dict(SALE, source_url=None, source_ref="My dated settlement extract, page 1")
    assert costs(comparable_sales=[record])["price_evidence"]["comparables"][0]["source_ref"] == record["source_ref"]


def test_subject_aliases_building_only_and_duplicate_unit_not_independent_sales():
    aliases = ["Unit 11, 14 Currie Cres., Kingston ACT", "11 / 14 Currie Cres KINGSTON 2604",
               "14 Currie Crescent, Unit 11", "14 Currie Cres", "Apartment 11 of 14 Currie Crescent"]
    rows = [dict(SALE, address=addr) for addr in aliases]
    rows += [SALE, dict(SALE, address="Unit 3, 14 Currie Cres, Kingston ACT 2604")]
    matches = costs(comparable_sales=rows)["price_evidence"]["comparables"]
    assert len(matches) == 1 and "3" in matches[0]["address"]


def test_invalid_workbench_values_and_pure_inputs():
    with pytest.raises(FinanceInputError):
        costs(horizon_months=0)
    before = deepcopy(CASE)
    costs(CASE, finance={"annual_rate_decimal": 0.05})
    assert before == CASE
