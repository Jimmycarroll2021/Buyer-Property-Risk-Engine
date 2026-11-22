"""Decision-level regressions from the first three externally reported buyer trials."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from riskengine.engine import canonical_hash
from riskengine.storage import StoreError
from riskengine.weekend_study import capture, evaluate_study, examples


def study(name, **changes):
    example = next(x for x in examples() if x["id"].startswith(name))
    return evaluate_study(capture(example, changes))


def test_total_works_includes_urgent_and_impossible_subset_is_rejected():
    kambah = next(x for x in examples() if x["id"].startswith("kambah"))
    with pytest.raises(StoreError, match="Total first-year works must include urgent works"):
        capture(kambah, {"first_year_works": 37999})
    equal = evaluate_study(capture(kambah, {"first_year_works": 38000}))
    assert equal["profile"]["first_year_works"] == "38000.00"
    revised = study("kambah", purchase_price=550000, cash_before_settlement=210000, first_year_works=48000)
    assert revised["result"]["verdict"] == "amber"
    assert revised["profile"]["urgent_works"] == 38000
    assert revised["result"]["storms"]["A"]["cash_month3"] == "43074.37"
    assert revised["ceiling"]["highest_passing_price"] == "720000.00"
    assert revised["ceiling"]["next_failing_price"] == "725000.00"
    assert "AUD 725,000.00" in revised["ceiling"]["binding_reason"]


def test_distinct_grid_offer_is_named_without_changing_main_cash():
    revised = study("ngunnawal", purchase_price=740000, cash_before_settlement=310000, first_year_works=40000)
    assert revised["result"]["baseline"]["cash_after_settlement"] == "-11000.00"
    reason = revised["ceiling"]["binding_reason"]
    assert "AUD 600,000.00 (red)" in reason
    assert "In the bid search, search-grid offer" in reason
    assert "lowest offer on the grid; no search-grid offer qualifies" in reason
    assert "Your entered offer is AUD 740,000.00" in reason
    assert "next higher" not in reason
    assert "AUD -7,500.00 available" in reason
    assert "AUD 11,157.30 required" in reason
    missing = study("ngunnawal", first_year_works=None)
    assert missing["result"]["verdict"] == "unresolved"
    assert missing["ceiling"]["status"] == "unknown"


def test_weston_cover_gap_and_endpoint_qualifies_amber():
    original = study("weston")
    revised = study("weston", purchase_price=740000)
    assert original["result"]["storms"]["B"]["tpd_cover_gap"] == "15000.00"
    assert revised["result"]["storms"]["B"]["tpd_cover_gap"] == "0.00"
    assert original["ceiling"]["status"] == "range_ceiling"
    assert original["ceiling"]["candidate"]["verdict"] == "amber"


def test_pinned_v1_capture_replays_original_shape_and_raw_reason():
    example = next(x for x in examples() if x["id"].startswith("ngunnawal"))
    legacy = {"version": "weekend-buyer/1", "example": deepcopy(example),
              "changes": {"purchase_price": "740000.00", "cash_before_settlement": "310000.00", "first_year_works": "40000.00"}, "source_notes": {}}
    before = deepcopy(legacy)
    result = evaluate_study(legacy)
    assert legacy == before
    assert result["version"] == "weekend-buyer/1"
    assert result["input_hash"] == canonical_hash(legacy)
    assert "A$-7500.00" in result["ceiling"]["binding_reason"]
    assert "At tested offer" not in result["ceiling"]["binding_reason"]
    assert "subset" not in result["result"]["assumptions"]["A"]


def test_five_full_legacy_results_match_pre_change_candidate_hashes():
    expected = json.loads((Path(__file__).parent / "fixtures/weekend_v1_hashes.json").read_text())
    for example, receipt in zip(examples(), expected, strict=True):
        legacy = {"version": "weekend-buyer/1", "example": example, "changes": {}, "source_notes": {}}
        assert example["id"] == receipt["example"]
        assert canonical_hash(evaluate_study(legacy)) == receipt["legacy_result_hash"]


def test_five_full_v2_results_replay_exactly_after_explanation_revision():
    expected = json.loads((Path(__file__).parent / "fixtures/weekend_v2_hashes.json").read_text())
    for example, receipt in zip(examples(), expected, strict=True):
        previous = {"version": "weekend-buyer/2", "example": example, "changes": {}, "source_notes": {}}
        assert example["id"] == receipt["example"]
        assert canonical_hash(evaluate_study(previous)) == receipt["legacy_result_hash"]


def test_v3_results_and_changed_offer_property_states_replay_exactly():
    expected = json.loads((Path(__file__).parent / "fixtures/weekend_v3_hashes.json").read_text())
    for receipt in expected:
        assert canonical_hash(evaluate_study(receipt["capture"])) == receipt["result_hash"]


def test_search_reason_names_actual_unknown_and_next_higher_sources():
    kambah = study("kambah")
    reason = kambah["ceiling"]["binding_reason"]
    assert "search-grid offer AUD 585,000.00 (red)" in reason
    assert "next higher grid offer above the highest qualifying grid offer" in reason
    assert "Your entered offer is AUD 620,000.00" in reason
    braddon = study("braddon")
    assert braddon["ceiling"]["next_candidate"]["price"] == "520000.00"
    assert braddon["ceiling"]["first_unresolved"]["price"] == "820000.00"
    reason = braddon["ceiling"]["binding_reason"]
    assert "search-grid offer AUD 820,000.00 (unresolved)" in reason
    assert "Your entered offer is AUD 640,000.00" in reason
    assert "520,000" not in reason and "next higher" not in reason
    no = study("braddon", structural_clear=False)["ceiling"]
    assert no["next_candidate"] is None
    assert "failed property check applies at every price" in no["binding_reason"]
    assert "search-grid offer AUD" not in no["binding_reason"]
    assert "Your entered offer is AUD 640,000.00" in no["binding_reason"]


def test_belconnen_cash_after_sale_already_funds_negative_equity():
    from decimal import Decimal
    original = study("belconnen")
    c = original["result"]["storms"]["C"]
    assert original["version"] == "weekend-buyer/4"
    assert c["net_sale_equity"] == "-40473.40"
    assert c["cash_after_sale"] == "37059.33"
    assert abs(Decimal(c["cash_month24"]) + Decimal(c["net_sale_equity"]) - Decimal(c["cash_after_sale"])) <= Decimal(".01")
    assert "do not subtract it again" in original["result"]["assumptions"]["C"]
    revised = study("belconnen", purchase_price=450000, cash_before_settlement=160000, first_year_works=9000)
    assert revised["result"]["verdict"] == "amber"
    assert revised["result"]["storms"]["C"]["cash_after_sale"] == "142269.50"
    no = study("belconnen", illiquid=False)
    assert no["result"]["storms"]["B"] == original["result"]["storms"]["B"]
    assert Decimal(no["result"]["storms"]["C"]["dip_decimal"]) == Decimal(".10")
    assert no["result"]["storms"]["C"]["cash_after_sale"] == "66309.33"
    missing = study("belconnen", illiquid=None)["result"]["storms"]["C"]
    assert missing["sale_price"] is None and missing["cash_after_sale"] is None


def test_braddon_property_unknown_does_not_erase_known_cash():
    original = study("braddon")
    assert original["result"]["verdict"] == "unresolved"
    assert original["result"]["baseline"]["cash_after_settlement"] == "101500.00"
    assert original["result"]["vetoes"]["V1"]["status"] == "unresolved"
    revised = study("braddon", purchase_price=635000, cash_before_settlement=411000, first_year_works=7000)
    assert revised["result"]["verdict"] == "unresolved"
    assert revised["result"]["baseline"]["cash_after_settlement"] == "112625.00"
    yes = study("braddon", structural_clear=True)
    assert yes["result"]["verdict"] == "green"
    assert yes["ceiling"]["status"] == "range_ceiling"
    assert yes["ceiling"]["highest_passing_price"] == "820000.00"
    no = study("braddon", structural_clear=False)
    assert no["result"]["verdict"] == "red"
    assert no["ceiling"]["intrinsic_veto"] == "V1"
    assert no["result"]["baseline"] == original["result"]["baseline"]
