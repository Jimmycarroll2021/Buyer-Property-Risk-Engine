"""Point-in-time settled-sale comparison and conditional buyer cash scenarios."""
from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from math import asin, cos, radians, sin, sqrt
from urllib.parse import urlsplit

from .buyer_location import STREET_TYPES
from .finance import FinanceInputError, ONE, PRECISION, ZERO, _budget, amount, loan_schedule, money, months
from .paths import project_root


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        if len(value) != 10:
            return None
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _key(value):
    return " ".join(str(value or "").casefold().split())


def _type(value):
    name = _key(value)
    return {"apartment": "unit", "flat": "unit", "detached house": "house"}.get(name, name)


def _street_identity(record):
    text = _key(record.get("address") or record.get("label")).split("(")[0]
    suburb = _key(record.get("suburb") or record.get("division"))
    if suburb:
        text = re.split(rf"\b{re.escape(suburb)}\b", text)[0]
    text = re.sub(r"\b(?:act|australian capital territory)\b.*$", "", text)
    text = re.sub(r"\s+\d{4}\s*$", "", text).replace(".", "").strip(" ,")
    unit = _key(record.get("unit_id"))
    leading = re.match(r"^(?:unit|apartment|flat|apt|u)\s*(\d+[a-z]?)\b[\s,/;-]*(?:of\s+)?", text)
    slashed = re.match(r"^(\d+[a-z]?)\s*/\s*", text)
    trailing = re.search(r"[,\s]+(?:unit|apartment|flat|apt)\s*(\d+[a-z]?)$", text)
    if leading or slashed:
        match = leading or slashed
        unit, text = match[1], text[match.end():]
    elif trailing:
        unit, text = trailing[1], text[:trailing.start()]
    words = re.findall(r"[a-z0-9'-]+", text)
    if words:
        words[-1] = STREET_TYPES.get(words[-1].upper(), words[-1]).lower()
    return " ".join(words), unit


def _point(record):
    try:
        lat, lon = (float(record[key]) for key in ("latitude", "longitude"))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return radians(lat), radians(lon)
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def _distance(a, b):
    p, q = _point(a), _point(b)
    if p is None or q is None:
        return None
    h = sin((q[0]-p[0])/2)**2 + cos(p[0])*cos(q[0])*sin((q[1]-p[1])/2)**2
    return round(12742000 * asin(sqrt(min(1, h))))


def _accepted_sale(record, subject, cutoff):
    if not isinstance(record, dict) or not cutoff:
        return None
    settled, known = _instant(record.get("settled_on")), _instant(record.get("known_at"))
    if not settled or not known or not (settled <= known <= cutoff) or (cutoff - settled).days > 730:
        return None
    if record.get("permission_confirmed") is not True or _key(record.get("status")) != "settled":
        return None
    if record.get("demonstration") or record.get("synthetic"):
        return None
    address = str(record.get("address") or "").strip()
    source = record.get("source_url")
    try:
        parsed = urlsplit(source) if isinstance(source, str) else None
        if parsed and (parsed.scheme not in ("http", "https") or not parsed.hostname):
            return None
        if not parsed and not str(record.get("source_ref") or "").strip():
            return None
        price = amount(record.get("price"), "settled price")
    except (ValueError, TypeError):
        return None
    if price <= 0 or not address:
        return None
    building, unit = _street_identity(record)
    subject_building, subject_unit = _street_identity(subject)
    same_address = building == subject_building and (not unit or not subject_unit or unit == subject_unit)
    same_plan_unit = (unit and unit == subject_unit and record.get("units_plan_no") is not None
                      and str(record["units_plan_no"]) == str(subject.get("units_plan_no")))
    if same_address or same_plan_unit or (record.get("address_id") and str(record["address_id"]) == str(subject.get("address_id"))):
        return None
    for key in ("jurisdiction", "suburb", "property_type"):
        norm = _type if key == "property_type" else _key
        target = subject.get(key) or (subject.get("division") if key == "suburb" else None)
        if not norm(target) or norm(record.get(key)) != norm(target):
            return None
    return address, settled, price


