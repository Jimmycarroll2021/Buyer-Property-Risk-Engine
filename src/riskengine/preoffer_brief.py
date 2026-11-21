"""Pre-offer questions derived only from the supplied case and frozen evidence."""
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .buyer_finance import _cash
from .purchase_decision import purchase_decision


BRIEF_VERSION = "1.0.0"


def _words(value):
    return str(value or "").lower().replace("_", " ").replace("-", " ")


def _topics(value):
    text = _words(value)
    matches = {
        "step_free": ("step free", "wheelchair", "no stairs", "level entry"),
        "rail": ("rail", "tram", "public transport", "commut"),
        "activity": ("activity", "noise", "quiet", "traffic", "construction", "outlook", "privacy"),
        "access": ("access", "parking", "driveway", "walking", "pedestrian"),
    }
    return {topic for topic, words in matches.items() if any(word in text for word in words)}


def _source_url(ref):
    if not isinstance(ref, str):
        return False
    try:
        parsed = urlsplit(ref)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def _dated_source(row, cutoff):
    def instant(value):
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    try:
        return _source_url(row.get("source_url")) and instant(row["as_of"]) <= instant(cutoff)
    except (KeyError, TypeError, ValueError):
        return False


def _geography(cid, details):
    if cid in {"S028", "S029"}:
        return "Common property / owners corporation"
    if cid in {"S017", "S018", "S019", "S020"}:
        return "Title / parcel and proposed use"
    if cid in {"S030", "S031", "S034", "S035", "S036", "S050", "S051"}:
        return "Nearby site or access route"
    if "S037" <= cid <= "S049" or cid in {"S016", "S032", "S033", "S053"}:
        return "Area / market context"
    if "S055" <= cid <= "S060" or cid == "S065":
        return "Buyer household"
    if details.get("subject_scope"):
        return f"Mapped {details['subject_scope']}"
    if cid in {"S001", "S002", "S003", "S004"}:
        return "Selected dwelling and parcel"
    if cid == "buyer_inputs":
        return "Buyer household"
    return "Selected dwelling"


def _card(row, *, kind, geography, confidence, refs=None, detail=None):
    return dict(id=row["id"], title=row["title"], kind=kind,
                detail=detail or row["detail"], confidence=confidence, geography=geography,
                references=sorted(set(row["references"] if refs is None else refs)),
                action=row["action"], changes_outcome=row["changes_outcome"], as_of=row.get("as_of"),
                illustrative=bool(row.get("illustrative")))


def _headline_card(key, title, detail, action, reversal, geography, refs, date):
    return dict(id=key, title=title, kind="Open question", detail=detail, action=action,
                changes_outcome=reversal, geography=geography, references=sorted(set(refs)),
                confidence="Unknown", as_of=date, illustrative=False)


def _coverage(checks, aggregate):
    rows = [{key: check.get(key) for key in
             ("check_id", "label", "domain", "state", "complete", "reason", "required", "critical")}
            for check in checks]
    return {**aggregate, "total": len(rows), "states": dict(Counter(row["state"] for row in rows)),
            "checks": rows}


def _driver_candidates(case, decision, findings, prefs):
    candidates = []
    for item in decision["drivers"]:
        entries = [findings[ref] for ref in item["references"] if ref in findings]
        if not entries:
            continue
        evidence = entries[0]
        cid, details = evidence["check_id"], evidence["details"]
        finance = evidence.get("method") == "conditional_financial_calculation"
        sourced = all(f["evidence_ids"] and f["snapshot_ids"] for f in entries)
        geo = _geography(cid, details)
        kind = "Conditional calculation" if finance else "Assessed finding"
        priority = item["priority"]
        rank = 25 - priority
        family = cid
        if finance:
            family = evidence["rule_id"]
            rank = 2 if family == "FN04" else 6
        elif priority == 4:
            rank = 3
        elif priority == 3:
            rank = 12
        card = _card(item, kind=kind, geography=geo, confidence=evidence.get("confidence", "Unknown"))
        if finance:
            card["references"].append(f"case:{case['case_id']}:finance")
        if cid == "S018" and evidence["rule_id"] == "LG01" and priority == 3:
            card.update(kind="Open question", title="Does the mapped encumbrance affect the intended use?"
                        if "map" in _words(details.get("scope")) or "spatial" in _words(details.get("scope"))
                        else "Does the encumbrance affect the intended use?",
                        changes_outcome="A current registered instrument and plan locating its burden relative to the proposed use resolve this question.")
            if "extension" in prefs:
                card["title"] = "Would the proposed extension cross an encumbrance?"
                card["action"] = "Give the conveyancer the extension footprint, registered instruments and unit plan to check the works and maintenance access."
                family, rank = "works", 8
            elif "as_is" in prefs:
                card["action"] = "Check whether the instrument changes existing access, maintenance obligations or use of the home as it stands."
        if cid == "S030":
            family = "activity"
            if prefs & {"activity", "access"}:
                rank = 13
        if item["illustrative"]:
            card["kind"] = "Illustrative example"
            rank = 95
        elif not (sourced or finance):
            card = _headline_card(cid, f"Verify {item['title'].lower()}",
                    "The saved finding lacks a linked observation or source snapshot.",
                    item["action"], item["changes_outcome"], geo, [cid], item["as_of"])
            rank = 42
        candidates.append((rank, family, card))
    return candidates


