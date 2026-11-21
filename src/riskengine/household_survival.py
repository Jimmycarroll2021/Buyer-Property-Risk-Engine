"""Conditional, month-end household cash flows for a selected home and offer."""
from __future__ import annotations

from decimal import Decimal, localcontext

from .finance import FinanceInputError, ONE, PRECISION, ZERO, _budget, amount, loan_schedule, money, monthly_payment, months
from .preoffer_costs import _instant, _sale_costs


def _value(fields, name):
    return None if fields.get(name) is None else amount(fields[name], name)


def _sum(*values):
    return None if None in values else sum(values, ZERO)


def _display(values):
    return {k: money(v) for k, v in values.items()}


def _dollars(value):
    return f"{'-' if value < 0 else ''}A${abs(value):,.2f}"


def _funding(f, offer):
    """Use the quoted terms at the original price; mark changed offers provisional."""
    gaps = set()
    original = _value(f, "purchase_price")
    price = offer if offer is not None else original
    advance = _value(f, "loan_funds")
    cash = _value(f, "cash_after_settlement")
    allocated = _value(f, "cash_allocated")
    total = _value(f, "total_liquid_cash")
    fees = _value(f, "acquisition_costs")
    works = _value(f, "immediate_works")
    if price == 0:
        raise FinanceInputError("purchase price must be positive")
    changed = offer is not None and offer != original
    if changed:
        ratio = offer / original if original else None
        if ratio is None:
            gaps.add("purchase_price")
        principal = _value(f, "principal")
        f.update(principal=principal * ratio if None not in (principal, ratio) else None,
                 loan_funds=advance * ratio if None not in (advance, ratio) else None)
        if cash is not None and None not in (original, advance, f["loan_funds"]):
            cash += (original - advance) - (offer - f["loan_funds"])
        else:
            cash = None
        advance = f["loan_funds"]
    for key, value in (("purchase_price", price), ("loan_funds", advance), ("acquisition_costs", fees),
                       ("immediate_works", works), ("cash_allocated", allocated)):
        if value is None:
            gaps.add(key)
    deposit = price - advance if None not in (price, advance) else None
    contribution = _sum(deposit, fees, works)
    if contribution is not None and contribution < ZERO:
        raise FinanceInputError("net loan advance exceeds acquisition costs and purchase price")
    gap = max(ZERO, contribution - allocated) if None not in (contribution, allocated) else None
    if None not in (total, contribution) and total < contribution:
        gap = max(gap or ZERO, contribution - total)
    if cash is not None and cash < ZERO:
        gap = max(gap or ZERO, -cash)
    if cash is None and None not in (total, contribution):
        cash = total - contribution
    original_cash = _value(f, "cash_after_settlement")
    contradictory = None not in (total, allocated, original_cash) and allocated + original_cash > total
    if None not in (cash, total, contribution) and cash + contribution > total:
        contradictory = True
    if contradictory:
        gaps.add("reconcile_cash_double_allocation")
        cash = None
    elif cash is None:
        gaps.add("cash_after_settlement")
    confirmed = f.get("funding_confirmed") is True and not changed and gap is not None and not contradictory
    if contradictory:
        status = "inconsistent"
    elif gap is None:
        status = "unknown"
    elif gap > 0 or (cash is not None and cash < 0):
        status = "shortfall" if confirmed else "provisional_shortfall"
    elif not confirmed:
        status = "unconfirmed"
    else:
        status = "funded"
    if not confirmed and status == "unconfirmed":
        gaps.add("funding_confirmed")
    return ({"state": status, "funding_confirmed": confirmed, **_display({
        "offer_price": price, "deposit": deposit, "acquisition_costs": fees, "immediate_works": works,
        "cash_required": contribution, "cash_allocated": allocated, "funding_gap": gap,
        "cash_after_settlement": cash, "protected_reserve": _value(f, "protected_reserve")})},
        cash, contribution, gaps)


