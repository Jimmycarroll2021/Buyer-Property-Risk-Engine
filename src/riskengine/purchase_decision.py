"""Purchaser actions derived from a pinned assessment and its dated location evidence."""
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from .buyer_finance import _cash, _shock


PURCHASE_RULE_VERSION = "1.0.1"
SUPPORTED_PURCHASE_RULE_VERSIONS = frozenset({"1.0.0", PURCHASE_RULE_VERSION})

_EVIDENCE = {
    "Identity": "Match the unit and block on the contract, registered plan and title.",
    "Flood and drainage": "Match each mapped mechanism to the parcel and obtain floor levels and a site drainage inspection.",
    "Bushfire": "Confirm the designation and obtain a site-specific fire assessment for the dwelling.",
    "Ground and contamination": "Obtain a site-specific search or specialist report covering the identified concern.",
    "Building condition": "Commission an inspection of the affected component and obtain a written scope and repair quote.",
    "Insurance": "Obtain a written quote for this address and check exclusions, excesses and the sum insured.",
    "Legal and planning": "Have the conveyancer check the title, lease and registered instruments against the intended use.",
    "Shared ownership": "Review the scheme minutes, capital works fund, levy notices and outstanding defect reports.",
    "Nearby development": "Compare the current approved or proposed plans with the selected dwelling and its access.",
    "Buyer fit": "Record the buyer's intended use and which purchase conditions are essential.",
}


def _item(key, title, detail, action, changes, priority, date, refs, **extra):
    return dict(id=key, title=title, detail=detail, action=action, changes_outcome=changes,
                priority=priority, as_of=date, references=sorted(set(ref for ref in refs if ref)), **extra)


def _finance_issue(rule, details):
    if rule == "FN04":
        gap = _cash(details["funding_gap"])
        return ("Settlement funding falls short",
                f"Confirmed case funds of {_cash(details['allocated_funds'])} leave {gap} unpaid "
                f"against {_cash(details['required_funds'])} due at settlement.",
                "Reconcile the loan, available cash and settlement statement before committing.",
                f"Verified additional funds or a reduction in the amount due of at least {gap} closes this gap.")
    if rule == "FN01":
        short = _cash(-Decimal(details["monthly_surplus"]))
        return ("The opening household budget runs short",
                f"The case spends {short} more than it receives in the first month, including "
                f"a {_cash(details['mortgage_payment'])} loan payment.",
                "Check income, loan terms and recurring costs against statements.",
                f"A verified improvement of {short} per month brings the opening budget to break-even.")
    if rule == "FN03":
        detail = (f"After settlement, cash of {_cash(details['cash_after_settlement'])} is available "
                  f"against the {_cash(details['protected_reserve'])} protected reserve.")
        if "minimum_buffer_months" in details:
            detail += (f" Cash covers {details['months_of_essential_outgoings']} months of outgoings "
                       f"against a {details['minimum_buffer_months']}-month target.")
        return ("Cash reserve is below target", detail, "Reconcile cash left after settlement with reserve needs.",
                "Rerun with documented cash and outgoings that meet the recorded reserve targets.")
    if rule == "FN02":
        detail = (f"Over {details['duration_months']} months with {_shock(details['assumptions'])}, "
                  f"cash reaches {_cash(details['minimum_cash'])} at its lowest.")
        title = "Monthly surplus misses the stress target"
        if details["reserve_breached"]:
            month = details["first_breach_month"]
            when = f"in month {month}" if month else "at settlement"
            short = Decimal(details["protected_reserve"]) - Decimal(details["minimum_cash"])
            title = f"Cash falls below the reserve {when}"
            detail += (f" The first breach occurs {when}. At its lowest, cash is {_cash(short)} "
                       f"below the {_cash(details['protected_reserve'])} reserve.")
        if details["surplus_target_breached"]:
            detail += " The monthly surplus also falls below the recorded target." if details["reserve_breached"] else " The monthly surplus falls below the recorded target."
        return (title, detail, "Rerun this stress period with the written loan terms, household income and available cash.",
                "The full monthly schedule must stay within each recorded cash and surplus target.")
    return ("Modelled exit leaves a shortfall",
            f"At the assumed sale price in month {details['sale_month']}, net proceeds after the debt and "
            f"specified costs are {_cash(details['net_sale_proceeds'])}.",
            "Check the assumed sale price, exit costs and remaining debt.",
            "Rerun with supported inputs showing proceeds sufficient to clear the debt and specified costs.")