def _buyer_questions(case, prefs, requirements, findings, checks, context):
    date = case["as_of"]
    rows = []
    # A stated need establishes relevance. Only evidence about its fulfilment
    # can establish whether the dwelling actually meets that need.
    for req in requirements:
        rid = req["requirement_id"]
        if any(f["details"].get("requirement_id") == rid and f["evidence_ids"] and f["snapshot_ids"]
               for f in findings.values()):
            continue
        name = req.get("description") or rid.replace("_", " ")
        step = "step_free" in _topics(rid + " " + name)
        title = "Is the entire route into and through the home step-free?" if step else f"Does the home meet “{name}”?"
        action = ("Walk from the street or parking space through shared entries to the door, living area, bedroom and bathroom. Record steps, thresholds and lift access."
                  if step else f"At inspection, verify “{name}” against the actual dwelling and obtain a dated record.")
        card = _headline_card("requirement:" + rid, title,
                f"The buyer recorded “{name}” as {'essential' if req.get('essential') else 'a preference'}. Its fit at this dwelling remains unverified.",
                action, f"Dated, dwelling-specific evidence confirming or ruling out “{name}” changes this comparison.",
                "Dwelling and access route" if step else "Selected dwelling", [f"requirement:{rid}"], date)
        rows.append((10 if req.get("essential") else 28, "step_free" if step else rid, card))
    preference_questions = {
        "extension": ("works", "Can the planned extension fit within the approved building envelope?",
                      "The buyer plans an extension. Its footprint, required consents and any easements need a site-specific review.",
                      "Match a sketch of the extension to the registered plan, instruments and planning controls.",
                      "Written confirmation of the allowable footprint and required consents would settle whether the plan is feasible.",
                      "Dwelling / parcel", ("S017", "S018", "S019")),
        "step_free": ("step_free", "Is there a continuous step-free route?",
                      "Step-free access matters to the buyer. Verify the street-to-door route and the rooms needed daily.",
                      "Walk and measure thresholds, gradients, lifts and internal level changes.",
                      "A measured route demonstrating continuous access, or identifying an unavoidable step, changes the ranking.",
                      "Dwelling and access route", ()),
        "rail": ("rail", "Will the current rail connection work for the buyer's trip?",
                 "The buyer has prioritised rail. A usable service and door-to-stop walking route remain unverified.",
                 "Walk the route and check existing services at the buyer's travel times.",
                 "A timed route and current service meeting the buyer's commute would resolve this question.",
                 "Nearby route", ("S035", "S050")),
        "activity": ("activity", "How much nearby activity reaches the home?",
                     "The buyer prioritises local activity or amenity. Exposure at the living areas needs an inspection.",
                     "Visit at the relevant hours and check activity from the actual windows and entrances.",
                     "Site observations at the buyer's usual hours establish whether activity affects their intended use.",
                     "Dwelling and nearby streets", ("S036", "S054")),
        "access": ("access", "Does everyday access work at the entrance?",
                   "The buyer prioritises access. The route from the street or parking space to the door needs checking.",
                   "Walk the route, inspect crossings and confirm any shared access rights on the plan.",
                   "A verified route and registered access consistent with the buyer's needs resolve the question.",
                   "Dwelling and access route", ("S018", "S051")),
    }
    for pref in sorted(prefs.intersection(preference_questions)):
        family, title, detail, action, reversal, geo, ids = preference_questions[pref]
        refs = ["case:buyer_preferences", *[cid for cid in ids if cid in checks]]
        if pref == "extension":
            zoning = [r for r in context.get("retained_location_evidence", []) if r.get("kind") == "zoning"]
            for zone in zoning or context.get("spatial", []):
                if zone.get("status") in {"mapped", "multiple_zones"} and _dated_source(zone, date):
                    detail += " " + zone["detail"]
                    refs.append(zone["source_url"])
        card = _headline_card("preference:" + pref, title, detail, action, reversal, geo, refs, date)
        rows.append((14 if pref in {"extension", "step_free"} else 24, family, card))
    return rows


