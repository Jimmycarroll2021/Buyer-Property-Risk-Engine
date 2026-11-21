"""Deterministic, assumption-explicit cash calculations.

Money is calculated at Decimal precision 40 and rounded only for presentation.
This is an equal-month, nominal-rate model, not a lender's daily-interest ledger.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_UP
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
PRECISION = 40
MAX_MONTHS = 1200


class FinanceInputError(ValueError):
    """Invalid rather than merely missing financial inputs."""


def amount(value: Any, name: str, *, minimum: Decimal | None = ZERO) -> Decimal:
    if value is None or isinstance(value, bool):
        raise FinanceInputError(f"{name} is missing or is not a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FinanceInputError(f"{name} is not a decimal number") from exc
    if not result.is_finite() or (minimum is not None and result < minimum):
        raise FinanceInputError(f"{name} must be finite and at least {minimum}")
    return result


def months(value: Any, name: str, *, allow_zero: bool = False) -> int:
    d = amount(value, name)
    if d != d.to_integral_value():
        raise FinanceInputError(f"{name} must be an integer")
    n = int(d)
    if not (0 if allow_zero else 1) <= n <= MAX_MONTHS:
        raise FinanceInputError(f"{name} must be between {0 if allow_zero else 1} and {MAX_MONTHS}")
    return n


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = max(PRECISION, len(value.as_tuple().digits) + 4)
        return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def normalise_rate(value: Any, unit: str = "decimal") -> Decimal:
    rate = amount(value, "annual rate")
    if unit in ("percent", "per_cent", "%"):
        rate /= Decimal(100)
    elif unit != "decimal":
        raise FinanceInputError("Rate unit must be decimal or percent")
    if rate > ONE:
        raise FinanceInputError("Annual rate exceeds supported 100% input bound; verify units")
    return rate


def monthly_payment(principal: Any, annual_rate_decimal: Any, term_months: Any) -> Decimal:
    p = amount(principal, "principal")
    n = months(term_months, "term_months")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        r = normalise_rate(annual_rate_decimal) / Decimal(12)
        if p == ZERO:
            return ZERO
        if r == ZERO:
            return p / Decimal(n)
        return p * r / (ONE - (ONE + r) ** (-n))


def remaining_balance(principal: Any, annual_rate_decimal: Any, term_months: Any, payments: Any) -> Decimal:
    p = amount(principal, "principal")
    n = months(term_months, "term_months")
    k = months(payments, "payments", allow_zero=True)
    if k > n:
        raise FinanceInputError("payments cannot exceed loan term")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        r = normalise_rate(annual_rate_decimal) / Decimal(12)
        payment = monthly_payment(p, annual_rate_decimal, n)
        if r == ZERO:
            return max(ZERO, p - payment * k)
        return max(ZERO, p * (ONE + r) ** k - payment * (((ONE + r) ** k - ONE) / r))


def _essential(requirements: list[dict], requirement_id: str | None) -> bool:
    return bool(requirement_id and any(
        r.get("requirement_id") == requirement_id and r.get("essential") is True
        for r in requirements
    ))


def _missing(inputs: dict, names: list[str]) -> list[str]:
    return [n for n in names if inputs.get(n) is None]


def _unassessed(reason: str, fields: list[str] | None = None, detail: str | None = None) -> dict:
    return {"state": "NOT_ASSESSED", "priority": None, "reason": reason,
            "missing_inputs": sorted(fields or []), "detail": detail}


def _loan_inputs(finance: dict) -> tuple[Decimal, Decimal, int, list[tuple[int, Decimal]]]:
    if finance.get("repayment_type", "principal_and_interest") != "principal_and_interest":
        raise FinanceInputError("UNSUPPORTED_METHOD: only fully amortising principal-and-interest loans are enabled")
    if finance.get("offset_balance") not in (None, 0, "0", "0.00"):
        raise FinanceInputError("UNSUPPORTED_METHOD: offset loans require a separate daily-interest model")
    if finance.get("loan_splits"):
        raise FinanceInputError("UNSUPPORTED_METHOD: split loans are not enabled")
    if finance.get("annual_rate") is not None and finance.get("rate_unit") is None:
        raise FinanceInputError("annual_rate requires an explicit rate_unit; alternatively use annual_rate_decimal")
    p = amount(finance.get("principal"), "principal")
    if finance.get("annual_rate_decimal") is not None:
        rate = normalise_rate(finance["annual_rate_decimal"])
        if finance.get("annual_rate") is not None:
            other = normalise_rate(finance["annual_rate"], finance.get("rate_unit", "decimal"))
            if other != rate:
                raise FinanceInputError("Conflicting annual rate representations")
    else:
        rate = normalise_rate(finance.get("annual_rate"), finance.get("rate_unit", "decimal"))
    n = months(finance.get("term_months"), "term_months")
    schedule = []
    starts = set()
    if not isinstance(finance.get("rate_schedule", []), list) or any(not isinstance(i,dict) for i in finance.get("rate_schedule", [])):
        raise FinanceInputError("rate_schedule must be a list of objects")
    for item in finance.get("rate_schedule", []):
        month = months(item.get("start_month"), "rate_schedule.start_month")
        if month > n or month in starts:
            raise FinanceInputError("Rate schedule months must be unique and within the loan term")
        starts.add(month)
        schedule.append((month, normalise_rate(item.get("annual_rate_decimal"))))
    if finance.get("revert_rate") is not None or finance.get("fixed_expiry_months") is not None:
        if finance.get("revert_rate") is None or finance.get("fixed_expiry_months") is None:
            raise FinanceInputError("Both revert_rate and fixed_expiry_months are required")
        expiry = months(finance["fixed_expiry_months"], "fixed_expiry_months", allow_zero=True)
        if expiry >= n or expiry + 1 in starts:
            raise FinanceInputError("Rate expiry overlaps another reset or is outside the loan term")
        schedule.append((expiry + 1, normalise_rate(finance["revert_rate"])))
    return p, rate, n, sorted(schedule)


def loan_schedule(finance: dict, duration: int, *, rate_delta_bps: Any = 0) -> list[dict]:
    """Unrounded internal schedule. Reset month is one-based payment number."""
    duration = months(duration, "duration", allow_zero=True)
    p, rate, n, changes = _loan_inputs(finance)
    delta = amount(rate_delta_bps, "rate_delta_bps", minimum=None) / Decimal(10000)
    rates = dict(changes)
    result = []
    balance = p
    with localcontext() as ctx:
        ctx.prec = PRECISION
        current = normalise_rate(rate + delta)
        payment = monthly_payment(balance, current, n)
        for month in range(1, duration + 1):
            if month in rates and month <= n:
                current = normalise_rate(rates[month] + delta)
                payment = monthly_payment(balance, current, n - month + 1)
            opening = balance
            if month > n or balance <= ZERO:
                interest = paid = ZERO
                balance = ZERO
            else:
                interest = balance * current / Decimal(12)
                paid = min(payment, balance + interest)
                balance = max(ZERO, balance + interest - paid)
                if month == n:
                    # Remove only the final arithmetic residue.
                    balance = ZERO
            result.append({"month": month, "opening_balance": opening, "payment": paid,
                           "interest": interest, "closing_balance": balance,
                           "annual_rate_decimal": current})
    return result


def _budget(finance: dict) -> tuple[dict[str, Decimal], list[str]]:
    names = ["income_monthly", "living_monthly", "other_debt_monthly"]
    missing = _missing(finance, names)
    if finance.get("property_costs_monthly") is None and finance.get("property_costs_annual") is None:
        missing.append("property_costs_monthly_or_annual")
    if finance.get("property_costs_monthly") is not None and finance.get("property_costs_annual") is not None:
        raise FinanceInputError("Supply property costs monthly OR annually, not both")
    rental = finance.get("intended_use") == "investment" or finance.get("gross_rent_monthly") is not None
    if rental:
        if finance.get("property_costs_include_management") is True:
            raise FinanceInputError("Management fees must not also be included in property_costs")
        if finance.get("rent_is_net") is True:
            raise FinanceInputError("gross_rent_monthly must be gross, not an already netted rent")
        missing += _missing(finance, ["gross_rent_monthly", "vacancy_fraction", "management_fraction"])
    if missing:
        return {}, sorted(set(missing))
    data = {k: amount(finance[k], k) for k in names}
    if finance.get("property_costs_monthly") is not None:
        data["property_costs_monthly"] = amount(finance["property_costs_monthly"], "property_costs_monthly")
    else:
        data["property_costs_monthly"] = amount(finance["property_costs_annual"], "property_costs_annual") / Decimal(12)
    if rental:
        vacancy = amount(finance["vacancy_fraction"], "vacancy_fraction")
        management = amount(finance["management_fraction"], "management_fraction")
        if vacancy > ONE or management > ONE:
            raise FinanceInputError("Rental vacancy and management fractions must be between zero and one")
        gross = amount(finance["gross_rent_monthly"], "gross_rent_monthly")
        collected = gross * (ONE - vacancy)
        data.update(rent_gross=gross, rent_vacancy=gross-collected,
                    rent_management=collected*management, rent_net=collected*(ONE-management))
    else:
        data.update(rent_gross=ZERO, rent_vacancy=ZERO, rent_management=ZERO, rent_net=ZERO)
    return data, []


def evaluate_finance(finance: dict | None, scenarios: list[dict] | None = None,
                     requirements: list[dict] | None = None) -> dict:
    f = finance or {}
    requirements = requirements or []
    result: dict[str, Any] = {
        "model": "equal_month_nominal_rate_principal_and_interest",
        "precision_policy": "Decimal precision 40; no intermediate payment or interest rounding; display HALF_UP to cents",
        "tax_treatment": "before_personal_income_tax",
        "repayment": _unassessed("MISSING_INPUT"),
        "baseline": _unassessed("MISSING_INPUT"),
        "settlement": _unassessed("MISSING_INPUT"),
        "buffer": _unassessed("MISSING_INPUT"),
        "scenarios": [], "exit": _unassessed("NOT_REQUESTED"),
        "limitations": ["Conditional calculations under supplied inputs; no loan approval or forecast of shock occurrence."]
    }
    if not f:
        return result
    with localcontext() as ctx:
        ctx.prec = PRECISION
        _evaluate(finance=f, scenarios=scenarios or [], requirements=requirements, result=result)
    return result


def _evaluate(finance: dict, scenarios: list[dict], requirements: list[dict], result: dict) -> None:
    f = finance
    loan_error = None
    schedule = []
    try:
        principal, rate, term, resets = _loan_inputs(f)
        schedule = loan_schedule(f, term)
        payment = schedule[0]["payment"]
        result["repayment"] = {
            "state": "ASSESSED", "priority": 0, "principal": money(principal),
            "annual_rate_decimal": str(schedule[0]["annual_rate_decimal"]), "term_months": term,
            "monthly_payment": money(payment), "repayment_type": "principal_and_interest",
            "rate_resets": [{"start_month": m, "annual_rate_decimal": str(r),
                             "opening_balance": money(schedule[m-1]["opening_balance"]),
                             "remaining_term_months": term-m+1,
                             "monthly_payment": money(schedule[m-1]["payment"])} for m, r in resets]
        }
    except (FinanceInputError, InvalidOperation) as exc:
        loan_error = str(exc)
        reason = "UNSUPPORTED_METHOD" if "UNSUPPORTED_METHOD" in loan_error else "INVALID_OR_MISSING_INPUT"
        result["repayment"] = _unassessed(reason, detail=loan_error)
        payment = None

    budget = {}
    budget_error = None
    try:
        budget, missing = _budget(f)
        if missing:
            result["baseline"] = _unassessed("MISSING_INPUT", missing)
        elif payment is None:
            result["baseline"] = _unassessed("UNSUPPORTED_OR_INVALID_LOAN", detail=loan_error)
        else:
            surplus = budget["income_monthly"] + budget["rent_net"] - budget["living_monthly"] - budget["other_debt_monthly"] - budget["property_costs_monthly"] - payment
            priority = 0 if surplus >= ZERO else (4 if _essential(requirements, f.get("no_drawdown_requirement_id")) else 3)
            result["baseline"] = {
                "state": "ASSESSED", "priority": priority, "monthly_surplus": money(surplus),
                "mortgage_payment": money(payment), "income_monthly": money(budget["income_monthly"]),
                "living_monthly": money(budget["living_monthly"]), "other_debt_monthly": money(budget["other_debt_monthly"]),
                "property_costs_monthly": money(budget["property_costs_monthly"]),
                "rental": {k: money(v) for k, v in budget.items() if k.startswith("rent_")},
                "scope": "Initial monthly cash flow; reset and shock periods are reported in their dated schedules."
            }
    except FinanceInputError as exc:
        budget_error = str(exc)
        result["baseline"] = _unassessed("INVALID_INPUT", detail=budget_error)

    # Day-one purchase funding is distinct from remaining cash and monthly affordability.
    settlement_fields = ["purchase_price", "acquisition_costs", "immediate_works", "loan_funds", "cash_allocated"]
    missing = _missing(f, settlement_fields)
    cash_error = None
    try:
        if missing:
            result["settlement"] = _unassessed("MISSING_INPUT", missing)
        else:
            values = {k: amount(f[k], k) for k in settlement_fields}
            required = values["purchase_price"] + values["acquisition_costs"] + values["immediate_works"]
            funded = values["loan_funds"] + values["cash_allocated"]
            gap = max(ZERO, required - funded)
            result["settlement"] = {
                "state": "ASSESSED" if f.get("funding_confirmed") is True else "NOT_ASSESSED",
                "priority": (4 if gap > ZERO else 0) if f.get("funding_confirmed") is True else None,
                "reason": None if f.get("funding_confirmed") is True else "FUNDING_UNCONFIRMED",
                "required_funds": money(required), "allocated_funds": money(funded),
                "funding_gap": money(gap), "input_amounts": {k: money(v) for k,v in values.items()},
                "basis": "Submitted funding configuration; confirmed means the submitter has verified its stated availability."
            }
        if f.get("total_liquid_cash") is not None and f.get("cash_after_settlement") is not None and f.get("cash_allocated") is not None:
            total = amount(f["total_liquid_cash"], "total_liquid_cash")
            allocated = amount(f["cash_allocated"], "cash_allocated")
            after = amount(f["cash_after_settlement"], "cash_after_settlement")
            if allocated + after > total:
                cash_error = "Cash allocated to acquisition plus post-settlement cash exceeds total liquid cash"
                result["settlement"] = _unassessed("CASH_DOUBLE_ALLOCATION", detail=cash_error)
    except FinanceInputError as exc:
        cash_error = str(exc)
        result["settlement"] = _unassessed("INVALID_INPUT", detail=cash_error)

    try:
        missing = _missing(f, ["cash_after_settlement", "protected_reserve"])
        if missing:
            result["buffer"] = _unassessed("MISSING_INPUT", missing)
        elif cash_error:
            result["buffer"] = _unassessed("CASH_DOUBLE_ALLOCATION", detail=cash_error)
        else:
            cash = amount(f["cash_after_settlement"], "cash_after_settlement")
            reserve = amount(f["protected_reserve"], "protected_reserve")
            shortfall = max(ZERO, reserve-cash)
            result["buffer"] = {"state":"ASSESSED", "priority":(4 if _essential(requirements,f.get("buffer_requirement_id")) else 2) if shortfall else 0,
                                "cash_after_settlement":money(cash), "protected_reserve":money(reserve),
                                "shortfall":money(shortfall)}
            if f.get("minimum_buffer_months") is not None:
                target = amount(f["minimum_buffer_months"], "minimum_buffer_months")
                if not budget or payment is None:
                    result["buffer"] = _unassessed("MISSING_INPUT", ["essential_outgoings"])
                else:
                    outgoings = budget["living_monthly"] + budget["other_debt_monthly"] + budget["property_costs_monthly"] + payment
                    if outgoings <= ZERO:
                        result["buffer"] = _unassessed("DENOMINATOR_INVALID")
                    else:
                        held_months = cash/outgoings
                        breach = held_months < target or shortfall > ZERO
                        result["buffer"].update(months_of_essential_outgoings=money(held_months), minimum_buffer_months=money(target),
                            priority=(4 if _essential(requirements,f.get("buffer_requirement_id")) else 2) if breach else 0)
    except FinanceInputError as exc:
        result["buffer"] = _unassessed("INVALID_INPUT", detail=str(exc))

    seen = set()
    for scenario in sorted(scenarios, key=lambda x: str(x.get("scenario_id",""))):
        sid = str(scenario.get("scenario_id", ""))
        out = {"scenario_id": sid, "required_review": scenario.get("required_review") is True}
        try:
            if not sid or sid in seen:
                raise FinanceInputError("Scenario IDs must be non-empty and unique")
            seen.add(sid)
            duration = months(scenario.get("duration_months"), "duration_months")
            if scenario.get("start_month", 0) != 0:
                raise FinanceInputError("UNSUPPORTED_METHOD: stress start_month must be zero; supply cash and loan state at the scenario start")
            if not budget or payment is None:
                out.update(_unassessed("MISSING_OR_INVALID_INPUT", detail=budget_error or loan_error or "Complete base budget is required"))
            elif cash_error:
                out.update(_unassessed("CASH_DOUBLE_ALLOCATION", detail=cash_error))
            elif _missing(f, ["cash_after_settlement", "protected_reserve"]):
                out.update(_unassessed("MISSING_INPUT", _missing(f,["cash_after_settlement","protected_reserve"])))
            else:
                cash = amount(f["cash_after_settlement"], "cash_after_settlement")
                reserve = amount(f["protected_reserve"], "protected_reserve")
                income_factor = amount(scenario.get("income_factor",1), "income_factor")
                cost_factor = amount(scenario.get("property_cost_factor",1), "property_cost_factor")
                rent_factor = amount(scenario.get("rent_factor",1), "rent_factor")
                loan = loan_schedule(f, duration, rate_delta_bps=scenario.get("rate_delta_bps",0))
                minimum = cash
                breach_month = 0 if cash < reserve else None
                surplus_target = amount(scenario["minimum_monthly_surplus"],"minimum_monthly_surplus",minimum=None) if scenario.get("minimum_monthly_surplus") is not None else None
                target_breach = False
                monthly = []
                raw_surpluses = []
                for row in loan:
                    surplus = budget["income_monthly"]*income_factor + budget["rent_net"]*rent_factor - budget["living_monthly"] - budget["other_debt_monthly"] - budget["property_costs_monthly"]*cost_factor - row["payment"]
                    opening = cash
                    cash += surplus
                    minimum = min(minimum,cash)
                    if cash < reserve and breach_month is None:
                        breach_month = row["month"]
                    if surplus_target is not None and surplus < surplus_target:
                        target_breach = True
                    raw_surpluses.append(surplus)
                    monthly.append({"month":row["month"],"annual_rate_decimal":str(row["annual_rate_decimal"]),
                                    "mortgage_payment":money(row["payment"]),"loan_balance":money(row["closing_balance"]),
                                    "opening_cash":money(opening),"monthly_surplus":money(surplus),"closing_cash":money(cash),
                                    "below_protected_reserve":cash<reserve})
                breached = minimum < reserve or target_breach
                priority = (4 if _essential(requirements,scenario.get("requirement_id")) else (3 if out["required_review"] else 2)) if breached else 0
                out.update({"state":"ASSESSED","priority":priority,"duration_months":duration,
                            "initial_cash":money(amount(f["cash_after_settlement"],"cash_after_settlement")),
                            "protected_reserve":money(reserve),"minimum_cash":money(minimum),"ending_cash":money(cash),
                            "reserve_breached":minimum<reserve,"first_breach_month":breach_month,
                            "surplus_target_breached":target_breach,"monthly_schedule":monthly,
                            "assumptions":{k:scenario.get(k,default) for k,default in [("rate_delta_bps",0),("income_factor","1"),("property_cost_factor","1"),("rent_factor","1")]},
                            "claim":"Conditional scenario; not a prediction that the shock will occur."})
                if raw_surpluses and all(s == raw_surpluses[0] for s in raw_surpluses) and raw_surpluses[0] < ZERO:
                    opening = amount(f["cash_after_settlement"], "cash_after_settlement")
                    out["continuous_equivalent_months_to_reserve"] = money(max(ZERO,(opening-reserve)/(-raw_surpluses[0])))
        except (FinanceInputError, InvalidOperation) as exc:
            out.update(_unassessed("UNSUPPORTED_METHOD" if "UNSUPPORTED_METHOD" in str(exc) else "INVALID_INPUT",detail=str(exc)))
        result["scenarios"].append(out)

    if f.get("exit") is not None:
        e = f["exit"]
        try:
            if not isinstance(e,dict):
                raise FinanceInputError("exit must be an object")
            m = months(e.get("sale_month"), "sale_month", allow_zero=True)
            sale = amount(e.get("sale_price"), "sale_price")
            costs = amount(e.get("selling_costs"), "selling_costs")
            treatment = e.get("tax_treatment")
            if treatment not in ("before_personal_tax","explicit_tax"):
                raise FinanceInputError("Exit tax_treatment must be before_personal_tax or explicit_tax")
            tax = amount(e.get("tax_costs"),"tax_costs") if treatment == "explicit_tax" else ZERO
            if loan_error:
                raise FinanceInputError(loan_error)
            balance = amount(f["principal"],"principal") if m == 0 else loan_schedule(f,m)[-1]["closing_balance"]
            net = sale-balance-costs-tax
            result["exit"]={"state":"ASSESSED","priority":2 if net<ZERO else 0,
                            "sale_month":m,"sale_price":money(sale),"remaining_principal":money(balance),
                            "selling_costs":money(costs),"tax_costs":money(tax) if treatment=="explicit_tax" else None,
                            "tax_treatment":treatment,"net_sale_proceeds":money(net),
                            "scope":"Sale proceeds after debt and specified exit costs; not total investment return or lending approval."}
        except (FinanceInputError,InvalidOperation,TypeError) as exc:
            result["exit"]=_unassessed("INVALID_OR_MISSING_INPUT",detail=str(exc))
