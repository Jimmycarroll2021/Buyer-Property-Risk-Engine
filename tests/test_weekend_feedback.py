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
