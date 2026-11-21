"""Point-in-time buyer evidence. Monetary outputs are AUD, elapsed days exclude the start day."""
from collections import defaultdict
from decimal import Decimal
from statistics import median
import re

from .finance import FinanceInputError, amount, money
from .preoffer_costs import _instant, _key, _street_identity, _type
from .preoffer_brief import _dated_source, _source_url


MARKETING_SOURCE = "jardine_agent_marketing"
MARKETING_SOURCES = {MARKETING_SOURCE, "act_addresses", "act_blocks", "act_unit", "act_boundary"}
_SELLING = "https://www.domain.com.au/3-9-jardine-street-kingston-act-2604-2021263946"
_OUTGOINGS = "https://www.realestate.com.au/property-apartment-act-kingston-152705636"
_LEASING = "https://www.luxeresidentialcanberra.com.au/property?property_id=1149616/3-9-jardine-street-kingston"
# The saved buyer note gives a local date, so withhold it until the entire Sydney day elapsed.
_NOTE_AVAILABLE = "2026-11-21T13:00:00+00:00"
_AGENT_CHECK = "2026-11-21T20:15:37+00:00"


def _jardine(case):
    prop = case.get("property") or {}
    expected = {"address_id": "140619", "unit_id": "3", "units_plan_no": "402",
                "block_key": "12170260047", "suburb": "kingston", "jurisdiction": "act"}
    if prop.get("label") and _street_identity(prop) != ("9 jardine street", "3"):
        return False
    for key, expected_value in (("latitude", "-35.313696826881085"), ("longitude", "149.1409067822325")):
        if prop.get(key) is not None:
            try:
                coordinate = amount(prop[key], key, minimum=None)
            except FinanceInputError:
                return False
            if abs(coordinate-Decimal(expected_value)) > Decimal("0.00001"):
                return False
    return (case.get("property_id") in {"act-address-140619", "act:block-12170260047:unit-3"}
            and prop.get("identity_confirmed") is True and not prop.get("ambiguous")
            and all(_key(prop.get(key)) == value for key, value in expected.items())
            and _type(prop.get("property_type")) == "unit"
            and prop.get("unit_required") is not False
            and all(_key(prop.get(k, v)) == v for k, v in
                    (("state", "act"), ("division", "kingston"), ("block", "47"), ("section", "26"), ("unit_class", "a")))
            and _instant(case.get("as_of")) is not None
            and _instant(case["as_of"]) >= _instant(_NOTE_AVAILABLE))


def capture_public_marketing(case, restricted=()):
    """Freeze attributed facts for the matched unit, without loading private or live sources."""
    if MARKETING_SOURCES.intersection(restricted) or not _jardine(case):
        return None
    row = {"version": 1, "source_id": MARKETING_SOURCE, "known_at": _NOTE_AVAILABLE, "as_of": "2026-11-21",
            "permission_confirmed": True, "scope": "Attributed numerical facts and a paraphrased layout description",
            "basis": "Historical agent marketing. Confirm the guide, outgoings and approved room use.",
            "address_id": "140619", "guide_low": "1525000.00", "guide_high": "1595000.00",
            "rates_quarterly": "832.00", "levies_quarterly": "3514.00",
            "rates_annual": "3328.00", "levies_annual": "14056.00", "outgoings_subtotal_annual": "17384.00",
            "sale_layout": "Three bedrooms", "leasing_layout": "Two bedrooms and a separate study",
            "guide_source_url": _SELLING, "outgoings_source_url": _OUTGOINGS, "leasing_source_url": _LEASING,
            "references": [_SELLING, _OUTGOINGS, _LEASING]}
    if _instant(case["as_of"]) >= _instant(_AGENT_CHECK):
        row.update(known_at=_AGENT_CHECK, agent_checked_at=_AGENT_CHECK, agent_checked_local_date="2026-11-22",
                   agent_listed_on="2026-10-22",
                   agent_build_year=1986, agent_eer="2.5")
    return row