def build_preoffer_brief(case, assessment, context, costs=None):
    """Build a deterministic, source-scoped inspection brief. No source I/O."""
    context, costs = context or {}, costs or {}
    date = case["as_of"]
    planning = [r for r in context.get("planning", []) if _dated_source(r, date)
                and r.get("status") not in {"unknown", "outside_coverage"}]
    decision = purchase_decision(case, assessment, {**context, "planning": planning})
    assessment = assessment or {}
    checks = {c["check_id"]: c for c in assessment.get("check_results", [])}
    findings = {f["finding_id"]: f for f in assessment.get("findings", [])}
    preferences = case.get("buyer_preferences") or {}
    priorities = preferences.get("priorities") or []
    if isinstance(priorities, str):
        priorities = [priorities]
    prefs = _topics(" ".join(str(p) for p in priorities))
    works = _words(preferences.get("planned_works"))
    if works in {"extension", "extend", "renovation and extension"}:
        prefs.add("extension")
    elif works == "as is":
        prefs.add("as_is")
    requirements = case.get("requirements") or []
    candidates = _driver_candidates(case, decision, findings, prefs)
    candidates.extend(_buyer_questions(case, prefs, requirements, findings, checks, context))
    for row in context.get("retained_location_evidence", []):
        if row.get("kind") != "bushfire_proximity" or not _dated_source(row, date):
            continue
        if row.get("status") != "nearby_designation" or row.get("nearby_designation") is not True:
            continue
        card = _headline_card("bushfire_proximity", "How close is the mapped bushfire designation to the home?",
                row["detail"], "Check the current designation against the dwelling footprint and site access. Obtain a site-specific assessment and insurance terms.",
                "A footprint-level designation check, site assessment and written insurance terms would clarify any purchase constraint.",
                row["scope"], [row["source_url"], *row.get("source_ids", [])], row["as_of"])
        card.update(kind="Nearby designation", confidence="Mapped nearby; dwelling exposure unverified")
        candidates.append((17, "fire", card))
    prop = case.get("property") or {}
    unit = prop.get("ownership_form") in {"unit_title", "strata"} or bool(prop.get("units_plan_no"))
    for row in decision["open_checks"]:
        cid = row["id"]
        if cid.startswith("da:"):
            if not any(_source_url(ref) for ref in row["references"]) or not row.get("as_of"):
                continue
            related = _topics(row["title"] + " " + row["detail"]) & prefs
            rank = 16 if related else 23
            family = "access" if "access" in related else "activity"
            card = _card(row, kind="Nearby proposal", geography="Nearby application site", confidence="Impact unverified")
        else:
            family = {"S028": "scheme", "S029": "scheme", "S064": "preferences",
                      "S017": "works", "S019": "works", "S002": "identity"}.get(cid, cid)
            rank = 50 - row["priority"]
            if cid in {"assessment", "property_identity", "S001"}:
                rank = 4
            elif cid == "S065":
                rank = 31
            elif unit and cid in {"S028", "S029"}:
                rank = 25 if cid == "S029" else 26
            elif cid == "S021":
                rank = 34
            elif cid == "buyer_inputs":
                rank = 29
            card = _card(row, kind="Open question", geography=_geography(cid, {}), confidence="Unknown")
            if cid == "S029" and unit:
                card["action"] = "Request the scheme budget, capital works forecast and levy notices. Ask what this lot would owe and when."
                register = next((f for f in findings.values() if f.get("method") == "official_register_join"
                                 and f["check_id"] == "S002" and f["evidence_ids"] and f["snapshot_ids"]), None)
                if register:
                    card["detail"] = register["summary"] + " The amount and timing of this lot's future levies remain unverified."
                    card["references"] = sorted(set(card["references"] + register["evidence_ids"] + register["snapshot_ids"]))
        candidates.append((rank, family, card))
    for row in decision["context_notes"]:
        if row["role"] != "transport_context" or "rail" not in prefs or "rail" not in _topics(row["title"]):
            continue
        if not row.get("as_of") or not any(_source_url(ref) for ref in row["references"]):
            continue
        card = _card(row, kind="Transport proposal", geography="Nearby transport site", confidence="Delivery and route unverified")
        candidates.append((15, "rail", card))
    price = costs.get("price_evidence") or {}
    if price.get("summary") and price.get("action"):
        card = _headline_card("price_evidence", "Is the offer supported by comparable sales?",
                price["summary"], price["action"], "Reviewed recent settled sales of comparable homes can change the supported price position.",
                "Local sales market", [cid for cid in ("S044", "S045") if cid in checks], case["as_of"])
        candidates.append((33, "price", card))
        card["references"].extend(r["source_url"] for r in price.get("comparables", []) if _source_url(r.get("source_url")))
    for row in costs.get("offer_comparison", []):
        if row.get("reserve_status") != "breached" or row.get("first_breach_month") is None:
            continue
        is_base = row.get("label") == "Proposed offer"
        when = "at settlement" if row["first_breach_month"] == 0 else f"in month {row['first_breach_month']}"
        card = _headline_card("offer_reserve:" + row["label"], f"{row['label']} falls below the cash reserve",
                f"At {_cash(row['offer_price'])}, the modelled cash balance first breaches the buyer's reserve {when} under this scenario's stated terms.",
                "Check the loan, available cash and dated outgoings, then compare another offer on the same assumptions.",
                "An offer and verified budget that preserve the reserve throughout the selected horizon change this result.",
                "Buyer household", ["case:finance", "offer_comparison:" + row["label"]], date)
        illustrative = decision["illustrative_finance"]
        card.update(kind="Illustrative example" if illustrative else "Conditional calculation",
                    illustrative=illustrative, confidence="Conditional on buyer inputs")
        if illustrative:
            card["detail"] = "Illustrative buyer inputs. " + card["detail"]
        candidates.append((95 if illustrative else 8 if is_base else 27, "FN02", card))
    if case.get("demonstration"):
        for _, _, card in candidates:
            card["illustrative"] = True
    # Sort once, stably, so ties retain the source's severity/proximity order.
    selected, seen = [], set()
    for _, family, card in sorted(candidates, key=lambda t: t[0]):
        if family in seen:
            continue
        selected.append(card)
        seen.add(family)
        if len(selected) == 3:
            break
    state, headline, summary = decision["state"], decision["headline"], decision["summary"]
    # A legacy finding with no retrievable evidence is exclusively an open
    # question in this brief, even when its legacy assessment carried a flag.
    supported = {card["id"] for _, _, card in candidates
                 if card["kind"] in {"Assessed finding", "Conditional calculation", "Open question"} and card["confidence"] != "Unknown"}
    real_drivers = [item for item in decision["drivers"] if item["id"] in supported and not item["illustrative"]]
    if state in {"review", "blocked"} and not real_drivers:
        state, headline = "incomplete", "Verify the open questions before committing"
    elif state == "blocked" and not any(item["priority"] == 4 for item in real_drivers):
        state, headline = "review", "Resolve the material concerns before committing"
    if state == "no_material_concern" and selected:
        state, headline = "review", "Check the fit at inspection"
    if selected:
        summary = selected[0]["detail"]
    return dict(case_id=case["case_id"], case_version=case.get("case_version"),
                assessment_id=assessment.get("assessment_id"), as_of=case["as_of"], rule_version=BRIEF_VERSION,
                state=state, headline=headline, summary=summary,
                next_action=selected[0]["action"] if selected else decision["next_action"],
                illustrative_finance=decision["illustrative_finance"], top_three=selected,
                coverage=_coverage(checks.values(), decision["coverage"]), costs=costs)
