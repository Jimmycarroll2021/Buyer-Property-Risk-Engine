from copy import deepcopy

from riskengine.engine import evaluate_case
from riskengine.preoffer_brief import build_preoffer_brief


def home(key):
    return {"case_id": key, "property_id": key, "case_version": 1, "as_of": "2026-11-21",
            "owner_tenant_id": "buyer", "property": {"property_type": "townhouse",
            "ownership_form": "unit_title", "identity_confirmed": True},
            "finance": {"purchase_price": "900000"}}


def planning(title, distance, url):
    return {"title": title, "detail": f"The address point is {distance} m from the mapped site.",
            "distance_m": distance, "source_url": url, "as_of": "2026-11-01", "status": "Proposed"}


def brief(case, context=None, costs=None):
    assessment = evaluate_case(case, [])
    inputs = [case, assessment, context, costs]
    original = deepcopy(inputs)
    result = build_preoffer_brief(case, assessment, context or {}, costs)
    assert inputs == original
    return result


def ids(result):
    return [c["id"] for c in result["top_three"]]


def test_same_price_two_homes_different_inspection_questions_without_inventing_site_impacts():
    inner, outer = home("inner"), home("outer")
    nearby = {"planning": [planning("Health facility and car park", 35, "https://example.test/da?da-number=42")]}
    outer_context = {"retained_location_evidence": [{"kind": "bushfire_proximity", "nearby_designation": True,
        "status": "nearby_designation", "detail": "Five mapped polygons within 500 m, none within 200 m.",
        "scope": "500 m from the registered address point", "source_url": "https://example.test/fire",
        "source_ids": ["fire_archive"], "as_of": "2026-11-16"}]}
    inner["buyer_preferences"] = {"priorities": ["access"]}
    a, b = brief(inner, nearby), brief(outer, outer_context)
    assert "da:42" in ids(a) and "bushfire_proximity" in ids(b) and ids(a) != ids(b)
    fire = next(c for c in b["top_three"] if c["id"] == "bushfire_proximity")
    assert "500 m" in fire["geography"] and "unverified" in fire["confidence"]
    for result in (a, b):
        assert len(result["top_three"]) == 3
        assert all(c[k] for c in result["top_three"] for k in ("references", "as_of", "action",
                   "changes_outcome", "geography", "confidence"))
        assert result["coverage"]["total"] == sum(result["coverage"]["states"].values()) == 65
    del outer_context["retained_location_evidence"][0]["source_url"]
    assert "bushfire_proximity" not in ids(brief(outer, outer_context))


def test_buyer_change_and_removed_or_postdated_transport_source_change_the_questions():
    c = home("compare")
    c["buyer_preferences"] = {"planned_works": "extension", "priorities": ["rail"]}
    ctx = {"planning": [planning("Proposed light rail stop", 600, "https://example.test/rail")]}
    first = brief(c, ctx)
    assert "preference:extension" in ids(first) and "https://example.test/rail" in ids(first)
    c["buyer_preferences"]["planned_works"] = "as_is"
    c["requirements"] = [{"requirement_id": "step_free", "essential": True, "description": "Step-free bedroom access"}]
    result = brief(c, ctx)
    assert ids(result)[0] == "requirement:step_free"
    assert result["top_three"][0]["confidence"] == "Unknown" and "preference:extension" not in ids(result)
    for change in ({"source_url": ""}, {"as_of": "2027-01-01"}):
        changed = {"planning": [{**ctx["planning"][0], **change}]}
        cards = brief(c, changed)["top_three"]
        assert any(card["id"] == "preference:rail" and card["confidence"] == "Unknown" for card in cards)
        assert all(card["kind"] != "Transport proposal" for card in cards)


def test_confirmed_settlement_shortfall_precedes_essential_open_question():
    c = home("funding")
    c["requirements"] = [{"requirement_id": "step_free", "essential": True}]
    c["finance"].update(loan_funds="500000", cash_allocated="300000", acquisition_costs="10000",
                        immediate_works="10000", funding_confirmed=True)
    result = brief(c)
    assert result["state"] == "blocked"
    assert ids(result)[0] == "finance:FN04"
    assert "A$120,000.00" in result["top_three"][0]["changes_outcome"]
    c["finance_is_illustrative"] = True
    example = brief(c)
    assert example["state"] != "blocked" and "finance:FN04" not in ids(example)


def test_partial_scope_and_offer_shock_remain_specific_to_selected_inputs():
    c = home("scenario")
    result = evaluate_case(c, [], [{"check_id": "S001"}])
    costs = {"offer_comparison": [{"label": "Proposed offer under stress", "offer_price": "900000",
              "reserve_status": "breached", "first_breach_month": 3}]}
    out = build_preoffer_brief(c, result, {}, costs)
    assert out["coverage"]["total"] == 1
    assert out["top_three"][0]["kind"] == "Conditional calculation"
    assert "month 3" in out["summary"] and out["costs"] == costs


def test_frozen_examples_compare_matched_sites_and_inspection_plans():
    from riskengine.buyer_context import buyer_context
    from riskengine.preoffer_locations import examples, public_evidence, retained_location_evidence, retained_property

    results = {}
    for point in examples()["matches"]:
        address_id = point["address_id"]
        c = home(f"act-address-{address_id}")
        c.update(as_of="2026-11-21T23:59:59Z", property=retained_property(address_id))
        assessed = evaluate_case(c, public_evidence(c))
        ctx = buyer_context(c, assessed)
        ctx["retained_location_evidence"] = retained_location_evidence(c)
        results[point["suburb"]] = build_preoffer_brief(c, assessed, ctx)
        c["buyer_preferences"] = {"planned_works": "extension", "priorities": ["rail"]}
        changed = build_preoffer_brief(c, assessed, ctx)
        assert ids(results[point["suburb"]]) != ids(changed)
        works = next(card for card in changed["top_three"] if card["id"] == "preference:extension")
        assert ("RZ5" if point["suburb"] == "Kingston" else "RZ2") in works["detail"]
        assert any(ref.startswith("https://") for ref in works["references"])
    assert results["Kingston"]["top_three"][0]["kind"] == "Nearby proposal"
    assert results["Isaacs"]["top_three"][0]["id"] == "bushfire_proximity"
    assert ids(results["Kingston"]) != ids(results["Isaacs"])
