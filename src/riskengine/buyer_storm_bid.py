"""Find the highest tested green or amber offer under a buyer's stated assumptions."""
from __future__ import annotations

from decimal import Decimal, localcontext

from .buyer_storms import evaluate_storms
from .finance import CENT, PRECISION, FinanceInputError, amount, money


MAX_CANDIDATES = 2001
_MAX_AUD = Decimal("1000000000000")
_VETO_LABELS = {"V1": "essential property checks", "V2": "post-settlement cash reserve",
                "V3": "reserve after urgent works", "V4": "income against lean spending"}
_STORM_LABELS = {"A": "rate, insurance and repairs", "B": "highest earner's income loss",
                 "C": "forced sale in month 24"}
_ASSUMPTIONS = (
    "Offers start at the minimum and rise by whole increments up to the maximum. "
    "Only green and amber verdicts qualify. Prices outside this grid are untested.",
    "Each cost band includes its upper price. Duty and other purchase costs are paid "
    "in cash. Each equals its fixed amount plus its decimal ratio times the offer.",
    "LMI is added to the loan. Its ratio applies to the price less the deposit, "
    "before LMI. Deposits and individual charges are rounded to the nearest cent.",
    "Cost bands are buyer-supplied assumptions. Confirm duty, concessions and "
    "price-specific LMI with the relevant authority and lender.",
)


def _number(value, name, *, ratio=False):
    if len(str(value)) > 80:
        raise FinanceInputError(f"{name} is too long")
    result = amount(value, name)
    if ratio:
        if result > 1 or (result and (result.adjusted() < -12 or len(result.as_tuple().digits) > 32)):
            raise FinanceInputError(f"{name} must be a decimal ratio from 0 to 1 with supported precision")
    elif result > _MAX_AUD or result != result.quantize(CENT):
        raise FinanceInputError(f"{name} must be an AUD amount up to {_MAX_AUD} with at most two decimal places")
    return result if result else Decimal(0)


def _charge(entry, name, ratio_field):
    if not isinstance(entry, dict):
        raise FinanceInputError(f"Declare {name}, including an explicit zero if applicable")
    return (_number(entry.get("fixed"), f"{name}.fixed"),
            _number(entry.get(ratio_field), f"{name}.{ratio_field}", ratio=True))


def _policy(search):
    if not isinstance(search, dict):
        raise FinanceInputError("Supply a bid search with price bounds, deposit and cost bands")
    deposit = search.get("deposit")
    if not isinstance(deposit, dict) or deposit.get("mode") not in ("fixed_cash", "ratio"):
        raise FinanceInputError("Declare a fixed_cash or ratio deposit and its value")
    mode = deposit["mode"]
    value = _number(deposit.get("value"), "deposit.value", ratio=mode == "ratio")
    raw_bands = search.get("costs")
    if not isinstance(raw_bands, list) or not 1 <= len(raw_bands) <= MAX_CANDIDATES:
        raise FinanceInputError(f"Supply between 1 and {MAX_CANDIDATES} explicit price bands for duty, acquisition costs and LMI")
    bands = []
    for raw in raw_bands:
        if not isinstance(raw, dict):
            raise FinanceInputError("Each cost band must be an object")
        ceiling = _number(raw.get("up_to_price"), "costs.up_to_price")
        if ceiling <= 0 or (bands and ceiling <= bands[-1][0]):
            raise FinanceInputError("Cost band upper prices must be positive and strictly increasing")
        bands.append((ceiling, _charge(raw.get("duty"), "duty", "price_ratio"),
                      _charge(raw.get("acquisition"), "acquisition", "price_ratio"),
                      _charge(raw.get("lmi"), "lmi", "loan_ratio")))
    return mode, value, bands


