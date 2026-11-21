"""Conditional owner-occupier protection and career scenarios, in Australian dollars."""
from decimal import Decimal

from .finance import FinanceInputError, ZERO, amount, money


MONEYSMART = "https://moneysmart.gov.au"
LIFE = "/how-life-insurance-works/"


def _section(data, key):
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _number(data, key, *, signed=False):
    try:
        value = amount(data.get(key), key, minimum=None if signed else ZERO)
        # Keep extreme API inputs outside the representable household scenario.
        if value and not -10 <= value.adjusted() <= 15:
            return None
        return value if value else ZERO
    except FinanceInputError:
        return None


def _duration(data, key, *, limit=1200, allow_zero=False):
    n = _number(data, key)
    if n is not None and (0 if allow_zero else 1) <= n <= limit and n == int(n):
        return int(n)
    return None


def _aud(value):
    return f"A${Decimal(money(value)):,.2f}"


def _row(key, title, detail, action, source):
    return {"id": key, "title": title, "detail": detail, "action": action,
            "status": "unknown", "metrics": {}, "source_url": MONEYSMART + source}


def _property(data, cash):
    scope = data.get("scope")
    action = "Confirm who insures the building and obtain the written quote or policy schedule and current rebuild estimate."
    if scope == "strata":
        action = ("Ask the owners corporation for its building schedule, whole-scheme rebuild valuation, exclusions and "
                  "excess payable by your lot. Check any contents and lot improvements you must insure separately.")
    elif scope == "owner":
        action = ("Get a written building quote for this address. Check its annual premium, excess, covered events and "
                  "rebuild estimate including demolition, professional fees and site access.")
    row = _row("property", "Building insurance and excess",
               "The building responsibility, written terms or rebuild comparison still need confirmation.",
               action, "/home-insurance/choosing-home-insurance")
    if scope not in ("owner", "strata") or data.get("written_confirmed") is not True:
        return row
    premium, excess, insured, rebuild = (_number(data, key) for key in
                                         ("annual_premium", "excess", "sum_insured", "rebuild_cost"))
    gap = None if insured is None or not rebuild else max(ZERO, rebuild - insured)
    excess_gap = None if excess is None or cash is None else max(ZERO, excess - cash)
    row["metrics"] = dict(scope=scope, annual_premium=money(premium), excess=money(excess),
                          rebuild_gap=money(gap), excess_cash_gap=money(excess_gap))
    details = []
    if gap is not None:
        scale = "whole scheme" if scope == "strata" else "home"
        details.append(f"The written building limit for the {scale} is {_aud(insured)} against a rebuild estimate of "
                       f"{_aud(rebuild)}, leaving a rebuild shortfall of {_aud(gap)}.")
    if premium is not None:
        label = "scheme premium (check your levy share)" if scope == "strata" else "owner building premium"
        details.append(f"The annual {label} is {_aud(premium)}.")
    if excess_gap is not None:
        details.append(f"Your payable excess of {_aud(excess)} exceeds cash available above your reserve by {_aud(excess_gap)}."
                       if excess_gap else f"Available cash above your reserve covers your {_aud(excess)} payable excess.")
    if details:
        row["detail"] = " ".join(details)
    if (gap or excess_gap):
        row["status"] = "gap"
    elif None not in (premium, gap, excess_gap):
        row["status"] = "modelled"
    return row


def _loss(data, income):
    lost = _number(data, "lost_income_monthly")
    if income is None or lost is None or lost > income:
        return None
    return lost