def _threshold(schedule, term, available):
    """Opening nominal P&I rate at which ongoing monthly spending equals income."""
    if not schedule or available is None:
        return None, "unknown"
    balance = schedule[0]["opening_balance"]
    if not balance:
        return None, "no_loan"
    if monthly_payment(balance, ZERO, term) > available:
        return None, "deficit_even_at_zero_rate"
    if monthly_payment(balance, ONE, term) < available:
        return None, "above_model_range"
    low, high = ZERO, ONE
    for _ in range(48):
        mid = (low + high) / 2
        if monthly_payment(balance, mid, term) <= available:
            low = mid
        else:
            high = mid
    return money(low * 100), "calculated"


def _partial_budget(f):
    """Keep independent submitted line items when the complete monthly budget is unavailable."""
    values = {}
    for key in ("income_monthly", "living_monthly", "other_debt_monthly", "property_costs_monthly", "property_costs_annual"):
        try:
            values[key] = _value(f, key)
        except FinanceInputError:
            values[key] = None
    if f.get("property_costs_monthly") is not None and f.get("property_costs_annual") is not None:
        values["property_costs_monthly"] = None
    elif values["property_costs_annual"] is not None:
        values["property_costs_monthly"] = values["property_costs_annual"] / 12
    # Isolate rental normalization from unrelated omissions while retaining its own input checks.
    rent_inputs = {**f, "income_monthly": 0, "living_monthly": 0, "other_debt_monthly": 0,
                   "property_costs_monthly": 0, "property_costs_annual": None}
    try:
        rent, _ = _budget(rent_inputs)
        values["rent_net"] = rent.get("rent_net")
    except FinanceInputError:
        values["rent_net"] = None
    return values


def _scenario(schedule, budget, opening, reserve, settlement, acquisition, loss, duration, extra, repair, repair_month):
    mortgage = sum(row["payment"] for row in schedule[:12]) if schedule else None
    income, living, debt, property_cost, rent = (budget[k] for k in
        ("income_monthly", "living_monthly", "other_debt_monthly", "property_costs_monthly", "rent_net"))
    repair_year = repair if repair_month <= 12 else ZERO
    living_year = 12 * living if living is not None else None
    debt_year = 12 * debt if debt is not None else None
    household_year = _sum(living_year, debt_year)
    property_year = 12 * property_cost if property_cost is not None else None
    extra_year = extra * min(duration, 12)
    outlays = _sum(acquisition, household_year, property_year, mortgage, repair_year, extra_year)
    inflows = 12 * (income + rent) - loss * min(duration, 12) if None not in (income, rent, loss) else None
    year = {"deposit": settlement["deposit"], "acquisition_costs": settlement["acquisition_costs"],
            "immediate_works": settlement["immediate_works"], **_display({
                "settlement_cash": acquisition, "mortgage": mortgage, "living_and_other_debt": household_year,
                "living_expenses": living_year, "other_debt_payments": debt_year,
                "property_running_costs": property_year, "extra_expenses": extra_year, "urgent_repair": repair_year,
                "total_cash_out": outlays, "income_and_net_rent": inflows,
                "net_cash_used_including_settlement": outlays - inflows if None not in (outlays, inflows) else None})}
    result = {"state": "unknown", "first_year": year, "timeline": [], "first_reserve_breach_month": None,
              "first_shortfall_month": None, "minimum_cash_month": None, "minimum_cash": None,
              "cash_shortfall": None, "reserve_shortfall": None, "ending_cash": None, "rebuild_month": None,
              "reserve_rebuild_month": None, "opening_cash": money(opening)}
    if (not schedule or None in (income, living, debt, property_cost, rent, opening, loss, repair_year)
            or settlement["state"] in {"inconsistent", "shortfall", "provisional_shortfall"}):
        return result
    timeline = [{"month": 0, "cash": money(opening), "income": None, "mortgage": None, "outgoings": None,
                 "repair": None, "net": None}]
    cash = minimum = opening
    low_month = 0
    breach = 0 if reserve is not None and cash < reserve else None
    unpaid = 0 if cash < ZERO else None
    balances = [opening]
    for payment in schedule[:12]:
        month = payment["month"]
        inflow = income + rent - (loss if month <= duration else ZERO)
        one_off = repair if month == repair_month else ZERO
        operating = living + debt + property_cost + (extra if month <= duration else ZERO)
        net = inflow - operating - payment["payment"] - one_off
        cash += net
        balances.append(cash)
        if cash < minimum:
            minimum, low_month = cash, month
        if unpaid is None and cash < ZERO:
            unpaid = month
        if breach is None and reserve is not None and cash < reserve:
            breach = month
        timeline.append({"month": month, **_display({"cash": cash, "income": inflow, "mortgage": payment["payment"],
                        "outgoings": operating, "repair": one_off, "net": net})})
    rebuild = None
    if minimum < opening:
        rebuild = next((m for m in range(low_month + 1, 13) if balances[m] >= opening), None)
    reserve_rebuild = None
    if breach is not None:
        reserve_rebuild = next((m for m in range(breach + 1, 13) if balances[m] >= reserve), None)
    status = ("commitments_shortfall" if unpaid is not None else "reserve_breach" if breach is not None
              else "reserve_unknown" if reserve is None else "holds")
    result.update(state=status, timeline=timeline, first_reserve_breach_month=breach, first_shortfall_month=unpaid,
                  minimum_cash_month=low_month, minimum_cash=money(minimum), cash_shortfall=money(max(ZERO, -minimum)),
                  reserve_shortfall=money(max(ZERO, reserve-minimum)) if reserve is not None else None,
                  ending_cash=money(cash), rebuild_month=rebuild, reserve_rebuild_month=reserve_rebuild)
    return result


