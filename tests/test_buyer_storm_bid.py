from copy import deepcopy

import pytest

from riskengine.buyer_storm_bid import MAX_CANDIDATES, profile_at_price, solve_storm_bid
from riskengine.buyer_storms import evaluate_storms
from riskengine.finance import FinanceInputError


def household():
    return dict(cash_before_settlement=250000, annual_rate_decimal=".06", term_months=360,
                lean_living_monthly=2500, normal_living_monthly=3000, locked_commitments_monthly=0,
                property_costs_monthly=750, insurance_annual=1200, urgent_works=0, first_year_works=0,
                loss_duration_months=4, redundancy_available=0, leave_available=0, ip_wait_months=3,
                death_cover=1000000, tpd_cover=1000000, earner_incomes_monthly=[6500, 3000],
                insurable=True, primary_works_approved=True, structural_clear=True, illiquid=False)


def band(ceiling, duty_fixed=0):
    return dict(up_to_price=ceiling, duty=dict(fixed=duty_fixed, price_ratio=".04"),
                acquisition=dict(fixed=2000, price_ratio=0), lmi=dict(fixed=0, loan_ratio=0))


def search():
    return dict(min_price=200000, max_price=1600000, increment=50000,
                deposit=dict(mode="ratio", value=".20"), costs=[band(1600000)])


def test_last_amber_price_and_adjacent_red_verified_by_full_evaluator():
    profile, policy = household(), search()
    result = solve_storm_bid(profile, policy)
    assert result["status"] == "qualified"
    assert (result["highest_passing_price"], result["next_failing_price"]) == ("950000.00", "1000000.00")
    for key, expected in (("candidate", "amber"), ("next_candidate", "red")):
        row = result[key]
        assert evaluate_storms(profile_at_price(profile, policy, row["price"]))["verdict"] == row["verdict"] == expected
    assert "post-settlement cash reserve" in result["binding_reason"]
    assert "8000.00" in result["binding_reason"]


def test_non_monotone_duty_bands_leave_qualifying_island_above_failure():
    profile = household()
    policy = dict(search(), min_price=500000, max_price=1000000, increment=100000,
                  costs=[band(500000), band(700000, 500000), band(1000000)])
    sequence = [evaluate_storms(profile_at_price(profile, policy, price))["verdict"]
                for price in range(500000, 1000001, 100000)]
    assert sequence == ["amber", "red", "red", "amber", "amber", "red"]
    result = solve_storm_bid(profile, policy)
    assert result["highest_passing_price"] == "900000.00"
    assert result["next_failing_price"] == "1000000.00"


def test_deposit_costs_and_lmi_reprice_without_changing_original_profile():
    profile = dict(household(), purchase_price=400000, deposit=80000, acquisition_costs=7000,
                   principal=323000, capitalized_lmi=3000, cash_after_settlement=163000)
    policy = search()
    policy["costs"][0]["lmi"] = dict(fixed=50, loan_ratio=".01")
    policy["costs"][0]["acquisition"]["price_ratio"] = ".001"
    before = deepcopy(profile), deepcopy(policy)
    revised = profile_at_price(profile, policy, 500000)
    assert (revised["deposit"], revised["acquisition_costs"], revised["capitalized_lmi"]) == (
        "100000.00", "22500.00", "4050.00")
    assert "principal" not in revised and "cash_after_settlement" not in revised
    outcomes = evaluate_storms(revised)["baseline"]
    assert outcomes["principal"] == "404050.00" and outcomes["cash_after_settlement"] == "127500.00"
    assert (profile, policy) == before
    fixed = dict(policy, deposit={"mode": "fixed_cash", "value": 50000})
    assert profile_at_price(profile, fixed, 500000)["deposit"] == "50000.00"
    assert profile_at_price(profile, fixed, 600000)["capitalized_lmi"] == "5550.00"
    with pytest.raises(FinanceInputError, match="fixed deposit exceeds"):
        profile_at_price(profile, fixed, 49999)


@pytest.mark.parametrize("field,bad_value", [
    ("principal", 99999), ("cash_after_settlement", 1), ("capitalized_lmi", None),
    ("cash_before_settlement", None),
])
def test_conflicting_or_unverifiable_reference_assertion_blocks_offer(field, bad_value):
    profile = dict(household(), purchase_price=200000, deposit=40000, acquisition_costs=10000,
                   principal=160000, capitalized_lmi=0, cash_after_settlement=200000)
    profile[field] = bad_value
    policy = dict(search(), min_price=200000, max_price=200000)
    result = solve_storm_bid(profile, policy)
    assert result["status"] == "unknown" and result["highest_passing_price"] is None
    assert "Reconcile reference" in result["binding_reason"] and result["evaluations"] == 0
    with pytest.raises(FinanceInputError, match="Reconcile reference"):
        profile_at_price(profile, policy, 200000)


def test_unresolved_higher_costs_preserve_best_known_offer_without_claiming_maximum():
    policy = dict(search(), min_price=850000, max_price=1000000, costs=[band(950000)])
    result = solve_storm_bid(household(), policy)
    assert result["status"] == "unknown" and result["highest_passing_price"] is None
    assert result["highest_tested_passing_price"] == "950000.00"
    assert result["next_failing_price"] is None
    assert result["first_unresolved"]["price"] == "1000000.00"
    assert "No duty" in result["binding_reason"]


def test_intrinsic_veto_survives_missing_finances_and_all_red_search_is_bounded():
    for incomplete in (search(), {}, dict(search(), costs=[band(1)])):
        result = solve_storm_bid({"insurable": False}, incomplete)
        assert result["status"] == "no_qualifying_bid" and result["evaluations"] == 0
        assert result["intrinsic_veto"] == "V1"
        assert result["highest_passing_price"] is None and "insurance unavailable" in result["binding_reason"]
    policy = dict(search(), min_price=1000000, max_price=1100000)
    red = solve_storm_bid(household(), policy)
    assert red["status"] == "no_qualifying_bid" and red["evaluations"] == 3
    assert red["candidate"] is None and "Every offer" in red["binding_reason"]
    partial = solve_storm_bid({}, policy)
    assert partial["status"] == "unknown" and "Missing inputs" in partial["binding_reason"]


def test_off_grid_ceiling_and_oversized_search():
    profile, policy = household(), dict(search(), min_price=600000, max_price=699999, increment=50000)
    result = solve_storm_bid(profile, policy)
    assert result["status"] == "range_ceiling" and result["highest_passing_price"] == "650000.00"
    assert result["evaluations"] == 1 and result["next_failing_price"] is None
    policy.update(max_price=600000 + MAX_CANDIDATES, increment=1)
    over = solve_storm_bid(profile, policy)
    assert over["status"] == "unknown" and over["grid"]["candidate_count"] == MAX_CANDIDATES + 1
    assert over["evaluations"] == 0 and "increase the increment" in over["binding_reason"]


@pytest.mark.parametrize("policy", [
    dict(search(), deposit={"mode": "ratio", "value": 1.01}), dict(search(), deposit={}),
    dict(search(), costs=[dict(band(1000000), duty=None)]),
    dict(search(), costs=[dict(band(1000000), lmi={"fixed": 0})]),
    dict(search(), costs=[band(1000000), band(1000000)]),
    dict(search(), increment=0), dict(search(), min_price="1.002"), dict(search(), max_price=float("inf")),
])
def test_missing_or_invalid_assumptions_do_not_generate_a_bid(policy):
    result = solve_storm_bid(household(), policy)
    assert result["status"] == "unknown" and result["evaluations"] == 0
    assert result["highest_passing_price"] is None and result["binding_reason"]
