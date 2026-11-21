"""Versioned weekend buyer study, composed with the ordinary case and assessment store."""
from copy import deepcopy
import json

from .engine import canonical_hash
from .paths import project_root
from .storage import Conflict, StoreError

STUDY_VERSION = "weekend-buyer/1"
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

    if study.get("version") != STUDY_VERSION:
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
    return {"version": STUDY_VERSION, "bid_policy_version": BID_POLICY_VERSION,
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