def _sales(subject, cutoff, offer, capture, submitted):
    # The same address and settlement date is a single transaction. Conflicting prices suppress it.
    transactions = {}
    id_keys = {}
    conflicts = set()
    for record in [*capture.get("records", []), *submitted]:
        eligible = _accepted_sale(record, subject, cutoff)
        if not eligible:
            continue
        address, settled, price = eligible
        key = (*_street_identity(record), settled.date())
        if record.get("address_id"):
            key = id_keys.setdefault((str(record["address_id"]), settled.date()), key)
        if key in transactions and transactions[key][2] != price:
            conflicts.add(key)
        else:
            transactions[key] = (record, address, price, settled)
    ranked = []
    for key, (record, address, price, settled) in transactions.items():
        if key in conflicts:
            continue
        matches = ["Same suburb", "Same dwelling type"]
        differences, missing = [], []
        same_plan = False
        for field, label in (("units_plan_no", "Units plan"), ("bedrooms", "Bedrooms"),
                             ("internal_area_sqm", "Internal area (m²)"), ("parking", "Parking"),
                             ("condition", "Condition")):
            left, right = subject.get(field), record.get(field)
            if left is None or right is None:
                missing.append(label)
            elif str(left).strip().casefold() == str(right).strip().casefold():
                matches.append(f"{label} matches ({right})")
                same_plan |= field == "units_plan_no"
            else:
                differences.append(f"{label}: subject {left}, sale {right}")
        distance = _distance(subject, record)
        record_id = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False).encode("utf-8")).hexdigest()
        row = {"record_id": record_id, "source_id": str(record.get("source_id") or record.get("source_url") or record["source_ref"]),
               "address": address, "price": money(price), "settled_on": settled.date().isoformat(),
               "known_at": record["known_at"], "source_url": record.get("source_url"), "source_ref": record.get("source_ref"),
               "evidence_basis": "Buyer-supplied reviewed record" if record in submitted else "Pinned sale capture",
               "difference_from_offer": money(offer - price) if offer is not None else None,
               "distance_m": distance, "matches": matches, "differences": differences,
               "unverified_attributes": missing}
        rank = (not same_plan, distance if distance is not None else float("inf"),
                -len(matches), -settled.toordinal(), _key(address))
        ranked.append((rank, row))
    rows = [row for _, row in sorted(ranked, key=lambda pair: pair[0])[:5]]
    summary = "No eligible settled comparable is available to establish support for the proposed price."
    if rows:
        prices = [Decimal(row["price"]) for row in rows]
        summary = f"{len(rows)} comparable sale(s) span A${min(prices):,.0f} to A${max(prices):,.0f}."
        if offer is not None:
            position = "above" if offer > max(prices) else "below" if offer < min(prices) else "within"
            summary += f" The offer is {position} that unadjusted range."
        summary += " Condition, size, title and sale timing can change the comparison."
    return {"status": "comparison_available" if rows else "insufficient_evidence", "summary": summary,
            "comparables": rows, "eligible_count": len(ranked), "conflicting_records": len(conflicts),
            "capture_version": capture.get("capture_version"), "source_url": capture.get("source_url"),
            "selection": "Settled in the preceding 730 days, same jurisdiction, suburb and dwelling type. Same plan first, then measured distance, matching attributes and recency. Distances require both coordinates.",
            "action": "Request dated, permitted transfer evidence for similar homes and verify beds, floor area, parking, condition and title before setting the offer."}


def _optional(f, key):
    return amount(f[key], key) if f.get(key) is not None else None


def _sale_costs(f, options):
    fixed = options.get("selling_costs")
    if fixed is None:
        fixed = (f.get("exit") or {}).get("selling_costs") if isinstance(f.get("exit"), dict) else None
    return amount(fixed, "selling_costs") if fixed is not None else None