def _illness(data, income, surplus, cash):
    row = _row("illness", "Illness or injury and the waiting period",
               "The waiting-period cash gap needs the household budget, income lost after paid leave, "
               "available cash and confirmed policy terms.",
               "Check eligibility, exclusions, payment in arrears, the benefit period and the after-tax benefit with the insurer.",
               LIFE + "income-protection-insurance")
    lost = _loss(data, income)
    if surplus is None or lost is None:
        return row
    deficit = max(ZERO, lost - surplus)
    row["metrics"]["monthly_gap_before_benefit"] = money(deficit)
    if data.get("policy_confirmed") is not True:
        row["detail"] = f"With the entered income loss, the budget needs {_aud(deficit)} per month before any insurance payment. Policy terms are unconfirmed."
        return row
    wait = _duration(data, "waiting_days", limit=3650, allow_zero=True)
    benefit = _number(data, "net_benefit_monthly")
    if wait is None or benefit is None or cash is None:
        return row
    required = deficit * wait / Decimal(30)
    bridge = max(ZERO, required - cash)
    ongoing = max(ZERO, deficit - benefit)
    row.update(status="gap" if bridge or ongoing else "modelled",
               detail=(f"Across {wait} days, the household needs {_aud(required)} from savings using 30-day months. "
                       f"Cash above your reserve leaves {_aud(bridge)} unfunded at the end of that wait. "
                       f"If a claim is accepted and the entered net benefit is paid, {_aud(ongoing)} per month remains uncovered. "
                       "Processing and payment in arrears can extend the cash bridge."))
    row["metrics"].update(waiting_days=wait, waiting_cash_required=money(required), waiting_cash_gap=money(bridge),
                          monthly_gap_if_paid=money(ongoing))
    return row


def _lump_sum(key, data, cash):
    death = key == "death"
    title = "Death and surviving household costs" if death else "Permanent disability and care costs"
    action = ("Confirm the policy, beneficiary and timing. Include the surviving household's after-tax income, "
              "ongoing housing costs and immediate expenses." if death else
              "Check the TPD definition and super release conditions. Include remaining after-tax income, "
              "care, housing costs and any immediate home modifications.")
    row = _row(key, title, "The funding gap needs the household's event-specific costs, income, horizon and policy terms.",
               action + " Count each debt once across upfront and ongoing costs.",
               LIFE + ("life-insurance-cover" if death else "total-and-permanent-disability-tpd-insurance"))
    income, costs, upfront = (_number(data, field) for field in
                             ("remaining_income_monthly", "ongoing_costs_monthly", "one_off_costs"))
    horizon = _duration(data, "horizon_months")
    if income is None or costs is None:
        return row
    monthly = max(ZERO, costs - income)
    row["metrics"].update(monthly_gap=money(monthly))
    if None in (upfront, horizon, cash):
        return row
    uncovered = max(ZERO, upfront + (costs - income) * horizon - cash)
    row["metrics"]["gap_without_benefit"] = money(uncovered)
    row["detail"] = (f"Remaining income of {_aud(income)} against {_aud(costs)} of monthly costs leaves a "
                     f"{_aud(monthly)} monthly gap. Over {horizon} months, including upfront costs and cash above "
                     f"your reserve, the unfunded amount before any payout is {_aud(uncovered)}.")
    benefit = _number(data, "benefit")
    delay = _duration(data, "payout_delay_months")
    if data.get("policy_confirmed") is not True or benefit is None:
        return row
    # A confirmed zero benefit has no payment date. A positive benefit needs
    # an explicit positive delay and a successful claim in the scenario.
    if benefit and delay is None:
        row["detail"] += " Enter a positive payment-delay assumption to test access to that benefit."
        return row
    bridge = max(ZERO, upfront + monthly * min(delay or horizon, horizon) - cash)
    counted = benefit if delay is not None and delay <= horizon else ZERO
    gap = max(ZERO, uncovered - counted)
    row["metrics"].update(bridge_gap=money(bridge), horizon_gap_if_paid=money(gap),
                          conditional_benefit_within_horizon=money(counted))
    row["status"] = "gap" if bridge or gap else "modelled"
    if benefit:
        row["detail"] += (f"With a payment delay of {delay} months, {_aud(bridge)} is unfunded before payment "
                          f"within this horizon. If the claim is accepted on those terms, the end gap is {_aud(gap)}.")
    else:
        row["detail"] += " The entered confirmed benefit is zero."
    return row