def _repriced(profile, policy, price):
    if not isinstance(profile, dict):
        raise FinanceInputError("Supply a storm profile")
    mode, value, bands = policy
    selected = next((band for band in bands if price <= band[0]), None)
    if selected is None:
        raise FinanceInputError("No duty, acquisition and LMI band covers this price")
    ceiling, duty, acquisition, lmi = selected
    with localcontext() as ctx:
        ctx.prec = PRECISION
        deposit = Decimal(money(price * value)) if mode == "ratio" else value
        if deposit > price:
            raise FinanceInputError("The declared fixed deposit exceeds this offer price")
        base_loan = price - deposit
        duty_due = Decimal(money(duty[0] + price * duty[1]))
        purchase_fees = Decimal(money(acquisition[0] + price * acquisition[1]))
        premium = Decimal(money(lmi[0] + base_loan * lmi[1]))
    # Remove reconciled figures from the previous price. The model derives both
    # from the new settlement terms and the same pre-settlement cash balance.
    revised = {k: v for k, v in profile.items() if k not in ("principal", "cash_after_settlement")}
    revised.update(purchase_price=money(price), deposit=money(deposit), acquisition_costs=money(duty_due + purchase_fees),
                   capitalized_lmi=money(premium))
    terms = {"deposit": money(deposit), "duty": money(duty_due), "other_acquisition_costs": money(purchase_fees),
             "capitalized_lmi": money(premium), "loan_before_lmi": money(base_loan),
             "cost_band_up_to": money(ceiling), "deposit_policy": {"mode": mode, "value": str(value)},
             "cost_policy": {"duty": {"fixed": money(duty[0]), "price_ratio": str(duty[1])},
                             "acquisition": {"fixed": money(acquisition[0]), "price_ratio": str(acquisition[1])},
                             "lmi": {"fixed": money(lmi[0]), "loan_ratio": str(lmi[1])}}}
    return revised, terms


def _validate_reference(profile):
    if not isinstance(profile, dict):
        raise FinanceInputError("Supply a storm profile")
    asserted = [key for key in ("principal", "cash_after_settlement") if profile.get(key) is not None]
    if not asserted:
        return
    # Validate at the original purchase terms before dropping dependent figures.
    # A working repricing policy cannot resolve a contradiction in the source.
    settlement_keys = ("purchase_price", "deposit", "capitalized_lmi", "acquisition_costs",
                       "cash_before_settlement", *asserted)
    reference = evaluate_storms({k: profile[k] for k in settlement_keys if k in profile})
    for key in asserted:
        issue = reference["input_issues"].get(key)
        if issue or reference["baseline"][key] is None:
            detail = issue or "the original settlement inputs are incomplete"
            raise FinanceInputError(f"Reconcile reference {key} before changing the price: {detail}")


def profile_at_price(profile, bid_policy, price):
    """Return a repriced storm profile using explicit deposit and cost assumptions.

    A band has an inclusive up_to_price, duty and acquisition objects containing
    fixed and price_ratio, and an lmi object containing fixed and loan_ratio.
    Missing coverage or a malformed policy raises FinanceInputError.
    """
    price = _number(price, "price")
    if price <= 0:
        raise FinanceInputError("Offer prices must be positive")
    _validate_reference(profile)
    return _repriced(profile, _policy(bid_policy), price)[0]


def _reason(model, verdict):
    sections = (("vetoes", "", _VETO_LABELS), ("storms", "Storm ", _STORM_LABELS))
    labels = []
    for section, prefix, names in sections:
        for key, row in model.get(section, {}).items():
            if isinstance(row, dict) and row.get("status") == verdict:
                label = f"{prefix}{key} ({names.get(key, key)})"
                detail = row.get("reason") or row.get("detail")
                if not detail and verdict == "red":
                    if key == "V1":
                        names_of_flags = {"insurable": "insurance unavailable",
                                          "primary_works_approved": "primary works lack approval",
                                          "structural_clear": "structure has an unresolved defect"}
                        detail = ", ".join(names_of_flags.get(flag, flag) for flag, value in row.get("flags", {}).items()
                                           if value is False)
                    elif row.get("available") is not None and row.get("required") is not None:
                        detail = f"A${row['available']} available against A${row['required']} required"
                    elif key == "B" and row.get("runway_months") is not None:
                        detail = f"{Decimal(row['runway_months']):.2f} months of runway for a {row['loss_duration_months']}-month income loss"
                    elif key == "C" and row.get("first_presale_shortfall_month") is not None:
                        detail = f"cash runs short in month {row['first_presale_shortfall_month']}"
                labels.append(f"{label}: {detail}" if isinstance(detail, str) and detail else label)
    missing = model.get("missing_inputs") or []
    if verdict == "unresolved" and missing:
        labels.append("Missing inputs: " + ", ".join(map(str, missing)))
    return "; ".join(labels) or f"Overall storm verdict is {verdict}."