def _offer_row(base, price, label, horizon, terms, selling):
    f = dict(base)
    gaps = set()
    original = _optional(base, "purchase_price")
    ratio = price / original if price is not None and original else None
    if ratio is None:
        gaps.add("purchase_price")
    for key in ("principal", "loan_funds"):
        # Use the actual loan quote unchanged at the case price; alternatives preserve leverage.
        value = _optional(base, key)
        f[key] = value * ratio if value is not None and ratio is not None else None
        if f[key] is None:
            gaps.add(key)
    buy_costs, works = _optional(f, "acquisition_costs"), _optional(f, "immediate_works")
    for field in ("acquisition_costs", "immediate_works"):
        if f.get(field) is None:
            gaps.add(field)
    required = None
    if None not in (price, f["loan_funds"], buy_costs, works):
        required = price + buy_costs + works - f["loan_funds"]
        if required < ZERO:
            raise FinanceInputError("net loan advance exceeds purchase and acquisition cash needs")
    after, total, allocated = (_optional(f, k) for k in ("cash_after_settlement", "total_liquid_cash", "cash_allocated"))
    allocation_error = bool(None not in (total, allocated, after) and allocated + after > total)
    if allocation_error:
        after = None
        gaps.add("reconcile_cash_double_allocation")
    elif after is not None and ratio is not None and ratio != ONE:
        if f["loan_funds"] is None:
            after = None
        else:
            after += (original - amount(base["loan_funds"], "loan_funds")) - (price - f["loan_funds"])
    elif ratio is None:
        after = None
    if after is None and total is not None and required is not None and not allocation_error:
        after = total - required
    if after is None:
        gaps.add("cash_after_settlement")
    reserve = _optional(f, "protected_reserve")
    if reserve is None:
        gaps.add("protected_reserve")
    if selling is None:
        gaps.add("selling_costs")
    schedule = []
    try:
        schedule = loan_schedule(f, horizon, rate_delta_bps=terms["rate_delta_bps"])
    except FinanceInputError as exc:
        gaps.add(str(exc))
    first = schedule[0]["payment"] if schedule else None
    try:
        budget, missing = _budget(f)
        gaps.update(missing)
    except FinanceInputError as exc:
        budget = {}
        gaps.add(str(exc))
    cash = after
    minimum = after
    monthly = None
    first_breach = 0 if after is not None and reserve is not None and after < reserve else None
    funding_gap = max(ZERO, required-allocated) if required is not None and allocated is not None else None
    can_trace = bool(budget and schedule and cash is not None and reserve is not None and
                     cash >= ZERO and not allocation_error and (funding_gap is None or funding_gap == ZERO))
    if budget and schedule:
        operating = budget["income_monthly"] * terms["income_factor"] + budget["rent_net"] - budget["living_monthly"] - budget["other_debt_monthly"] - budget["property_costs_monthly"] * terms["property_cost_factor"]
        for period in schedule:
            surplus = operating - period["payment"]
            if period["month"] == terms["levy_month"]:
                surplus -= terms["special_levy"]
            if period["month"] == 1:
                monthly = surplus
            if can_trace:
                cash += surplus
                minimum = min(minimum, cash)
                if first_breach is None and cash < reserve:
                    first_breach = period["month"]
    # Calculate asset cash flows separately from household living costs and employment income.
    # Reuse the same property/rental normalization without requiring unrelated household inputs.
    try:
        property_budget, gaps_property = _budget({**f, "income_monthly": 0, "living_monthly": 0, "other_debt_monthly": 0})
        gaps.update(gaps_property)
    except FinanceInputError as exc:
        property_budget = {}
        gaps.add(str(exc))
    break_even = None
    detail = {}
    if required is not None and schedule and property_budget and selling is not None:
        payments = sum(row["payment"] for row in schedule)
        interest = sum(row["interest"] for row in schedule)
        debt = schedule[-1]["closing_balance"]
        holding = property_budget["property_costs_monthly"] * terms["property_cost_factor"] * horizon
        rents = property_budget["rent_net"] * horizon
        levy = terms["special_levy"] if terms["levy_month"] <= horizon else ZERO
        break_even = required + payments + debt + holding + levy + selling - rents
        detail = {k: money(v) for k, v in {"initial_cash_invested": required, "total_loan_payments": payments,
                  "interest_within_payments": interest, "remaining_debt": debt, "holding_costs": holding,
                  "special_levy": levy, "net_rent": rents, "selling_costs": selling}.items()}
    if funding_gap and funding_gap > ZERO:
        gaps.add("settlement_funding_shortfall")
    return {"label": label, "offer_price": money(price), "principal": money(f["principal"]),
            "cash_required": money(required), "cash_after_settlement": money(after),
            "settlement_funding_gap": money(funding_gap), "monthly_repayment": money(first),
            "monthly_surplus": money(monthly), "first_breach_month": first_breach if can_trace else None,
            "reserve_status": ("breached" if first_breach is not None else "held") if can_trace else "unknown",
            "minimum_cash": money(minimum) if can_trace else None, "ending_cash": money(cash) if can_trace else None,
            "break_even_resale": money(break_even), "horizon_months": horizon, "break_even_detail": detail,
            "terms": {k: str(v) if isinstance(v, Decimal) else v for k, v in terms.items()},
            "missing_inputs": sorted(gaps), "funding_confirmed": f.get("funding_confirmed") is True and ratio == ONE}


