from copy import deepcopy

import pytest

from riskengine import buyer_underwriting as uw


def case(**groups):
    return {"as_of": "2026-11-22T00:00:00Z", "property_id": "act-address-140619",
            "property": {"address_id": 140619, "unit_id": "3", "units_plan_no": 402,
                         "block_key": 12170260047, "jurisdiction": "ACT", "suburb": "Kingston",
                         "property_type": "unit", "identity_confirmed": True, "bedrooms": 2},
            "preoffer": {"underwriting": groups}}


def row(**values):
    return {"source_ref": "Reviewed record", "permission_confirmed": True, "known_at": "2026-11-21", **values}


def sections(subject, context=None, costs=None, assessment=None, survival=None):
    output = uw.buyer_underwriting(subject, assessment or {}, context or {}, costs or {}, survival or {})
    return {s["id"]: s for s in output["sections"]}


def test_public_context_is_private_case_independent_and_replay_uses_frozen_material(monkeypatch):
    c = case()
    before = deepcopy(c)
    capture = uw.capture_public_marketing(c)
    assert capture["outgoings_subtotal_annual"] == "17384.00" and capture["agent_eer"] == "2.5"
    assert not uw.capture_public_marketing(c, {"act_unit"})
    assert not uw.capture_public_marketing(c, {uw.MARKETING_SOURCE})
    assert not uw.capture_public_marketing({**c, "as_of": "2026-11-21T12:00:00Z"})
    earlier = uw.capture_public_marketing({**c, "as_of": "2026-11-21T14:00:00Z"})
    assert "agent_eer" not in earlier
    assert not uw.capture_public_marketing({**c, "property": {**c["property"], "block_key": 194}})
    monkeypatch.setattr(uw, "capture_public_marketing", lambda *_: pytest.fail("queried marketing on replay"))
    out = sections(c, {"public_marketing": capture})
    assert out["negotiation"]["metrics"]["guide"]["high"] == "1595000.00"
    assert "two bedrooms and a study" in out["approvals"]["detail"]
    assert out["negotiation"]["metrics"]["campaign"]["observed_days"] is None
    assert out["physical"]["metrics"]["quoted_first_year_subtotal"] is None
    assert c == before
    for context in [{}, {"public_marketing": capture, "restricted_sources": [uw.MARKETING_SOURCE]},
                    {"public_marketing": {**capture, "address_id": "999"}},
                    {"public_marketing": {**capture, "known_at": "2028-01-01"}}]:
        assert sections(c, context)["negotiation"]["metrics"]["guide"] is None


def test_quote_requires_document_timing_scope_and_permission_no_photo_cost():
    quote = row(kind="trade_quote", owner_scope="lot", item="Hot water", amount=3000,
                budget=2400, due_month=2, quote_on="2026-11-17", valid_until="2026-12-17")
    q = [quote, quote, {**quote, "item": "Roof", "owner_scope": "scheme"},
         {**quote, "item": "Old", "valid_until": "2026-11-20"},
         {**quote, "item": "Future", "known_at": "2027-01-01"},
         {**quote, "item": "Later stage", "due_month": 18, "amount": 5200},
         {**quote, "item": "Prohibited", "permission_confirmed": False},
         {**quote, "item": "Photo", "kind": "inspection_photo"}]
    c = case(repair_quotes=q, inspection_leads=row(kind="visual", observation="Water staining at sill", amount=50000))
    facts = sections(c)["physical"]["metrics"]
    assert facts["quoted_first_year_subtotal"] == "3000.00"
    assert [(r["item"], r["over_budget"]) for r in facts["items"]] == [("Hot water", "600.00"), ("Later stage", "2800.00")]
    assert len(facts["inspection_leads"]) == 1
    q.append({**quote, "amount": 1500})
    assert sections(c)["physical"]["metrics"]["conflicting_items"] == ["hot water"]
    assert sections(c)["physical"]["metrics"]["quoted_first_year_subtotal"] is None
    q[-1]["selected"] = True
    assert sections(c)["physical"]["metrics"]["quoted_first_year_subtotal"] == "1500.00"


def test_policy_ids_and_scope():
    c = case(guide_history=[row(source_id="listing.agent", low=1, high=2),
                            row(source_id="https://not-an-id", subject_property_id="elsewhere", low=3, high=4)])
    assert uw.underwriting_sources(c) == {"buyer_underwriting", "listing.agent"}
    assert uw.underwriting_sources(case()) == set()
    assert sections(c)["negotiation"]["metrics"]["guide"]["low"] == "1.00"
    for denied in ("buyer_underwriting", "listing.agent"):
        assert sections(c, {"restricted_sources": [denied]})["negotiation"]["metrics"]["guide"] is None
    c["property"]["identity_confirmed"] = False
    assert sections(c)["negotiation"]["metrics"]["guide"] is None