def _frozen_marketing(row, case, restricted):
    if (not isinstance(row, dict) or not _jardine(case) or MARKETING_SOURCES.intersection(restricted)
            or row.get("version") != 1 or row.get("permission_confirmed") is not True
            or row.get("source_id") != MARKETING_SOURCE or str(row.get("address_id")) != "140619"):
        return None
    known = _instant(row.get("known_at"))
    if not known or known > _instant(case["as_of"]):
        return None
    if any(not _source_url(row.get(key)) for key in ("guide_source_url", "leasing_source_url", "outgoings_source_url")):
        return None
    if any(_number(row.get(k)) is None for k in ("guide_low", "guide_high", "rates_quarterly",
                                                  "levies_quarterly", "outgoings_subtotal_annual")):
        return None
    if _number(row["guide_low"]) > _number(row["guide_high"]):
        return None
    return row


def _number(value, maximum=Decimal("1000000000000")):
    try:
        result = amount(value, "value")
        return result if result <= maximum else None
    except FinanceInputError:
        return None


def _integer(value, maximum):
    num = _number(value, Decimal(maximum))
    return int(num) if num is not None and num == num.to_integral_value() else None


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _ref(row):
    url = row.get("source_url")
    return url if _source_url(url) else _text(row.get("source_ref"))


def _records(data):
    if isinstance(data, dict):
        return [data]
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _inputs(case):
    raw = (case.get("preoffer") or {}).get("underwriting") or {}
    return raw if isinstance(raw, dict) else {}


