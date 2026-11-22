"""Versioned weekend buyer study, composed with the ordinary case and assessment store."""
from copy import deepcopy
import json

from .engine import canonical_hash
from .paths import project_root
from .storage import Conflict, StoreError

STUDY_VERSION = "weekend-buyer/3"
PREVIOUS_STUDY_VERSION = "weekend-buyer/2"
LEGACY_STUDY_VERSION = "weekend-buyer/1"
BID_POLICY_VERSION = "storm-bid-grid/1"
WHAT_IF_FIELDS = {"purchase_price", "cash_before_settlement", "first_year_works"}
EVIDENCE_FIELDS = {"insurable", "primary_works_approved", "structural_clear", "illiquid"}


def examples():
    rows = json.loads((project_root() / "examples/weekend_buyers.json").read_text(encoding="utf-8-sig"))
    return [{key: value for key, value in row.items() if key != "expected"} for row in rows]


def capture(example, changes, evidence_notes=None):
    """Keep the actual seed, explicit overrides and source labels for exact historical replay."""
    if not isinstance(changes, dict) or set(changes) - WHAT_IF_FIELDS - EVIDENCE_FIELDS:
        raise StoreError("Unrecognised weekend buyer input")
    from decimal import Decimal, InvalidOperation

    cleaned = {}
    for key, value in changes.items():
        if key in EVIDENCE_FIELDS:
            if value is not None and type(value) is not bool:
                raise StoreError("Evidence checks require yes, no or unknown")
            cleaned[key] = value
            continue
        if value is None:
            cleaned[key] = None
            continue
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0 or amount > 1_000_000_000 or amount != amount.quantize(Decimal(".01")):
                raise ValueError
            if key == "purchase_price" and amount == 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise StoreError(f"Enter a valid Australian dollar amount for {key.replace('_', ' ')}") from None
        cleaned[key] = format(amount, ".2f")
    profile = {**example["profile"], **cleaned}
    total, urgent = profile.get("first_year_works"), profile.get("urgent_works")
    if total is not None and urgent is not None and Decimal(str(total)) < Decimal(str(urgent)):
        raise StoreError("Total first-year works must include urgent works. "
                         f"Enter at least AUD {Decimal(str(urgent)):,.2f}, or leave the total blank if unknown.")
    notes = evidence_notes or {}
    if not isinstance(notes, dict) or set(notes) - EVIDENCE_FIELDS or any(
            not isinstance(note, str) or not note.strip() or len(note) > 240 for note in notes.values()):
        raise StoreError("A source note must identify the evidence in 240 characters or fewer")
    if set(notes) - set(changes):
        raise StoreError("Source notes must belong to an edited property check")
    return {"version": STUDY_VERSION, "example": deepcopy(example), "changes": cleaned, "source_notes": notes}


def evaluate_study(study):
    from .buyer_storms import evaluate_storms
    from .finance import FinanceInputError
    from .buyer_storm_bid import profile_at_price, solve_storm_bid

    if study.get("version") not in (LEGACY_STUDY_VERSION, PREVIOUS_STUDY_VERSION, STUDY_VERSION):
        raise Conflict("This weekend assessment model is unavailable for replay")
    example = study["example"]
    seed = deepcopy(example["profile"])
    policy = example["bid_policy"]
    changes = study["changes"]
    seed.update({key: value for key, value in changes.items() if key != "purchase_price"})
    target = changes.get("purchase_price", seed.get("purchase_price"))
    price_issue = None
    try:
        if target is None:
            raise FinanceInputError("Enter an offer to calculate its deposit, costs and mortgage.")
        profile = profile_at_price(seed, policy, target)
    except FinanceInputError as exc:
        price_issue = str(exc)
        profile = {**seed, "purchase_price": target, "deposit": None, "acquisition_costs": None,
                   "capitalized_lmi": None, "principal": None, "cash_after_settlement": None}
    result = evaluate_storms(profile)
    ceiling = solve_storm_bid(seed, policy)
    if study["version"] in (PREVIOUS_STUDY_VERSION, STUDY_VERSION):
        # Presentation changes are pinned to v2; v1 calculations and text replay exactly.
        import re
        from decimal import Decimal
        def readable_reason(text):
            return re.sub(r"A\$(-?\d+(?:\.\d+)?)", lambda m: f"AUD {Decimal(m[1]):,.2f}", text)
        for key in ("candidate", "next_candidate", "first_unresolved"):
            if ceiling.get(key):
                ceiling[key]["reason"] = readable_reason(ceiling[key]["reason"])
        ceiling["binding_reason"] = readable_reason(ceiling["binding_reason"])
        if ceiling.get("next_candidate"):
            next_offer = ceiling["next_candidate"]
            ceiling["binding_reason"] = (f"At tested offer AUD {Decimal(next_offer['price']):,.2f} "
                                         f"({next_offer['verdict']}): {ceiling['binding_reason']}")
        result["assumptions"]["A"] += " First-year works means the total including urgent works; urgent works are a subset, not an added bill."
        result["assumptions"]["C"] += " First-year works means the total including urgent works."
    if study["version"] == STUDY_VERSION:
        result["assumptions"]["V1"] = (
            "Yes records clearance for that property check; No is a failed check and makes V1 red at every price. "
            "Unknown leaves that check unresolved unless another known failure already makes V1 red. "
            "Cash and income calculations can be known while a property check is unresolved. "
            "Changing the offer cannot supply missing property evidence. An edited answer is an assumption unless supported by a recorded source.")
        result["assumptions"]["C"] += (
            " Difficult-to-sell Yes selects a declared 15% stress fall; No selects 10%; Unknown leaves the sale-price stress unresolved. "
            "These are worksheet stress assumptions, not sourced market predictions. "
            "Cash after sale equals cash immediately before sale plus net sale equity. "
            "Net sale equity already subtracts selling costs and the mortgage balance. "
            "When equity is negative, cash after sale already funds that shortfall; do not subtract it again.")
    return {"version": study["version"], "bid_policy_version": BID_POLICY_VERSION,
            "bid_policy_hash": canonical_hash(policy), "capture": study, "profile": profile,
            "price_issue": price_issue, "result": result, "ceiling": ceiling, "input_hash": canonical_hash(study)}



def attach_study(case, assessment):
    """Keep all identifiers in the ordinary purchase brief bound to the new result."""
    if "weekend_study" not in case:
        return assessment
    weekend = evaluate_study(case["weekend_study"])
    result = {**assessment, "weekend": weekend, "case_version": case["case_version"],
              "input_hash": canonical_hash({"preoffer_input_hash": assessment["input_hash"],
                                           "weekend_input_hash": weekend["input_hash"]})}
    model = weekend["result"]
    result["buyer_summary"] = {
        "household_decision": model["verdict"], "illustrative_finance": True,
        "cash_after_settlement": model["baseline"]["cash_after_settlement"],
        "normal_monthly_surplus": model["baseline"]["normal_surplus"],
        "tested_offer": weekend["profile"].get("purchase_price"),
        "offer_limit_status": weekend["ceiling"]["status"],
        "highest_passing_price": weekend["ceiling"]["highest_passing_price"],
        "rules": model["rule_version"], "missing_inputs": model["missing_inputs"],
    }
    for key in ("purchase_decision", "preoffer_brief"):
        result[key] = dict(result[key])
    for item in (result, result["purchase_decision"], result["preoffer_brief"]):
        item.pop("assessment_id", None)
    assessment_id = "assessment:" + canonical_hash(result).split(":")[1]
    for item in (result, result["purchase_decision"], result["preoffer_brief"]):
        item["assessment_id"] = assessment_id
    return result
