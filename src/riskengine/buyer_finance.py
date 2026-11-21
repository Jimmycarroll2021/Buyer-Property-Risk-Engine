"""Buyer-facing explanations of the financial results for one pinned case."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .finance import FinanceInputError, amount, months, normalise_rate


_LABELS = {
    "income_monthly": "monthly household income",
    "living_monthly": "monthly living expenses",
    "other_debt_monthly": "monthly payments on other debt",
    "property_costs_monthly_or_annual": "monthly or annual property costs",
    "acquisition_costs": "purchase costs",
    "cash_allocated": "cash committed to the purchase",
    "immediate_works": "immediate works costs",
    "loan_funds": "loan funds available at settlement",
    "cash_after_settlement": "cash left after settlement",
    "protected_reserve": "the cash reserve you want to keep",
    "essential_outgoings": "the monthly household, property and loan outgoings",
}


def _cash(value: Decimal | str) -> str:
    value = Decimal(value)
    return f"{'-' if value < 0 else ''}A${abs(value):,.2f}"


def _percent(rate: Decimal) -> str:
    number = format(rate * 100, "f")
    return number.rstrip("0").rstrip(".") if "." in number else number


def _gap(row: dict, fallback: str) -> str:
    fields = row.get("missing_inputs") or []
    if fields:
        labels = [_LABELS.get(key, key.replace("_", " ")) for key in fields]
        needed = ", ".join(labels[:-1]) + " and " + labels[-1] if len(labels) > 1 else labels[0]
        return f"Enter {needed}."
    if row.get("reason") == "CASH_DOUBLE_ALLOCATION":
        return "Reconcile cash committed to the purchase and cash kept in reserve against total liquid cash."
    if row.get("detail"):
        if row["detail"].startswith("term_months is missing"):
            return "Enter a valid loan term in months and complete the household budget."
        return "Check the case inputs. " + row["detail"].replace("_", " ").rstrip(".") + "."
    return fallback


def _repayment_gap(inputs: dict, row: dict) -> str:
    if row.get("detail", "") and row["detail"].startswith("term_months is missing") and inputs.get("term_months") is None:
        try:
            principal = amount(inputs.get("principal"), "principal")
            if inputs.get("annual_rate_decimal") is not None:
                rate = normalise_rate(inputs["annual_rate_decimal"])
            else:
                rate = normalise_rate(inputs.get("annual_rate"), inputs.get("rate_unit"))
        except FinanceInputError:
            return "Enter the loan amount, annual rate with units, and repayment term."
        return (f"The case assumes a loan of {_cash(principal)} at {_percent(rate)}% per year. "
                "Enter the loan term in months to calculate the initial monthly repayment.")
    return _gap(row, "Enter the loan amount, annual rate with units, and repayment term.")


def _settlement_gap(inputs: dict, row: dict) -> str:
    prompt = _gap(row, "Enter the purchase price, purchase costs, immediate works, loan funds and cash committed.")
    if row.get("reason") != "MISSING_INPUT":
        return prompt
    try:
        price = amount(inputs.get("purchase_price"), "purchase price")
        loan = amount(inputs.get("loan_funds"), "loan funds")
    except FinanceInputError:
        return prompt
    if price < loan:
        return prompt
    return (f"At the case price of {_cash(price)}, planned loan funds of {_cash(loan)} leave "
            f"{_cash(price - loan)} of the price to cover before purchase costs and immediate works. {prompt}")


def _shock(assumptions: dict) -> str:
    labels = []
    if assumptions.get("rate_delta_bps") is not None:
        bps = amount(assumptions["rate_delta_bps"], "rate_delta_bps", minimum=None)
        if bps:
            labels.append(f"a {bps / 100:+f} percentage point change in the loan rate")
    for key, label in (("income_factor", "income"), ("property_cost_factor", "property costs"), ("rent_factor", "net rent")):
        if assumptions.get(key) is not None:
            factor = amount(assumptions[key], key)
            if factor != 1:
                labels.append(f"{label} at {_percent(factor)}% of baseline")
    return ", ".join(labels) or "unchanged rates, income, property costs and rent"


def _pending_stress(inputs: dict, outcome: dict) -> str:
    prompt = _gap(outcome, "Complete the base budget, reserve and stress assumptions.")
    if outcome.get("reason") not in {"MISSING_INPUT", "MISSING_OR_INVALID_INPUT"}:
        return prompt
    try:
        duration = months(inputs.get("duration_months"), "duration_months")
        conditions = _shock(inputs)
    except (FinanceInputError, InvalidOperation):
        return prompt
    return f"The requested {duration}-month stress test assumes {conditions}. {prompt}"


def finance_signals(case: dict, assessment: dict) -> list[dict]:
    """Explain recorded outcomes using the same case version passed to evaluate_case."""
    finance = assessment.get("financial_scenarios") or {}
    as_of = assessment.get("as_of", case.get("as_of"))
    signals = []

    def add(title: str, detail: str, status: str) -> None:
        signals.append({"title": title, "detail": detail, "status": status, "as_of": as_of})

    if not finance or finance.get("repayment", {}).get("reason") == "NOT_KNOWN_AS_OF":
        add("Buyer finances unavailable", "Use finance inputs available by the assessment date and run the assessment.", "Missing inputs")
        return signals
    inputs = case.get("finance") or {}
    if not inputs and all(finance.get(key, {}).get("state") != "ASSESSED" for key in ("repayment", "baseline", "settlement", "buffer")):
        add("Add your buyer finances", "Enter your purchase price, loan terms, household budget and cash reserve to assess this purchase.", "Missing inputs")
        return signals

    repayment = finance.get("repayment", {})
    if repayment.get("state") == "ASSESSED":
        add("Initial monthly loan repayment",
            f"Allow {_cash(repayment['monthly_payment'])} in month 1 for principal and interest on "
            f"{_cash(repayment['principal'])} at {_percent(Decimal(repayment['annual_rate_decimal']))}% per year "
            f"over {repayment['term_months']} months.", "Case estimate")
        for reset in repayment.get("rate_resets", []):
            add(f"Loan rate reset in month {reset['start_month']}",
                f"The case rate changes to {_percent(Decimal(reset['annual_rate_decimal']))}% per year. "
                f"Budget {_cash(reset['monthly_payment'])} per month from that reset.", "Case estimate")
    else:
        add("Monthly repayment unknown", _repayment_gap(inputs, repayment), "Missing inputs")

    baseline = finance.get("baseline", {})
    if baseline.get("state") == "ASSESSED":
        surplus = Decimal(baseline["monthly_surplus"])
        direction = "left over" if surplus >= 0 else "short"
        add("Monthly household budget",
            f"The opening monthly budget is {_cash(abs(surplus))} {direction} after the loan payment, living expenses, "
            "other debt and property costs. Compare this with your expected monthly spending.",
            "Budget shortfall" if surplus < 0 else "Case estimate")
    else:
        add("Monthly household budget unknown", _gap(baseline, "Complete the monthly household budget and loan terms."), "Missing inputs")

    settlement = finance.get("settlement", {})
    confirmed = settlement.get("state") == "ASSESSED"
    if confirmed or settlement.get("reason") == "FUNDING_UNCONFIRMED":
        required, allocated = Decimal(settlement["required_funds"]), Decimal(settlement["allocated_funds"])
        balance = allocated - required
        position = (f"a shortfall of {_cash(-balance)}" if balance < 0 else
                    f"headroom of {_cash(balance)}" if balance > 0 else "no headroom")
        detail = f"The case allocates {_cash(allocated)} against {_cash(required)} due at settlement, leaving {position}."
        if not confirmed:
            detail += " Confirm the loan and cash amounts before relying on this estimate."
        elif balance < 0:
            detail += " Reconcile the gap against funds available on settlement day."
        add("Settlement funding", detail, "Unconfirmed funding" if not confirmed else "Funding shortfall" if balance < 0 else "Case estimate")
    else:
        add("Settlement funding incomplete", _settlement_gap(inputs, settlement), "Missing inputs")

    buffer = finance.get("buffer", {})
    if buffer.get("state") == "ASSESSED":
        short = Decimal(buffer["shortfall"])
        detail = (f"After settlement the case leaves {_cash(buffer['cash_after_settlement'])} in cash "
                  f"against your protected reserve of {_cash(buffer['protected_reserve'])}.")
        if short:
            detail += f" Another {_cash(short)} would bring cash up to your reserve."
        if "minimum_buffer_months" in buffer:
            detail += (f" Cash covers {buffer['months_of_essential_outgoings']} months of essential outgoings "
                       f"against your {buffer['minimum_buffer_months']}-month target.")
        add("Cash reserve after settlement", detail, "Below target" if buffer.get("priority") else "Case estimate")
    else:
        add("Cash reserve unknown", _gap(buffer, "Enter the cash left after settlement and your protected reserve."), "Missing inputs")

    requested = {s["scenario_id"]: s for s in case.get("scenarios", [])}
    for scenario in finance.get("scenarios", []):
        name = scenario["scenario_id"]
        if scenario.get("state") != "ASSESSED":
            add(f"Stress test pending · {name}", _pending_stress(requested.get(name, {}), scenario), "Missing inputs")
            continue
        duration = scenario["duration_months"]
        detail = (f"Assumptions over {duration} months include {_shock(scenario['assumptions'])}. "
                  f"Cash reaches a low of {_cash(scenario['minimum_cash'])} and ends at {_cash(scenario['ending_cash'])}.")
        if scenario["reserve_breached"]:
            breach = scenario["first_breach_month"]
            when = "at the start" if breach == 0 else f"in month {breach}"
            detail += f" Cash first falls below your {_cash(scenario['protected_reserve'])} reserve {when}."
        else:
            detail += f" Cash stays at or above your {_cash(scenario['protected_reserve'])} reserve throughout."
        if scenario.get("surplus_target_breached"):
            detail += " Monthly surplus falls below your target during this period."
        add(f"Stress test · {name}", detail, "Below target" if scenario.get("priority") else "Case estimate")
    if not finance.get("scenarios"):
        add("Stress test pending", "Set a duration and a change in the loan rate, income or property costs to test how long your reserve lasts.", "Missing inputs")
    return signals