def underwriting_sources(case):
    """IDs required for rights checks at capture, display and replay."""
    records = [row for rows in _inputs(case).values() for row in _records(rows)]
    if not records:
        return set()
    return {"buyer_underwriting", *[row["source_id"] for row in records
                                   if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", _text(row.get("source_id")))]}


def _known(case, cutoff, restricted):
    known = {}
    if "buyer_underwriting" in restricted:
        return known
    for name, raw in _inputs(case).items():
        rows = []
        for row in _records(raw):
            stamp = _instant(row.get("known_at"))
            if (cutoff and stamp and stamp <= cutoff and _ref(row)
                    and row.get("permission_confirmed") is True
                    and not (row.get("synthetic") or row.get("demonstration"))
                    and not restricted.intersection({_text(row.get("source_id")), _ref(row)})
                    and row.get("subject_property_id", case.get("property_id")) == case.get("property_id")):
                rows.append(row)
        known[name] = sorted(rows, key=lambda row: _instant(row["known_at"]))
    return known


def _section(key, title, detail, action, metrics, refs=(), status=None):
    return {"id": key, "title": title, "status": status or ("partial" if refs else "unknown"),
            "detail": detail, "action": action, "metrics": metrics,
            "references": sorted({ref for ref in refs if ref})}


def _money_text(num):
    return f"A${num:,.0f}"


def _physical(data, cutoff, marketing):
    # Multiple active quotes for the same scope represent alternatives. Keep one only
    # when the buyer identifies a selected quote or all terms agree.
    by_item = defaultdict(list)
    for row in data.get("repair_quotes", []):
        price, due = _number(row.get("amount")), _integer(row.get("due_month"), 600)
        issued, expires = _instant(row.get("quote_on")), _instant(row.get("valid_until"))
        if (row.get("kind") == "trade_quote" and row.get("owner_scope") == "lot" and _text(row.get("item"))
                and price is not None and due is not None and issued and issued <= _instant(row["known_at"])
                and expires and cutoff.date() <= expires.date()):
            by_item[_key(row["item"])].append((row, price, due))
    items, conflicts = [], []
    for key, choices in sorted(by_item.items()):
        selected = [item for item in choices if item[0].get("selected") is True] or choices
        if len({(q[1], q[2], _number(q[0].get("budget"))) for q in selected}) > 1:
            conflicts.append(key)
            continue
        row, price, due = selected[-1]
        budget = _number(row.get("budget"))
        items.append({"item": row["item"], "due_month": due, "amount": money(price), "budget": money(budget),
                      "over_budget": money(max(Decimal(0), price-budget)) if budget is not None else None,
                      "quote_on": row["quote_on"], "valid_until": row["valid_until"], "source": _ref(row)})
    leads = [{"kind": row["kind"], "observation": row["observation"], "source": _ref(row)}
             for row in data.get("inspection_leads", []) if row.get("kind") in
             ("visual", "asbestos", "thermal", "moisture", "structure", "roof", "electrical", "plumbing")
             and _text(row.get("observation"))]
    urgent = [Decimal(item["amount"]) for item in items if item["due_month"] <= 12]
    detail = (f"Listed lot repairs total {_money_text(sum(urgent))} in months 0–12."
              if urgent else "First-year repair exposure is unpriced.")
    if leads:
        detail += f" {len(leads)} recorded inspection lead(s) need confirmation on site."
    if conflicts:
        detail += " Conflicting quotes were excluded from the subtotal."
    overruns = [i for i in items if i["over_budget"] is not None and Decimal(i["over_budget"]) > 0]
    if overruns:
        detail += " Above the recorded budget: " + ", ".join(
            f"{i['item']} by {_money_text(Decimal(i['over_budget']))} (month {i['due_month']})" for i in overruns) + "."
    if marketing and marketing.get("agent_eer") and marketing.get("agent_build_year"):
        detail += (f" The agent gives a {marketing['agent_build_year']} build date and an energy rating of "
                   f"{marketing['agent_eer']}. Check materials, glazing, insulation and the original rating report.")
        leads.append({"kind": "thermal", "observation": f"Advertised EER {marketing['agent_eer']}",
                      "source": marketing["outgoings_source_url"]})
    return _section("physical", "Repairs, asbestos and thermal performance", detail,
                    "Check water entry, roof and services at inspection. Ask for a qualified asbestos assessment, "
                    "the energy-rating report and itemised trade quotes showing responsibility and timing.",
                    {"items": items, "conflicting_items": conflicts, "inspection_leads": leads,
                     "quoted_first_year_subtotal": money(sum(urgent)) if urgent else None},
                    [r["source"] for r in items + leads])


def _cohort(row, prop):
    return all(norm(prop.get(k)) and norm(prop.get(k)) == norm(row.get(k))
               for k, norm in (("suburb", _key), ("property_type", _type), ("bedrooms", _key)))


def _market(data, prop, cutoff):
    """Two fixed 90-day windows. Group by address and settlement before computing statistics."""
    grouped = defaultdict(list)
    for row in data.get("market_dom", []):
        settled = _instant(row.get("settled_on"))
        addr = str(row.get("address_id") or "").strip()
        if (_cohort(row, prop) and addr and addr != str(prop.get("address_id"))
                and row.get("status") == "settled" and settled and settled <= _instant(row["known_at"])
                and (cutoff.date() - settled.date()).days < 180):
            grouped[addr, settled.date()].append(row)
    periods, refs = [[], []], []
    for (_, day), group in grouped.items():
        values = {(_integer(r.get("days_on_market"), 3650), _number(r.get("opening_ask")),
                   _number(r.get("settled_price"))) for r in group}
        if len(values) != 1:
            continue
        periods[int((cutoff.date()-day).days >= 90)].append(values.pop())
        refs.append(_ref(group[-1]))
    stats = []
    for cohort in periods:
        dom = [d for d, _, _ in cohort if d is not None]
        discounts = [(a-p)*100/a for _, a, p in cohort if a and p]
        stats.append({"settlements": len(cohort), "dom_sample": len(dom), "discount_sample": len(discounts),
                      "median_days": float(median(dom)) if len(dom) >= 3 else None,
                      "median_discount_pct": money(median(discounts)) if len(discounts) >= 3 else None})
    inventory = None
    for row in data.get("market_inventory", []):
        end = _instant(row.get("window_end"))
        active = _integer(row.get("active_listings"), 1000000)
        sales = _integer(row.get("window_settlements"), 1000000)
        days = _integer(row.get("window_days"), 365)
        if (_cohort(row, prop) and row.get("complete") is True and end and end <= _instant(row["known_at"])
                and (cutoff.date()-end.date()).days <= 30 and days and days >= 30
                and active is not None and sales is not None and sales >= 3):
            supply = Decimal(active)*days/(Decimal(sales)*Decimal("30.4375"))
            inventory = {"months_supply": money(supply), "active_listings": active, "window_settlements": sales,
                         "window_days": days, "window_end": row["window_end"]}
            refs.append(_ref(row))
    return {"last_90_days": stats[0], "previous_90_days": stats[1], "inventory": inventory,
            "cohort": "Same suburb, dwelling type and bedroom count. At least three observations per statistic."}, refs


def _campaigns(data):
    spans = []
    for row in data.get("listing_periods", []):
        start = _instant(row.get("listed_on"))
        end = _instant(row.get("ended_on") or row.get("observed_active_on"))
        if start and end and start <= end <= _instant(row["known_at"]):
            spans.append((start.date(), end.date(), _ref(row)))
    merged = []
    for start, end, _ in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return {"periods": [[s.isoformat(), e.isoformat()] for s, e in merged],
            "observed_days": sum((e-s).days for s, e in merged) if merged else None,
            "separate_periods": len(merged) if merged else None}, [ref for _, _, ref in spans]


def _negotiation(data, prop, cutoff, prices, marketing):
    campaign, refs = _campaigns(data)
    market, evidence = _market(data, prop, cutoff)
    refs += evidence
    history = []
    for row in data.get("guide_history", []):
        low, high = _number(row.get("low")), _number(row.get("high"))
        if low and high and high >= low:
            history.append((_instant(row["known_at"]), low, high, _ref(row)))
    if marketing:
        history.append((_instant(marketing["known_at"]), _number(marketing["guide_low"]),
                        _number(marketing["guide_high"]), marketing["guide_source_url"]))
        listed, checked = _instant(marketing.get("agent_listed_on")), _instant(marketing.get("agent_checked_at"))
        observed_day = _instant(marketing.get("agent_checked_local_date"))
        if listed and checked and observed_day and listed <= checked <= cutoff:
            campaign["days_since_advertised_start_at_check"] = (observed_day.date()-listed.date()).days
            campaign["advertised_start"] = marketing["agent_listed_on"]
            refs.append(marketing["outgoings_source_url"])
    history.sort()
    by_time = defaultdict(set)
    for when, low, high, ref in history:
        by_time[when].add((low, high))
        refs.append(ref)
    guides = [(when, next(iter(values))) for when, values in sorted(by_time.items()) if len(values) == 1]
    guide = None
    if guides and len(by_time[max(by_time)]) == 1:
        when, (low, high) = guides[-1]
        guide = {"low": money(low), "high": money(high), "known_at": when.isoformat()}
        if len(guides) > 1:
            _, (prior_low, prior_high) = guides[-2]
            guide.update(low_change=money(low-prior_low), high_change=money(high-prior_high))
    # Upstream sales already passed identity, permission and cutoff checks. Require matched bedrooms
    # here before treating a suburb/type sale as evidence about this layout.
    comparable = [r for r in prices.get("comparables", []) if
                  any(m.startswith("Bedrooms matches (") for m in r.get("matches", []))
                  and _number(r.get("price")) and not r.get("differences")]
    matched_prices = [Decimal(str(r["price"])) for r in comparable]
    refs.extend(_ref(r) for r in comparable)
    detail = "A dated guide and matched settled sales are needed to assess the asking range."
    if guide:
        detail = f"Observed guide {_money_text(Decimal(guide['low']))}–{_money_text(Decimal(guide['high']))}. "
        detail += (f"{len(matched_prices)} matched sale(s) span {_money_text(min(matched_prices))}–"
                   f"{_money_text(max(matched_prices))}." if matched_prices else "Matched settled sales are missing.")
        if "low_change" in guide:
            low_delta, high_delta = Decimal(guide["low_change"]), Decimal(guide["high_change"])
            if low_delta < 0 and high_delta <= 0 or low_delta <= 0 and high_delta < 0:
                detail += f" The guide fell by {_money_text(abs(low_delta))} at the lower end and {_money_text(abs(high_delta))} at the upper end."
    if campaign["observed_days"] is not None:
        detail += (f" The documented campaign covers {campaign['observed_days']} elapsed on-market days "
                   f"across {campaign['separate_periods']} separate listing period(s).")
    elif campaign.get("advertised_start"):
        detail += f" The listing gives a {campaign['advertised_start']} start. Withdrawals and relistings remain unverified."
    recent, prior = market["last_90_days"], market["previous_90_days"]
    market["leverage_trend"] = "insufficient_evidence"
    if recent["median_days"] is not None:
        detail += f" Similar homes took a median {recent['median_days']:g} days to sell over the last 90 days."
    if recent["median_days"] is not None and prior["median_days"] is not None:
        detail += f" The preceding 90-day median was {prior['median_days']:g} days."
    if recent["median_discount_pct"] is not None:
        detail += f" Median discount to opening ask was {recent['median_discount_pct']}%."
    if market["inventory"]:
        detail += f" Active supply represents {market['inventory']['months_supply']} months at the observed sales pace."
    if all(row[k] is not None for row in (recent, prior) for k in ("median_days", "median_discount_pct")):
        dom_change = recent["median_days"]-prior["median_days"]
        discount_change = Decimal(recent["median_discount_pct"])-Decimal(prior["median_discount_pct"])
        if dom_change > 0 and discount_change > 0:
            market["leverage_trend"] = "more_buyer_leverage"
            detail += " Slower matched sales and larger discounts support more negotiating room in this cohort."
        elif dom_change < 0 and discount_change < 0:
            market["leverage_trend"] = "less_buyer_leverage"
            detail += " Faster matched sales and smaller discounts point to less negotiating room in this cohort."
        else:
            market["leverage_trend"] = "mixed_or_flat"
            detail += " The two market indicators give a mixed or flat bargaining signal."
    return _section("negotiation", "Price evidence and negotiating leverage", detail,
                    "Get listing and withdrawal dates, guide revisions and matched local inventory, settled prices, "
                    "opening asks and days on market. Ask the agent why the campaign changed and verify the answer.",
                    {"guide": guide, "campaign": campaign, "market": market, "matched_sales": len(comparable),
                     "matched_sale_low": money(min(matched_prices)) if matched_prices else None,
                     "matched_sale_high": money(max(matched_prices)) if matched_prices else None,
                     "guide_low_minus_highest_sale": money(Decimal(guide["low"])-max(matched_prices))
                     if guide and matched_prices else None}, refs)


def _approvals(data, marketing):
    refs, plan, restrictions = [], None, []
    for row in data.get("approved_layout", []):
        if row.get("kind") == "approved_plan" and _text(row.get("approved_use")) and _text(row.get("room")):
            observed = _text(row.get("observed_use"))
            plan = {"room": row["room"], "approved_use": row["approved_use"], "observed_use": observed or None,
                    "use_differs": _key(observed) != _key(row["approved_use"]) if observed else None}
            refs.append(_ref(row))
    for row in data.get("registered_restrictions", []):
        if row.get("kind") == "registered_instrument" and _text(row.get("instrument_id")) and _text(row.get("effect")):
            restrictions.append({"instrument": row["instrument_id"], "recorded_effect": row["effect"], "source": _ref(row)})
            refs.append(_ref(row))
    detail = "Approved room use and any registered burden affecting the buyer's plans need separate documents."
    if marketing:
        detail = "The sale agent described three bedrooms. An earlier leasing agent described two bedrooms and a study."
        refs += [marketing["guide_source_url"], marketing["leasing_source_url"]]
    if plan:
        detail += f" The approved plan records {plan['room']} as {plan['approved_use']}."
        if plan["use_differs"]:
            detail += f" Recorded use at inspection is {plan['observed_use']}. Review the discrepancy before pricing the room."
    if restrictions:
        detail += f" {len(restrictions)} registered instrument(s) identify a restriction for conveyancer review."
    return _section("approvals", "Approved layout and title restrictions", detail,
                    "Compare the occupied layout with the approved plan and permits. Obtain the title, unit plan and "
                    "registered instruments for alterations, access, parking and exclusive-use rights.",
                    {"approved_layout": plan, "registered_restrictions": restrictions}, refs)


def _insurance(data, assessment, cutoff):
    hazards = [{"check_id": r["check_id"], "finding": r.get("summary"), "scope": r.get("details", {}).get("subject_scope"),
                "references": [*r["evidence_ids"], *r["snapshot_ids"]]}
               for r in assessment.get("findings", []) if r.get("check_id") in {"S005", "S008", "S011", "S012"}
               and r.get("evidence_ids") and r.get("snapshot_ids") and not r.get("illustrative")]
    refs = [ref for row in hazards for ref in row["references"]]
    quote = None
    for row in data.get("insurance_quote", []):
        expiry = _instant(row.get("valid_until"))
        if row.get("kind") != "written_quote" or not expiry or expiry.date() < cutoff.date():
            continue
        premium, excess = _number(row.get("annual_premium")), _number(row.get("excess"))
        if premium is None or not _text(row.get("cover_scope")):
            continue
        quote = {"annual_premium": money(premium), "excess": money(excess), "cover_scope": row["cover_scope"],
                 "exclusions": _text(row.get("exclusions")) or None, "valid_until": row["valid_until"]}
        refs.append(_ref(row))
    detail = "Building-level exposure, insurance availability, premium, excess and exclusions need separate evidence."
    if hazards:
        detail = " ".join(f"{r['scope'] or r['check_id']}: {r['finding']}." for r in hazards)
        detail += " Insurance cover needs a written quote or scheme policy."
    if quote:
        detail += f" Written {quote['cover_scope']} quote costs {_money_text(Decimal(quote['annual_premium']))} annually."
    return _section("insurance", "Hazard and insurance exposure", detail,
                    "Compare a site-specific assessment and written insurance terms, including event exclusions, "
                    "rebuild limits and excess. Check exactly what the scheme policy covers.",
                    {"mapped_or_assessed": hazards, "insurance_quote": quote}, refs)


def _strata(data, prop, marketing, cutoff):
    if prop.get("ownership_form") not in {"unit_title", "strata"} and not prop.get("units_plan_no") and (
            prop.get("ownership_form") == "freehold" and _type(prop.get("property_type")) == "house"):
        return _section("strata", "Common works and levies", "The case identifies a freehold house.",
                        "Confirm ownership on title.", {}, status="not_applicable")
    refs, schedule, adopted = [], None, {}
    for row in data.get("strata", []):
        if row.get("kind") == "adopted_lot_levy":
            lot_amount, due = _number(row.get("lot_amount")), _instant(row.get("due_on"))
            resolution = _text(row.get("resolution"))
            if lot_amount is not None and due and resolution:
                adopted[resolution, due] = {"lot_amount": money(lot_amount), "due_on": row["due_on"],
                                            "resolution": resolution, "source": _ref(row)}
                refs.append(_ref(row))
            continue
        end = _instant(row.get("horizon_end"))
        reserve = _number(row.get("available_works_funds"))
        works = row.get("scheduled_works")
        if (row.get("kind") != "reviewed_fund_forecast" or reserve is None or not end
                or end.date() < cutoff.date() or not isinstance(works, list)
                or row.get("schedule_complete") is not True):
            continue
        scoped = []
        for work in works:
            if not isinstance(work, dict):
                break
            cost, due, label = _number(work.get("amount")), _instant(work.get("due_on")), _text(work.get("item"))
            if cost is None or not due or not label or not (_instant(row["known_at"]).date() <= due.date() <= end.date()):
                break
            scoped.append({"item": label, "amount": money(cost), "due_on": work["due_on"]})
        else:
            total = sum((Decimal(item["amount"]) for item in scoped), Decimal(0))
            gap = max(Decimal(0), total-reserve)
            share = _number(row.get("documented_lot_share"), Decimal(1))
            if not share or not _text(row.get("allocation_basis")):
                share = None
            schedule = {"scheduled_works": scoped, "horizon_end": row["horizon_end"], "works_total": money(total),
                        "available_works_funds": money(reserve), "scheme_gap": money(gap),
                        "lot_share": str(share) if share is not None else None,
                        "allocation_basis": row.get("allocation_basis") if share is not None else None,
                        "conditional_lot_contribution": money(gap*share) if share is not None else None}
            refs.append(_ref(row))
    detail = "" if schedule else "Works, available capital funds and this lot's share remain unverified."
    if marketing:
        detail += (f" The agent quoted approximate levies of {_money_text(_number(marketing['levies_quarterly']))} and "
                   f"rates of {_money_text(_number(marketing['rates_quarterly']))} per quarter, "
                   f"{_money_text(_number(marketing['outgoings_subtotal_annual']))} per year together.")
        refs.append(marketing["outgoings_source_url"])
    if schedule:
        detail += (f" Scheduled works by {schedule['horizon_end']} total {_money_text(Decimal(schedule['works_total']))}. "
                   f"The shortfall against earmarked funds is {_money_text(Decimal(schedule['scheme_gap']))}.")
        if schedule["conditional_lot_contribution"] is not None:
            detail += f" Using the documented allocation gives {_money_text(Decimal(schedule['conditional_lot_contribution']))} for the lot if the gap is levied."
    if adopted:
        detail += f" {len(adopted)} separately resolved lot levy payment(s) have documented amounts and due dates. Check for overlap with forecast projects."
    return _section("strata", "Common works and levy exposure", detail,
                    "Reconcile the capital plan, uncommitted funds, committed contracts and levy resolutions. "
                    "Confirm the lot allocation and payment dates in scheme records.",
                    {"forecast": schedule, "resolved_lot_payments": list(adopted.values()),
                     "advertised_annual_rates_and_levies": marketing["outgoings_subtotal_annual"] if marketing else None},
                    refs)


def _micro(data, context, as_of):
    applications = []
    for row in context.get("planning", []):
        distance = _number(row.get("distance_m"))
        if (distance is None or distance > 200 or not _dated_source(row, as_of) or not _text(row.get("status"))
                or row["status"] in {"unknown", "outside_coverage"} or " | DA " not in str(row.get("title", ""))):
            continue
        applications.append({"title": row["title"], "distance_m": float(distance), "status": row["status"],
                             "as_of": row["as_of"], "geometry_basis": row.get("distance_method"),
                             "summary": row.get("detail"), "source": row["source_url"]})
    roads = [{"road": r["road"], "observation": r["observation"], "source": _ref(r)} for r in data.get("road", [])
             if _text(r.get("road")) and _text(r.get("observation"))]
    detail = "Road exposure at the windows and entrance is unverified."
    if roads:
        detail = f"Recorded at {roads[-1]['road']}: {roads[-1]['observation']}."
    detail += (f" The dated snapshot places {len(applications)} application(s) within approximately 200 m of the address point."
               if applications else " No supported application within 200 m is shown in the available snapshot. Coverage is incomplete.")
    return _section("micro_location", "Road exposure and development within 200 m", detail,
                    "Inspect at peak and night-time from the actual rooms. Read DA plans for work hours, traffic, height, "
                    "shadowing, sightlines and any proposed dwellings. Check stage and delivery dates.",
                    {"applications_200m": applications, "road_observations": roads, "coverage": "Partial address-point screen"},
                    [r["source"] for r in roads + applications])


def _exit(data, prop, marketing, costs, survival):
    refs, stock, layout = [], [], []
    for row in data.get("competing_stock", []):
        units = _integer(row.get("dwellings"), 100000)
        if (units and _cohort(row, prop) and _text(row.get("project")) and row.get("stage") in
                {"proposed", "approved", "under_construction", "completed"}):
            stock.append({"project": row["project"], "dwellings": units, "stage": row["stage"],
                          "expected_delivery": _text(row.get("expected_delivery")) or None, "source": _ref(row)})
            refs.append(_ref(row))
    for row in data.get("layout", []):
        if _text(row.get("feature")) and _text(row.get("buyer_constraint")):
            layout.append({"feature": row["feature"], "buyer_constraint": row["buyer_constraint"], "source": _ref(row)})
            refs.append(_ref(row))
    break_evens = [{"months": r["horizon_months"], "break_even_resale": r["break_even_resale"], "scenario": r.get("label")}
                   for r in costs.get("offer_comparison", []) if r.get("horizon_months") in {36, 60}
                   and _number(r.get("break_even_resale")) is not None]
    for row in survival.get("exit_scenarios", []):
        if row.get("years") in {3, 5} and _number(row.get("break_even_resale")) is not None:
            break_evens.append({"months": row["years"]*12, "break_even_resale": row["break_even_resale"],
                                "net_proceeds": row.get("net_proceeds"), "scenario": "Household baseline"})
    detail = "Three-to-five-year resale demand and achievable price remain unknown."
    if marketing:
        detail += " Competing as a two-bedroom-plus-study or a three-bedroom unit changes the relevant buyer pool."
        refs += [marketing["guide_source_url"], marketing["leasing_source_url"]]
    if layout:
        detail += f" Layout constraint: {layout[-1]['feature']} ({layout[-1]['buyer_constraint']})."
    if stock:
        detail += f" {len(stock)} recorded project entry/entries concern comparable stock. Delivery depends on project stage."
    if break_evens:
        detail += " Conditional resale break-even is available for the stated holding period."
    return _section("exit", "Floorplan, competing supply and a 3–5 year exit", detail,
                    "Check approved bedrooms, natural light, access, parking and floorplan against recent settled stock. "
                    "Compare supply by delivery stage and test a 36- or 60-month hold with selling costs.",
                    {"layout_constraints": layout, "competing_stock": stock, "break_even_scenarios": break_evens},
                    refs, status="partial" if refs or break_evens else "unknown")


def buyer_underwriting(case, assessment, context, costs, survival):
    """Derive evidence cards from this case and its frozen, rights-filtered capture."""
    cutoff = _instant(case.get("as_of"))
    restricted = set(context.get("restricted_sources") or ())
    marketing = _frozen_marketing(context.get("public_marketing"), case, restricted)
    data = _known(case, cutoff, restricted)
    prop = case.get("property") or {}
    if prop.get("identity_confirmed") is not True or prop.get("ambiguous") or (context.get("location") or {}).get("issue"):
        marketing, data, context, assessment, costs = None, {}, {}, {}, {}
    if case.get("demonstration") or assessment.get("assessment_mode") == "demonstration":
        assessment = {}
    cards = [_physical(data, cutoff, marketing), _negotiation(data, prop, cutoff, costs.get("price_evidence") or {}, marketing),
             _approvals(data, marketing), _insurance(data, assessment, cutoff), _strata(data, prop, marketing, cutoff),
             _micro(data, context, case.get("as_of")), _exit(data, prop, marketing, costs, survival or {})]
    checks = {"physical": {"S013", "S015", "S021", "S022", "S023", "S024", "S052"},
              "approvals": {"S017", "S018", "S020"}, "insurance": {"S025", "S026", "S027"},
              "strata": {"S028", "S029"}, "micro_location": {"S031", "S036", "S051", "S054"},
              "exit": {"S037", "S040", "S046"}}
    for card in cards:
        findings = [r for r in assessment.get("findings", []) if r.get("check_id") in checks.get(card["id"], ())
                    and r.get("evidence_ids") and r.get("snapshot_ids") and _text(r.get("summary"))]
        if findings:
            card["metrics"]["assessed_findings"] = [{"check_id": r["check_id"], "summary": r["summary"],
                "references": [*r["evidence_ids"], *r["snapshot_ids"]]} for r in findings]
            card["detail"] += " Assessment evidence: " + " ".join(r["summary"] for r in findings)
            card["references"] = sorted(set(card["references"]).union(
                ref for r in findings for ref in [*r["evidence_ids"], *r["snapshot_ids"]]))
            card["status"] = "partial"
    return {"as_of": case.get("as_of"), "sections": cards, "public_marketing": marketing}