def preoffer_costs(case, assessment, options=None, *, sales_capture=None):
    """Calculate from this case version, explicit what-ifs and a pinned offline sales capture."""
    options = options or {}
    if not isinstance(options, dict):
        raise FinanceInputError("options must be an object")
    cutoff = _instant(assessment.get("as_of") or case.get("as_of"))
    capture = sales_capture
    if capture is None:
        capture = json.loads((project_root() / "config/preoffer_sales.json").read_text(encoding="utf-8"))
    f = case.get("finance") or {}
    received = _instant(f.get("received_at"))
    withheld = (assessment.get("financial_scenarios", {}).get("repayment", {}).get("reason") == "NOT_KNOWN_AS_OF"
                or (f.get("received_at") is not None and (not received or not cutoff or received > cutoff)))
    overrides = options.get("finance") or {}
    if not isinstance(overrides, dict):
        raise FinanceInputError("finance overrides must be an object")
    override_time = _instant(overrides.get("received_at"))
    if overrides.get("received_at") is not None and (not cutoff or not override_time or override_time > cutoff):
        raise FinanceInputError("finance overrides fall outside the assessment date")
    f = {**({} if withheld else f), **overrides}
    with localcontext() as ctx:
        ctx.prec = PRECISION
        original = _optional(f, "purchase_price")
        offer = _optional(options, "offer_price") if options.get("offer_price") is not None else original
        alternative = _optional(options, "alternative_offer_price")
        if offer == ZERO or alternative == ZERO:
            raise FinanceInputError("offer prices must be greater than zero")
        if alternative is None and offer is not None:
            alternative = Decimal(money(offer * Decimal("0.95")))
        horizon = months(options.get("horizon_months", 12), "horizon_months")
        levy_month = months(options.get("levy_month", 1), "levy_month")
        base_terms = {"rate_delta_bps": ZERO, "income_factor": ONE, "property_cost_factor": ONE,
                      "special_levy": ZERO, "levy_month": levy_month}
        stress = {"rate_delta_bps": amount(options.get("rate_delta_bps", 200), "rate_delta_bps", minimum=None),
                  "income_factor": amount(options.get("income_factor", "0.80"), "income_factor"),
                  "property_cost_factor": amount(options.get("property_cost_factor", "1.20"), "property_cost_factor"),
                  "special_levy": amount(options.get("special_levy", 10000), "special_levy"), "levy_month": levy_month}
        selling = _sale_costs(f, options)
        submitted = options.get("comparable_sales", [])
        if not isinstance(submitted, list) or len(submitted) > 200:
            raise FinanceInputError("comparable_sales must be a list of up to 200 records")
        sales = _sales(case.get("property") or {}, cutoff, offer, capture, submitted)
        rows = [_offer_row(f, p, label, horizon, terms, selling)
                for p, label, terms in [(offer, "Proposed offer", base_terms), (alternative, "Alternative offer", base_terms),
                                        (offer, "Proposed offer under stress", stress)]]
    return {"price_evidence": sales, "offer_comparison": rows,
            "illustrative_finance": bool(case.get("finance_is_illustrative") or case.get("demonstration")),
            "assumptions": [
                "Each offer preserves the original loan-to-price ratio and net-advance ratio. Purchase costs and immediate works stay fixed. Requote duty and fees at the actual offer.",
                "Cash required includes price, purchase costs and immediate works less the net loan advance. Remaining cash starts at the case figure, adjusted for the difference in buyer contribution.",
                "Reserve is tested at settlement and each month end. Month one surplus includes any levy due then. A levy applies once, on top of recurring costs, only in the stressed row.",
                "Cash break-even resale repays the remaining debt and recovers buyer cash invested, mortgage payments, running costs and levy less net rent, plus fixed selling costs. Principal is counted once. Before personal tax, with no discounting, opportunity cost or owner-occupier rent saving.",
                "Alternative price defaults to 5% below the proposed offer. Stress defaults to +200 basis points, 80% of income, 120% of property costs and a A$10,000 levy in month one. These are editable scenarios."
            ]}