def _drivers(assessment, checks, illustrative_finance, demonstration, rule_version):
    grouped = {}
    for row in assessment.get("findings", []):
        rule, priority = row["rule_id"], row["priority"]
        if priority < 2 or rule == "CR01":
            continue
        cid, details = row["check_id"], row["details"]
        finance = row.get("method") == "conditional_financial_calculation"
        illustrative = demonstration or (illustrative_finance and finance)
        refs = [cid, rule, row["finding_id"], *row["evidence_ids"], *row["snapshot_ids"]]
        if finance:
            key = "finance:" + rule
            if rule == "FN02":
                key += ":" + details["scenario_id"]
            title, detail, action, changes = _finance_issue(rule, details)
            if rule == "FN02" and details["reserve_breached"]:
                shorter = [s for s in assessment["financial_scenarios"]["scenarios"]
                           if s.get("state") == "ASSESSED" and not s["reserve_breached"]
                           and s["assumptions"] == details["assumptions"]
                           and s["duration_months"] < details["duration_months"]]
                if shorter:
                    horizon = max(s["duration_months"] for s in shorter)
                    detail += f" Under the same shock, the reserve holds for the shorter {horizon}-month test."
            if illustrative:
                detail = "Illustrative buyer inputs. " + detail
        else:
            # A default factor may be the rule itself (e.g. all inspections). Keep
            # distinct observations visible even when their rule/priority coincides.
            key = row["finding_id"]
            if row["factor_id"] != rule:
                key = "|".join([rule, str(row["factor_id"]), row["summary"]])
            title = checks[cid]["label"]
            detail = row["summary"]
            # LG01 assigns priority 3 to a material *question*. Positive legal
            # effect requires its own evidence, even if the source describes a
            # spatial intersection. Preserve the prior wording for saved replay.
            if (rule_version != "1.0.0" and rule == "LG01" and priority == 3
                    and details.get("evidence_kind") == "restriction" and details.get("reviewed")):
                detail = (f"The review raises an unresolved question about {title.lower()}. "
                          "Its legal effect on the selected property still needs confirmation.")
                if details.get("scope"):
                    detail += f" The source review covered {details['scope']}."
            if details.get("requirement_id"):
                detail += f" The recorded buyer condition is {details['requirement_id']}."
            if demonstration:
                detail = "Demonstration case. " + detail
            action = _EVIDENCE.get(row["domain"], f"Review the source evidence for {title.lower()}.")
            changes = f"Record a dated review resolving the finding for {title.lower()} and rerun the assessment."
        if key in grouped:
            old = grouped[key]
            refs.extend(old["references"])
            if old["priority"] >= priority:
                old["references"] = sorted(set(refs))
                continue
        grouped[key] = _item(key, title, detail, action, changes, priority, assessment["as_of"], refs,
                             illustrative=illustrative, rule_id=rule)
    return sorted(grouped.values(), key=lambda x: (x["illustrative"], -x["priority"], x["rule_id"] != "FN04", x["id"]))


def _assessment_gaps(assessment, checks):
    pending = {}
    for gap in assessment.get("gaps", []):
        cid, reason = gap["check_id"], gap["reason"]
        check = checks[cid]
        refs = [cid, *gap["evidence_ids"], *check["snapshot_ids"]]
        action = _EVIDENCE.get(check["domain"], gap["next_action"])
        key, title, detail = cid, check["label"], gap["summary"]
        if reason == "UNRESOLVED_PROPERTY_ID":
            key, title = "property_identity", "Confirm the property and title"
            detail = "The recorded property identity prevents a reliable match to several parcel and dwelling checks."
            action = _EVIDENCE["Identity"]
        elif cid == "S065":
            part = assessment["financial_scenarios"]["settlement"]
            action = "Obtain the settlement statement, loan confirmation and evidence of cash available at settlement."
            if reason == "FUNDING_UNCONFIRMED":
                detail = (f"Funding is unconfirmed. The case allocates {_cash(part['allocated_funds'])} "
                          f"against {_cash(part['required_funds'])} due, with a provisional shortfall "
                          f"of {_cash(part['funding_gap'])}." if Decimal(part["funding_gap"]) else
                          f"Unconfirmed funds of {_cash(part['allocated_funds'])} cover the estimated "
                          f"{_cash(part['required_funds'])} due.")
            elif part.get("missing_inputs"):
                detail = "Missing settlement inputs include " + ", ".join(x.replace("_", " ") for x in part["missing_inputs"]) + "."
        elif reason in {"REPAIR_COST_UNKNOWN", "COST_EVIDENCE_UNREVIEWED"}:
            action = "Obtain an itemised repair quote tied to the inspected defect."
        elif check["domain"] == "Buyer finance":
            fields = sorted({field.replace("_", " ") for fail in check["failures"] for field in fail.get("missing_inputs", [])})
            if fields:
                detail += ". Required inputs include " + ", ".join(fields) + "."
        if reason == "UNRESOLVED_PROPERTY_ID":
            changes = "A confirmed address, unit and parcel match allows each dependent check to be assessed."
        else:
            changes = f"A dated, case-matched assessment of {title.lower()} resolves this evidence gap."
        if key in pending:
            item = pending[key]
            item["priority"] = max(item["priority"], gap["priority"])
            item["references"] = sorted(set(item["references"] + refs))
            item["required"] |= gap["required"]
            if reason not in item["reasons"]:
                item["reasons"].append(reason)
                item["detail"] += " " + detail
            continue
        pending[key] = _item(key, title, detail, action, changes, gap["priority"], assessment["as_of"], refs,
                             required=gap["required"], reasons=[reason])
    return list(pending.values())