def _test_offer(profile, policy, price):
    try:
        revised, terms = _repriced(profile, policy, price)
    except FinanceInputError as exc:
        return {"price": money(price), "verdict": "unresolved", "reason": str(exc)}, False
    model = evaluate_storms(revised)
    verdict = model.get("verdict", "unresolved")
    if verdict not in ("green", "amber", "red"):
        verdict = "unresolved"
    intrinsic = model.get("vetoes", {}).get("V1", {}).get("status") == "red"
    return {"price": money(price), "verdict": verdict, "reason": _reason(model, verdict),
            "settlement_terms": terms}, intrinsic


def solve_storm_bid(profile, search):
    """Certify a grid maximum by testing downward until the first qualifying offer.

    Any unresolved higher offer prevents a maximum claim. A red V1 veto applies
    to every price. Other vetoes and storms are evaluated again at each price.
    """
    result = {"status": "unknown", "highest_passing_price": None, "highest_tested_passing_price": None,
              "next_failing_price": None, "binding_reason": None, "candidate": None, "next_candidate": None,
              "first_unresolved": None, "evaluations": 0, "max_candidates": MAX_CANDIDATES,
              "intrinsic_veto": None, "grid": None, "assumptions": list(_ASSUMPTIONS)}
    # A confirmed property veto also applies when no cost quote or range exists.
    flag_names = ("insurable", "primary_works_approved", "structural_clear")
    if isinstance(profile, dict) and any(profile.get(name) is False for name in flag_names):
        flags_only = {name: profile.get(name) for name in flag_names}
        model = evaluate_storms(flags_only)
        veto = model["vetoes"]["V1"]
        if veto["status"] == "red":
            result.update(status="no_qualifying_bid", intrinsic_veto="V1",
                          binding_reason="V1 is red at every price. " + _reason(model, "red"))
            return result
    try:
        _validate_reference(profile)
        policy = _policy(search)
        low = _number(search.get("min_price"), "min_price")
        high = _number(search.get("max_price"), "max_price")
        step = _number(search.get("increment"), "increment")
        if low <= 0 or high < low or step <= 0:
            raise FinanceInputError("The minimum price and increment must be positive, with the maximum at or above the minimum")
        count = int((high - low) // step) + 1
        top = low + (count - 1) * step
        result["grid"] = {"min_price": money(low), "max_price": money(high), "increment": money(step),
                          "highest_grid_price": money(top), "candidate_count": count}
        if count > MAX_CANDIDATES:
            raise FinanceInputError(f"This range contains {count:,} offers. Narrow it or increase the increment to test at most {MAX_CANDIDATES:,}.")
    except FinanceInputError as exc:
        result["binding_reason"] = str(exc)
        return result

    above = None
    for offset in range(count):
        offer, intrinsic = _test_offer(profile, policy, top - step * offset)
        result["evaluations"] += 1
        if intrinsic:
            result.update(status="no_qualifying_bid", intrinsic_veto="V1", next_candidate=offer,
                          binding_reason="V1 is red at every price. " + offer["reason"])
            return result
        if offer["verdict"] in ("green", "amber"):
            result.update(candidate=offer, highest_tested_passing_price=offer["price"], next_candidate=above)
            if above and above["verdict"] == "red":
                result["next_failing_price"] = above["price"]
            if result["first_unresolved"]:
                result["binding_reason"] = "A higher offer is unresolved. " + result["first_unresolved"]["reason"]
                return result
            result["highest_passing_price"] = offer["price"]
            if above is None:
                result.update(status="range_ceiling", binding_reason="The highest offer on the requested grid qualifies. Higher offers are untested.")
            else:
                result.update(status="qualified", binding_reason=above["reason"])
            return result
        if offer["verdict"] == "unresolved" and not result["first_unresolved"]:
            result["first_unresolved"] = offer
        above = offer

    result["next_candidate"] = above
    if result["first_unresolved"]:
        result["binding_reason"] = "A qualifying price cannot be established. " + result["first_unresolved"]["reason"]
    else:
        result.update(status="no_qualifying_bid", binding_reason="Every offer on this grid is red. " + above["reason"])
    return result
