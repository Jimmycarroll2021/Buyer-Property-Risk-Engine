"""Capture address and price evidence once, then derive a reproducible purchase brief."""
from datetime import datetime
import json

from .engine import canonical_hash
from .paths import project_root
from .storage import Conflict

PREOFFER_VERSION = "2.0.0"
IDENTITY_SOURCES = {"act_addresses", "act_blocks", "act_unit", "act_boundary"}
SALES_SOURCE = "act_settled_sales"


def capture_home(case, restricted):
    """Match a buyer-selected address without overriding contradictory case evidence."""
    from .preoffer_locations import retained_property

    prop = case.get("property") or {}
    address_id = prop.get("address_id")
    if (not address_id or prop.get("identity_confirmed") is not True or prop.get("ambiguous")
            or not case.get("preoffer")):
        return {}
    known = retained_property(address_id)
    if not known:
        return {}
    if restricted.intersection(IDENTITY_SOURCES):
        return {"issue": "Retained address and register evidence is restricted."}
    if datetime.fromisoformat(known["retrieved_at"]) > datetime.fromisoformat(case["as_of"]):
        return {"issue": "Retained register evidence postdates this assessment."}
    expected_id = f"act-address-{address_id}"
    alternate = f"act:block-{known.get('block_key')}:unit-{known.get('unit_id')}"
    mismatched = case["property_id"] not in (expected_id, alternate)
    allowed_types = (None, "unit") if str(address_id) == "140619" else (None, "unit", "townhouse")
    mismatched |= prop.get("property_type") not in allowed_types
    mismatched |= prop.get("unit_required") is False
    for key in ("label", "jurisdiction", "state", "suburb", "division", "address_id", "unit_id",
                "units_plan_no", "block_key", "block", "section", "unit_class", "ownership_form", "crs"):
        if prop.get(key) is not None and known.get(key) is not None:
            mismatched |= str(prop[key]).strip().casefold() != str(known[key]).strip().casefold()
    for key in ("latitude", "longitude"):
        if prop.get(key) is not None:
            try:
                mismatched |= not abs(float(prop[key]) - float(known[key])) <= 0.000001
            except (ValueError, TypeError):
                mismatched = True
    if prop.get("parcel_geometry") and prop["parcel_geometry"] != known.get("parcel_geometry"):
        mismatched = True
    if mismatched:
        return {"issue": "The selected address conflicts with the retained address, parcel or unit register."}
    return {"property": known, "source_ids": sorted(IDENTITY_SOURCES)}


def case_with_home(case, home):
    if not home:
        return case
    if home.get("issue"):
        return {**case, "property": {**case["property"], "identity_confirmed": False}}
    return {**case, "property": {**home["property"], **case["property"]}}


def sales_inputs(restricted):
    if SALES_SOURCE in restricted:
        return {"records": [], "status": "restricted", "coverage": "Sales evidence is restricted."}
    return json.loads((project_root() / "config/preoffer_sales.json").read_bytes())


def calculate_survival(case, assessment, options):
    from .household_survival import household_survival
    from .storage import SURVIVAL_AMOUNTS, SURVIVAL_MONTHS

    options = {k: v for k, v in options.items() if v is not None or k not in SURVIVAL_AMOUNTS | SURVIVAL_MONTHS}
    return household_survival(case, assessment, options)


def _buyer_priorities(brief, decision):
    survival, protection, underwriting = (brief[key] for key in ("survival", "protection", "underwriting"))
    date, illustrative = brief["as_of"], brief["illustrative_finance"]
    choices = []
    def add(rank, family, row):
        choices.append((rank, family, row))

    def card(key, title, detail, action, change, kind, scope, refs, sample=False):
        return dict(id=key, title=title, detail=detail, action=action, changes_outcome=change, kind=kind,
                    geography=scope, references=refs, as_of=date, illustrative=sample,
                    confidence=("Illustrative assumptions" if sample else "Conditional on the recorded inputs")
                    if scope == "Buyer household" else "Limited to the cited evidence")

    severity = {r["id"]: r["priority"] for r in decision["drivers"] if not r["illustrative"]}
    for index, row in enumerate(brief["top_three"]):
        priority = severity.get(row["id"], 0)
        family = {"S028": "strata", "S029": "strata", "S065": "cash", "buyer_inputs": "cash",
                  "price_evidence": "negotiation"}.get(row["id"], row["id"])
        rank = 0 if priority == 4 else 4 if priority == 3 else 20 + index
        add(rank, family, row)

    combined = survival["combined"]
    stressed = (survival["state"] == "settlement_shortfall" or combined["first_shortfall_month"] is not None
                or combined["first_reserve_breach_month"] is not None)
    action = ("Reprice the offer or increase available cash, then rerun the same household stress before committing."
              if stressed else "Enter the loan, take-home income, cash reserve and repair allowance to test this offer."
              if survival["state"] == "unknown" else "Confirm the funding and check the reserve under a longer income interruption.")
    add(1 if stressed else 8, "cash", card("household_survival", survival["headline"], survival["detail"], action,
        "Changing the available cash, loan terms, lost income or repair bill changes this result.",
        "Illustrative example" if illustrative else "Household calculation", "Buyer household",
        ["case:finance", "case:preoffer", "survival:combined"], illustrative))

    for row in protection["rows"]:
        if row["status"] == "gap":
            add(5, "protection", card("protection:" + row["id"], row["title"], row["detail"], row["action"],
                "A current written policy and revised household budget can change the uncovered cash requirement.",
                "Illustrative example" if illustrative else "Protection calculation", "Buyer household",
                ["case:buyer_protection", row["source_url"]], illustrative))

    for row in underwriting["sections"]:
        key, m = row["id"], row["metrics"]
        if not row["references"]:
            continue
        rank = 16
        if key == "approvals":
            rank = 3 if m["registered_restrictions"] or (m["approved_layout"] or {}).get("use_differs") else 11
        elif key == "strata":
            rank = 3 if m.get("resolved_lot_payments") or m.get("forecast") else 10
        elif key == "physical":
            rank = 3 if m["quoted_first_year_subtotal"] is not None else 12
        elif key == "negotiation":
            rank = 6 if m["matched_sales"] else 13
        elif key == "insurance" and m["insurance_quote"]:
            rank = 7
        add(rank, key, card("underwriting:" + key, row["title"], row["detail"], row["action"],
            "Verify the cited evidence at the property and update the offer assumptions with dated records.",
            "Property evidence to verify", "Selected dwelling and its market", row["references"]))
    selected, families = [], set()
    for _, family, item in sorted(choices, key=lambda entry: entry[0]):
        if family not in families:
            families.add(family)
            selected.append(item)
        if len(selected) == 3:
            break
    return selected