def _exits(f, options, schedule, contribution):
    fixed = _value(options, "selling_cost_fixed")
    pct = _value(options, "selling_cost_pct")
    # Legacy selling_costs is a complete all-in figure. New components both require entries.
    if fixed is None and pct is None:
        fixed = _sale_costs(f, options)
        if fixed is not None:
            pct = ZERO
    if pct is not None and pct >= 100:
        raise FinanceInputError("selling_cost_pct must be below 100")
    try:
        property_budget, _ = _budget({**f, "income_monthly": 0, "living_monthly": 0, "other_debt_monthly": 0})
    except FinanceInputError:
        property_budget = {}
    rows = []
    for years in (3, 5):
        horizon = years * 12
        sale = _value(options, f"sale_price_{years}y")
        balance = schedule[horizon - 1]["closing_balance"] if schedule else None
        gross = sale - balance if None not in (sale, balance) else None
        costs = fixed + sale * pct / 100 if None not in (fixed, pct, sale) else None
        net = gross - costs if None not in (gross, costs) else None
        hurdle = None
        if None not in (contribution, balance, fixed, pct) and property_budget:
            holding = (property_budget["property_costs_monthly"] - property_budget["rent_net"]) * horizon
            payments = sum(row["payment"] for row in schedule[:horizon])
            hurdle = (contribution + payments + holding + balance + fixed) / (ONE - pct / 100)
        rows.append({"years": years, **_display({"sale_price": sale, "remaining_debt": balance, "gross_equity": gross,
                     "selling_costs": costs, "net_proceeds": net, "break_even_resale": hurdle})})
    return rows