def test_market_price_changes_like_stock_only_and_observed_time_excludes_off_market_gaps():
    generic = dict(suburb="Kingston", property_type="apartment", bedrooms=2, status="settled", opening_ask=1000)
    sales = []
    for i in range(3):
        sales.append(row(**generic, address_id=i+1, days_on_market=39+i, settled_price=900,
                         settled_on="2026-11-10"))
        sales.append(row(**generic, address_id=i+11, days_on_market=19+i, settled_price=950,
                         settled_on="2026-07-01"))
    sales += [sales[0], {**sales[0], "address_id": 140619}, {**sales[0], "address_id": 555, "bedrooms": 3},
              {**sales[0], "address_id": 666, "settled_on": "2025-03-04"}]
    inventory = row(**generic, active_listings=21, window_settlements=30, window_days=90,
                    window_end="2026-11-20", complete=True)
    c = case(market_dom=sales, market_inventory=inventory,
             listing_periods=[row(listed_on="2026-10-01", ended_on="2026-10-15"),
                              row(listed_on="2026-10-09", ended_on="2026-10-12"),
                              row(listed_on="2026-11-01", observed_active_on="2026-11-18")],
             guide_history=[row(low=900, high=950), row(known_at="2026-10-01", low=1000, high=1050)])
    costs = {"price_evidence": {"comparables": [{"price": "810", "source_ref": "Settlement", "matches": ["Bedrooms matches (2)"]},
                                                 {"price": "999", "matches": ["Same suburb"]}]}}
    result = sections(c, costs=costs)["negotiation"]["metrics"]
    assert result["campaign"]["observed_days"] == 31 and result["campaign"]["separate_periods"] == 2
    assert result["guide"]["low_change"] == "-100.00" and result["guide_low_minus_highest_sale"] == "90.00"
    market = result["market"]
    assert market["last_90_days"]["median_days"] == 40 and market["previous_90_days"]["median_days"] == 20
    assert market["last_90_days"]["median_discount_pct"] == "10.00"
    assert market["leverage_trend"] == "more_buyer_leverage"
    assert market["inventory"]["months_supply"] == "2.07"
    c["preoffer"]["underwriting"]["market_dom"] = sales[:2]
    inventory["window_end"] = "2026-08-01"
    market = sections(c)["negotiation"]["metrics"]["market"]
    assert market["leverage_trend"] == "insufficient_evidence" and market["inventory"] is None
    assert market["last_90_days"]["median_days"] is None


def test_scheme_liability_needs_documented_allocation_and_excludes_undated_work():
    forecast = row(kind="reviewed_fund_forecast", horizon_end="2028-11-01", available_works_funds=100000,
                   number_of_lots=20, schedule_complete=True,
                   scheduled_works=[{"item": "Lift", "amount": 140000, "due_on": "2027-01-01"},
                                    {"item": "Pool", "amount": 10000, "due_on": "2027-08-01"}])
    c = case(strata=forecast)
    value = sections(c)["strata"]["metrics"]["forecast"]
    assert value["scheme_gap"] == "50000.00" and value["conditional_lot_contribution"] is None
    forecast.update(documented_lot_share="0.06", allocation_basis="Approved contributions schedule, lot 3")
    assert sections(c)["strata"]["metrics"]["forecast"]["conditional_lot_contribution"] == "3000.00"
    forecast["scheduled_works"].append({"item": "Painting", "amount": 10})
    assert sections(c)["strata"]["metrics"]["forecast"] is None


def test_approved_plan_hazards_road_real_da_and_exit_have_separate_scopes():
    c = case(approved_layout=row(kind="approved_plan", room="Room 3", approved_use="Study", observed_use="Bedroom"),
             registered_restrictions=row(kind="marketing", instrument_id="Hint", effect="Easement"),
             road=row(road="Jardine Street", observation="Traffic audible at balcony at 8 am"),
             insurance_quote=row(kind="written_quote", annual_premium=1700, excess=2000,
                                 cover_scope="contents", valid_until="2026-12-01"),
             layout=row(feature="Stairs from garage", buyer_constraint="Limits step-free access"),
             competing_stock=row(suburb="Kingston", property_type="unit", bedrooms=2, project="Nearby", stage="proposed", dwellings=5))
    planning = {"source_url": "https://example.org/da", "as_of": "2026-10-01", "status": "Proposed", "title": "Works | DA 123", "distance_m": 200}
    context = {"planning": [planning, {**planning, "distance_m": 201}, {**planning, "title": "Rail stop"},
                            {**planning, "as_of": "2028-01-01"}]}
    covered = {"check_id": "S011", "summary": "Parcel designation", "details": {"subject_scope": "parcel"},
               "evidence_ids": ["receipt"], "snapshot_ids": ["capture"]}
    survival = {"exit_scenarios": [{"years": 5, "break_even_resale": "680000.00", "net_proceeds": "120000.00"}]}
    out = sections(c, context, assessment={"findings": [covered]}, survival=survival)
    assert out["approvals"]["metrics"]["approved_layout"]["use_differs"] is True
    assert out["approvals"]["metrics"]["registered_restrictions"] == []
    assert out["insurance"]["metrics"]["mapped_or_assessed"][0]["scope"] == "parcel"
    assert out["insurance"]["metrics"]["insurance_quote"]["annual_premium"] == "1700.00"
    assert len(out["micro_location"]["metrics"]["applications_200m"]) == 1
    assert out["exit"]["metrics"]["competing_stock"][0]["stage"] == "proposed"
    assert out["exit"]["metrics"]["break_even_scenarios"][0]["months"] == 60