def apply_preoffer(case, assessment, capture, *, version=PREOFFER_VERSION):
    """Pure rule dispatch for this purchase-brief version, including price calculations."""
    from .preoffer_brief import build_preoffer_brief
    from .preoffer_costs import preoffer_costs

    if version not in ("1.0.0", PREOFFER_VERSION) or not isinstance(capture, dict) or "sales_capture" not in capture:
        raise Conflict("The recorded pre-offer rules or evidence are unavailable for replay")
    options = case.get("preoffer") or {}
    if capture.get("private_sales_withheld"):
        options = {**options, "comparable_sales": []}
    costs = preoffer_costs(case, assessment, options, sales_capture=capture["sales_capture"])
    brief = build_preoffer_brief(case, assessment, assessment["decision_evidence"], costs)
    if version == PREOFFER_VERSION:
        from .buyer_protection import buyer_protection
        from .buyer_underwriting import buyer_underwriting

        context = assessment["decision_evidence"]
        if "public_marketing" not in context or "private_underwriting_withheld" not in capture:
            raise Conflict("The recorded underwriting evidence is unavailable for replay")
        if capture["private_underwriting_withheld"]:
            options = {**options, "underwriting": {}}
        scoped_case = {**case, "preoffer": options}
        survival = calculate_survival(scoped_case, assessment, options)
        protection = buyer_protection(scoped_case, survival)
        underwriting = buyer_underwriting(scoped_case, assessment, context, costs, survival)
        brief.update(rule_version=version, survival=survival, protection=protection, underwriting=underwriting)
        property_decision = {"headline": brief["headline"], "next_action": brief["next_action"]}
        brief["property_decision"] = property_decision
        brief["top_three"] = _buyer_priorities(brief, assessment["purchase_decision"])
        lead = brief["top_three"][0]
        brief.update(headline=("Illustrative scenario: " if lead["illustrative"] else "") + lead["title"],
                     summary=lead["detail"], next_action=lead["action"])
    brief["offer"] = {key: options.get(key) for key in ("offer_price", "price_basis", "intended_use")}
    decision = dict(assessment["purchase_decision"])
    result = {**assessment, "purchase_decision": decision, "preoffer_version": version,
              "preoffer_capture": capture, "preoffer_brief": brief,
              "input_hash": canonical_hash({"purchase_input_hash": assessment["input_hash"],
                                            "preoffer_version": version, "capture": capture})}
    if version == PREOFFER_VERSION:
        result["buyer_summary"] = {
            "household_decision": survival["headline"], "explanation": survival.get("detail"),
            "illustrative_finance": brief["illustrative_finance"],
            "cash_after_settlement": survival["settlement"].get("cash_after_settlement"),
            "total_first_year_cash_out": survival["combined"]["first_year"].get("total_cash_out"),
            "lowest_first_year_cash": survival["combined"].get("minimum_cash"),
            "first_reserve_breach_month": survival["combined"].get("first_reserve_breach_month"),
            "cash_shortfall": survival["combined"].get("cash_shortfall"),
            "property_decision": property_decision["headline"], "property_next_action": property_decision["next_action"],
        }
    for item in (result, decision, brief):
        item.pop("assessment_id", None)
    assessment_id = "assessment:" + canonical_hash(result).split(":")[1]
    for item in (result, decision, brief):
        item["assessment_id"] = assessment_id
    return result


def buyer_first(result):
    """Lead exported JSON with the household outcome without changing the saved payload."""
    first = ("buyer_summary", "weekend", "assessment_id") if "weekend" in result else ("buyer_summary", "preoffer_brief", "assessment_id")
    if "buyer_summary" not in result:
        return result
    return {**{key: result[key] for key in first}, **result}