def household_survival(case, assessment, options=None):
    """Return serializable AUD estimates. Unavailable inputs leave affected estimates unknown."""
    options = case.get("preoffer", {}) if options is None else options
    if not isinstance(options, dict):
        raise FinanceInputError("household options must be an object")
    f = dict(case.get("finance") or {})
    assessment = assessment or {}
    cutoff = _instant(assessment.get("as_of") or case.get("as_of"))
    received = _instant(f.get("received_at"))
    unavailable = (assessment.get("financial_scenarios", {}).get("repayment", {}).get("reason") == "NOT_KNOWN_AS_OF"
                   or (f.get("received_at") is not None and (not received or not cutoff or received > cutoff)))
    overrides = options.get("finance") or {}
    if not isinstance(overrides, dict):
        raise FinanceInputError("finance overrides must be an object")
    override_time = _instant(overrides.get("received_at"))
    if overrides.get("received_at") is not None and (not cutoff or not override_time or override_time > cutoff):
        raise FinanceInputError("finance overrides fall outside the assessment date")
    f = {**({} if unavailable else f), **overrides}
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return _survival(case, f, options, unavailable)


def _survival(case, f, options, unavailable):
    settlement, opening, contribution, gaps = _funding(f, _value(options, "offer_price"))
    reserve = _value(f, "protected_reserve")
    if reserve is None:
        gaps.add("protected_reserve")
    try:
        budget, missing = _budget(f)
        gaps.update(missing)
    except FinanceInputError as exc:
        gaps.add(str(exc))
        budget = {}
    loss = _value(options, "lost_income_monthly")
    if loss is not None and budget and loss > budget["income_monthly"]:
        raise FinanceInputError("lost_income_monthly cannot exceed total household income_monthly")
    duration = months(options.get("loss_months", 4), "loss_months", allow_zero=True)
    extra = amount(options.get("extra_expense_monthly", 0), "extra_expense_monthly")
    repair = _value(options, "repair_cost")
    repair_month = months(options.get("repair_month", 1), "repair_month")
    overrun = amount(options.get("repair_overrun_pct", 30), "repair_overrun_pct")
    rise = amount(options.get("rate_rise_bps", 150), "rate_rise_bps")
    if duration == 0:
        loss = ZERO
    if loss is None:
        gaps.add("lost_income_monthly")
    if repair is None and repair_month <= 12:
        gaps.add("repair_cost")
    if unavailable:
        gaps.add("finance_not_known_as_of")
    schedules = []
    for delta in (ZERO, rise):
        try:
            schedules.append(loan_schedule(f, 60, rate_delta_bps=delta))
        except FinanceInputError as exc:
            gaps.add(str(exc))
            schedules.append([])
    line_items = budget or _partial_budget(f)
    base = _scenario(schedules[0], line_items, opening, reserve, settlement, contribution, ZERO, 0, ZERO, ZERO, 1)
    shocked_repair = repair * (ONE + overrun / 100) if repair is not None else None
    combined = _scenario(schedules[1], line_items, opening, reserve, settlement, contribution, loss, duration,
                         extra, shocked_repair, repair_month)
    spending_room = (budget["income_monthly"] + budget["rent_net"] - budget["living_monthly"] -
                     budget["property_costs_monthly"] - budget["other_debt_monthly"]) if budget else None
    threshold, threshold_state = _threshold(schedules[0], f.get("term_months"), spending_room)
    first = combined["first_shortfall_month"]
    breach = combined["first_reserve_breach_month"]
    status = combined["state"]
    if settlement["state"] in {"shortfall", "provisional_shortfall"}:
        status, headline = "settlement_shortfall", "The submitted funds fall short at settlement"
        detail = f"The purchase needs another {_dollars(Decimal(settlement['funding_gap']))} at settlement."
    elif status == "unknown":
        headline = "The household stress result is still open"
        detail = "Complete the missing inputs to calculate how far cash would last after settlement."
    else:
        qualifier = "" if settlement["state"] == "funded" else "If settlement is funded, "
        if first is not None:
            headline = f"The household runs short in month {first}"
            detail = (f"{qualifier}the lowest balance is {_dollars(Decimal(combined['minimum_cash']))} in month "
                      f"{combined['minimum_cash_month']}. An additional {_dollars(Decimal(combined['cash_shortfall']))} "
                      "at settlement covers the modelled payments.")
        elif breach is not None:
            headline = "The household uses its protected reserve"
            detail = (f"{qualifier}the household covers all modelled payments and first crosses below its reserve "
                      f"in month {breach}. The largest reserve gap is {_dollars(Decimal(combined['reserve_shortfall']))}.")
        else:
            headline = "The household covers the modelled year"
            detail = (f"{qualifier}cash reaches a low of {_dollars(Decimal(combined['minimum_cash']))} in month "
                      f"{combined['minimum_cash_month']}. " + ("Enter a protected reserve to test it." if reserve is None
                                                               else "Cash stays at or above the protected reserve."))
        detail = detail[0].upper() + detail[1:]
        if qualifier:
            headline = qualifier.capitalize() + headline[0].lower() + headline[1:]
            status = "conditional"
        month_one = combined["timeline"][1]
        detail += (f" In month one, income is {_dollars(Decimal(month_one['income']))}. Living costs, other debt "
                   f"and property expenses total {_dollars(Decimal(month_one['outgoings']))}, with a further "
                   f"{_dollars(Decimal(month_one['mortgage']))} due on the mortgage.")
        if shocked_repair and repair_month <= 12:
            detail += f" The additional repair costs {_dollars(shocked_repair)} in month {repair_month}."
        if combined["rebuild_month"] is not None:
            detail += f" Cash regains its opening balance in month {combined['rebuild_month']}."
        elif Decimal(combined["minimum_cash"]) < opening:
            detail += " Cash has yet to regain its opening balance after the low point by month 12."
    indicative = bool(case.get("demonstration") or case.get("finance_is_illustrative"))
    if indicative:
        detail = "Illustrative household figures. " + detail
    additional_mortgage = None
    if all(schedules):
        additional_mortgage = sum(p["payment"] for p in schedules[1][:12]) - sum(p["payment"] for p in schedules[0][:12])
    income_lost = loss * min(12, duration) if loss is not None else None
    extra_expenses = extra * min(12, duration)
    repair_in_year = shocked_repair if repair_month <= 12 else ZERO
    difference = _display({"income_lost": income_lost, "extra_mortgage": additional_mortgage,
                           "extra_expenses": extra_expenses, "urgent_repair": repair_in_year,
                           "additional_cash_used": _sum(income_lost, additional_mortgage, extra_expenses, repair_in_year)})
    return {"state": status, "headline": headline, "detail": detail, "illustrative": indicative,
            "missing_inputs": sorted(gaps), "settlement": settlement, "baseline": base, "combined": combined,
            "first_year_difference": difference,
            "break_even_rate_pct": threshold, "break_even_rate_state": threshold_state,
            "exit_scenarios": _exits(f, options, schedules[0], contribution),
            "assumptions": {"rate_rise_bps": str(rise), "lost_income_monthly": money(loss), "loss_months": duration,
                "extra_expense_monthly": money(extra), "repair_cost": money(repair), "repair_month": repair_month,
                "repair_overrun_pct": str(overrun), "stressed_repair_cost": money(shocked_repair)},
            "basis": [
                "Income means household take-home cash. The selected earner's stated loss and extra expenses apply from month one for the specified duration. The rate rise applies to every scheduled rate.",
                "The additional repair occurs once in the combined case. Exclude work already counted at settlement or in recurring property costs. Enter zero for an explicitly excluded repair or income loss.",
                "Balances are measured at settlement and month end. A negative balance measures a funding need. Recovery after a shortfall assumes that funding need can be bridged without interest or fees.",
                "Rebuild month is the first month after the low point when cash regains its opening balance within year one. Reserve recovery is measured separately.",
                "The break-even rate is the opening annual principal-and-interest rate at which normal monthly income equals monthly outgoings, before temporary shocks.",
                "Three- and five-year exits use the baseline loan schedule and stated sale and selling costs. The break-even resale price recovers acquisition cash, all mortgage payments and property expenses less net rent after clearing debt and selling costs. Household consumption and hypothetical shocks are excluded."
            ]}