def _work(data, income, surplus, cash):
    job = _row("job_loss", "Job loss or redundancy",
               "Enter the take-home income at risk and the number of months to test a job loss.",
               "Check final pay and eligibility for any redundancy entitlement. Illness or injury cover supplies no payment in this scenario.",
               "/work-and-tax/losing-your-job")
    career = _row("career", "Career flexibility and savings goals",
                  "Enter your monthly goal allocation and the take-home income you would give up during a job change.",
                  "Choose an income change and transition length that fit your household's plans.",
                  "/budgeting/how-to-do-a-budget")
    if surplus is None:
        return job, career
    goal = _number(data, "goal_monthly")
    if goal is not None:
        career["metrics"].update(monthly_goal=money(goal), flexibility_after_goals=money(surplus - goal))
        career["detail"] = f"After setting aside {_aud(goal)} each month, {_aud(surplus - goal)} remains for other choices."
    lost = _loss(data, income)
    horizon = _duration(data, "duration_months")
    if lost is None:
        return job, career
    stressed = surplus - lost
    deficit = max(ZERO, -stressed)
    job["metrics"]["monthly_cash_deficit"] = money(deficit)
    job["detail"] = (f"Losing {_aud(lost)} in monthly take-home income leaves a monthly cash deficit of "
                     f"{_aud(deficit)} before insurance, redundancy pay or benefits.")
    if horizon is not None and cash is not None:
        gap = max(ZERO, deficit * horizon - cash)
        job["status"] = "gap" if gap else "modelled"
        job["metrics"]["cash_gap"] = money(gap)
        job["detail"] += f" Over {horizon} months this leaves {_aud(gap)} unfunded after cash above your reserve."
    if goal is not None:
        flex = stressed - goal
        career["metrics"]["flexibility_during_change"] = money(flex)
        career["detail"] += f" With {_aud(lost)} less take-home pay, the monthly balance after goals is {_aud(flex)}."
        if horizon is not None and cash is not None:
            gap = max(ZERO, -flex * horizon - cash)
            career["metrics"]["transition_gap"] = money(gap)
            career["status"] = "gap" if flex < 0 else "modelled"
            career["detail"] += f" Funding these goals through {horizon} months leaves an uncovered cash gap of {_aud(gap)}."
    return job, career


def buyer_protection(case: dict, survival: dict) -> dict:
    """Use the selected home's reconciled settlement cash and opening operating budget."""
    data = _section(case, "buyer_protection")
    settlement = _section(survival, "settlement")
    cash_after = _number(settlement, "cash_after_settlement")
    reserve = _number(settlement, "protected_reserve")
    cash = None
    if None not in (cash_after, reserve) and _number(settlement, "funding_gap") == ZERO:
        cash = max(ZERO, cash_after - reserve)
    timeline = _section(survival, "baseline").get("timeline")
    first = {}
    if isinstance(timeline, list):
        first = next((r for r in timeline if isinstance(r, dict) and r.get("month") == 1), {})
    income = _number(first, "income")
    surplus = _number(first, "net", signed=True)
    job, career = _work(_section(data, "career"), income, surplus, cash)
    basis = ("Settlement funding is confirmed in the case." if settlement.get("state") == "funded" else
             "Cash comparisons depend on settlement being funded as entered.")
    return {
        "illustrative": bool(case.get("finance_is_illustrative") or case.get("demonstration")),
        "assumptions": ("Each event is modelled separately using cash above the protected reserve. "
                        "Income change scenarios hold the first month's budget constant. "
                        "Income and personal policy benefits use after-tax estimates. A payout requires an accepted claim. " + basis),
        "rows": [_property(_section(data, "property"), cash), _illness(_section(data, "illness"), income, surplus, cash),
                 job, _lump_sum("disability", _section(data, "disability"), cash),
                 _lump_sum("death", _section(data, "death"), cash), career],
    }