def _location_context(context):
    pending, notes = [], []
    for row in context.get("planning", []):
        source = row.get("source_url", "")
        refs = [source, row.get("geometry_source_url"), row.get("design_source_url")]
        number = parse_qs(urlsplit(source).query).get("da-number", [])
        if number and "distance_m" in row:
            title = row["title"].lower()
            if any(word in title for word in ("lease", "health facility", "parking", "car park", "access", "driveway")):
                action = "Check proposed hours, parking and access routes against the unit entrance and the streets you use."
            elif any(word in title for word in ("storey", "homes", "dwellings", "extension")):
                action = "Check elevations, shadow diagrams and setbacks against the unit's floor, windows and orientation."
            else:
                action = "Check the site plan and works schedule against the unit's outlook, access and construction exposure."
            pending.append(_item("da:" + number[0], row["title"], row["detail"], action,
                                 "A current determination and site-specific plans can establish whether the proposed change affects this unit.",
                                 2, row.get("as_of"), refs, distance_m=row["distance_m"], required=False,
                                 reasons=["NEARBY_APPLICATION"]))
        elif "distance_m" in row:
            notes.append(_item(source, row["title"], row["detail"], "Check delivery milestones and the walking route.",
                               "Reassess accessibility after a confirmed route, service and opening date are available.",
                               None, row.get("as_of"), refs, role="transport_context"))
    for row in context.get("crime", []):
        if row.get("status") == "available":
            notes.append(_item(row["title"], row["title"], row["detail"], "Use this as historical suburb context.",
                               "A newer like-for-like series would update the area comparison only.",
                               None, row["as_of"], [row.get("source_url")], role="historical_area_context"))
    return pending, notes


def purchase_decision(case, assessment, context, *, rule_version=PURCHASE_RULE_VERSION):
    """Summarise the current case. No new score, I/O, or mutation of the core result."""
    if rule_version not in SUPPORTED_PURCHASE_RULE_VERSIONS:
        raise ValueError(f"Unsupported purchase decision rule version {rule_version!r}")
    date = case["as_of"]
    illustrative = bool(case.get("finance_is_illustrative") or case.get("demonstration"))
    planning, notes = _location_context(context)
    drivers, gaps, coverage = [], [], {}
    if assessment:
        checks = {c["check_id"]: c for c in assessment["check_results"]}
        coverage = assessment["coverage"]["full_due_diligence"]
        drivers = _drivers(assessment, checks, illustrative, bool(case.get("demonstration")), rule_version)
        gaps = _assessment_gaps(assessment, checks)
    else:
        gaps.append(_item("assessment", "Run the current assessment", "This case version has no selected assessment.",
                          "Run the assessment for the current case version.",
                          "A completed run links each result to the recorded inputs.", 3, date, [], required=True))
    if illustrative and assessment:
        gaps.append(_item("buyer_inputs", "Replace the illustrative buyer finances",
                          "Loan terms, household income and available cash are example values.",
                          "Enter the buyer's loan, budget, settlement costs and cash, then rerun.",
                          "The revised figures determine which funding and stress constraints apply to this buyer.",
                          3, date, ["financial_scenarios"], required=True))
    gaps.extend(planning)
    first_checks = {"assessment": 0, "property_identity": 1, "S001": 1, "S065": 2, "buyer_inputs": 3,
                    "S017": 4, "S021": 5, "S028": 6, "S029": 7, "S025": 8}
    gaps.sort(key=lambda g: (-g["priority"], first_checks.get(g["id"], 9),
                             "distance_m" not in g, g.get("distance_m", 0), g["id"]))
    binding = next((d for d in drivers if not d["illustrative"]), None)
    if binding:
        if binding["priority"] == 4:
            state, headline = "blocked", "The purchase fails a recorded condition"
        else:
            state, headline = "review", "Resolve the material concerns before committing"
        summary, action = binding["title"] + ". " + binding["detail"], binding["action"]
    elif not coverage.get("complete") or illustrative:
        state, headline = "incomplete", "More evidence is needed before committing"
        summary = "No assessment is available for this case version."
        if assessment:
            summary = (f"{coverage['assessed']} of {coverage['required_applicable']} required applicable checks are complete. "
                       "The available evidence leaves the purchase decision open.")
        if drivers:
            summary += " " + drivers[0]["detail"]
        action = gaps[0]["action"] if gaps else "Confirm the applicable checks and run the assessment."
    else:
        state, headline = "no_material_concern", "No material concern in the assessed scope"
        summary = "All required applicable checks are complete and no assessed purchaser constraint reaches priority 2."
        action = gaps[0]["action"] if gaps else "Review the assessed scope and rerun if the facts or purchase terms change."
    return dict(state=state, headline=headline, summary=summary, next_action=action, as_of=date,
                case_id=case["case_id"], case_version=case.get("case_version"),
                assessment_id=assessment["assessment_id"] if assessment else None, rule_version=rule_version,
                illustrative_finance=illustrative, drivers=drivers, open_checks=gaps, context_notes=notes, coverage=coverage)
