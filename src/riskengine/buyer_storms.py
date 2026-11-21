"""Versioned owner-occupier purchase stress scenarios, denominated in AUD.

The caller resolves evidence, permissions and policy eligibility before supplying
this flat profile. Omit unknown values. Explicit zero means a confirmed amount
of zero. Benefits and entitlements belong to the nominated highest earner.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Callable

from .finance import FinanceInputError, ONE, PRECISION, ZERO, amount, loan_schedule, money, monthly_payment


RULE_VERSION = "three-storms/1.0"
D = Decimal
RATE_SHOCK = D(".015")
INSURANCE_SHOCK = D(".20")
WORKS_MULTIPLIER = D("1.25")
WORKS_FLOOR = D("15000")
EXIT_FEE = D(".025")
EXIT_FIXED = D("3500")

FINANCE_FIELDS = ("purchase_price", "deposit", "capitalized_lmi", "cash_before_settlement",
                  "acquisition_costs", "annual_rate_decimal", "term_months")
LIVING_FIELDS = ("lean_living_monthly", "normal_living_monthly", "locked_commitments_monthly",
                 "property_costs_monthly", "insurance_annual", "urgent_works", "first_year_works")
PROTECTION_FIELDS = ("loss_duration_months", "redundancy_available", "leave_available",
                     "ip_wait_months", "death_cover", "tpd_cover")
FLAGS = ("insurable", "primary_works_approved", "structural_clear", "illiquid")


def _when(operation: Callable, *values):
    return operation(*values) if None not in values else None


def _number(value, name, *, signed=False):
    num = amount(value, name, minimum=None if signed else ZERO)
    # Household amounts use bounded precision and size. This also excludes rates
    # so small that adding the monthly rate to one would lose all significance.
    if num and (not -12 <= num.adjusted() <= 15 or len(num.as_tuple().digits) > 32):
        raise FinanceInputError(f"{name} exceeds supported precision or magnitude")
    return num if num else ZERO


class _Profile:
    def __init__(self, raw):
        self.values = {}
        self.issues = {}
        for key in FINANCE_FIELDS + LIVING_FIELDS + PROTECTION_FIELDS:
            if raw.get(key) is None:
                self.reject(key, "missing")
                continue
            try:
                self.values[key] = _number(raw[key], key)
            except FinanceInputError as exc:
                self.reject(key, str(exc))
        for key in FLAGS:
            if type(raw.get(key)) is bool:
                self.values[key] = raw[key]
            else:
                self.reject(key, "requires a confirmed boolean")
        incomes = raw.get("earner_incomes_monthly")
        try:
            if not isinstance(incomes, (list, tuple)) or not incomes:
                raise FinanceInputError("requires a list of monthly take-home amounts by earner")
            self.values["earner_incomes_monthly"] = [_number(n, "income") for n in incomes]
        except FinanceInputError as exc:
            self.reject("earner_incomes_monthly", str(exc))
        self.validate(raw)

    def reject(self, field, reason):
        self.values[field] = None
        self.issues[field] = reason

    def __getitem__(self, field):
        return self.values[field]

    def missing(self, fields):
        return sorted(set(fields).intersection(self.issues))

    def validate(self, raw):
        if self["purchase_price"] == ZERO:
            self.reject("purchase_price", "requires a positive purchase price")
        if _when(lambda d, p: d > p, self["deposit"], self["purchase_price"]):
            self.reject("deposit", "deposit exceeds purchase price")
        term = self["term_months"]
        if term is not None and (term != int(term) or not 1 <= term <= 1200):
            self.reject("term_months", "requires 1 to 1200 whole months")
        if self["annual_rate_decimal"] is not None and self["annual_rate_decimal"] > ONE:
            self.reject("annual_rate_decimal", "requires a decimal rate from zero to one")
        if self["loss_duration_months"] not in (None, 3, 4, 6):
            self.reject("loss_duration_months", "requires an explicit 3, 4 or 6 month scenario")
        if _when(lambda lean, normal: lean > normal, self["lean_living_monthly"], self["normal_living_monthly"]):
            for field in ("lean_living_monthly", "normal_living_monthly"):
                self.reject(field, "lean spending exceeds normal spending")
        if _when(lambda h, i: h * 12 < i, self["property_costs_monthly"], self["insurance_annual"]):
            for field in ("property_costs_monthly", "insurance_annual"):
                self.reject(field, "base annual insurance exceeds total property costs")
        self.values["principal"] = _when(lambda p, d, l: p - d + l, self["purchase_price"],
                                          self["deposit"], self["capitalized_lmi"])
        self.values["cash_after_settlement"] = _when(lambda w, d, a: w - d - a, self["cash_before_settlement"],
                                                      self["deposit"], self["acquisition_costs"])
        for field in ("principal", "cash_after_settlement"):
            if raw.get(field) is None:
                continue
            try:
                supplied = _number(raw[field], field, signed=field == "cash_after_settlement")
            except FinanceInputError as exc:
                self.reject(field, str(exc))
                continue
            if self[field] is not None and self[field] != supplied:
                self.reject(field, "supplied figure conflicts with the settlement calculation")


def _classify(red, decisive_unknown, amber=False):
    if any(test is True for test in red):
        return "red"
    if decisive_unknown:
        return "unresolved"
    return "amber" if amber else "green"


def _display_decimal(value):
    """Round ratios only for display. Decision comparisons use unrounded amounts."""
    return None if value is None else format(value, ".8f")


def _cash_fields(**fields):
    return {name: money(value) for name, value in fields.items()}


def _base(f):
    p, rate, term = (f[k] for k in ("principal", "annual_rate_decimal", "term_months"))
    schedules = []
    for delta, horizon in ((ZERO, 24), (RATE_SHOCK, 12)):
        schedule = None
        if None not in (p, rate, term) and rate + delta <= ONE:
            schedule = loan_schedule({"principal": p, "annual_rate_decimal": rate, "term_months": term},
                                     horizon, rate_delta_bps=delta * 10000)
        schedules.append(schedule)
    payment = schedules[0][0]["payment"] if schedules[0] else None
    earnings = f["earner_incomes_monthly"]
    income = sum(earnings, ZERO) if earnings is not None else None
    lean = _when(lambda m, e, h: m + e + h, payment, f["lean_living_monthly"], f["property_costs_monthly"])
    normal = _when(lambda m, e, h: m + e + h, payment, f["normal_living_monthly"], f["property_costs_monthly"])
    baseline = _cash_fields(principal=p, cash_after_settlement=f["cash_after_settlement"],
                            income_monthly=income, payment=payment, lean_burn=lean, normal_burn=normal,
                            normal_surplus=_when(lambda y, b: y - b, income, normal))
    return schedules, income, lean, baseline


DEBT_KEYS = ("principal", "purchase_price", "deposit", "capitalized_lmi", "term_months", "annual_rate_decimal")
CASH_KEYS = ("cash_after_settlement", "cash_before_settlement", "deposit", "acquisition_costs")
LEAN_KEYS = DEBT_KEYS + ("lean_living_monthly", "property_costs_monthly")


def _cash_ceiling(f):
    if f["cash_after_settlement"] is not None:
        return f["cash_after_settlement"]
    if "cash_after_settlement" in f.issues:
        return None  # A contradictory supplied cash figure requires reconciliation.
    return _when(lambda w: w - (f["deposit"] or ZERO) - (f["acquisition_costs"] or ZERO),
                 f["cash_before_settlement"])


def _vetoes(f, income, lean, base_schedule):
    cash = f["cash_after_settlement"]
    cash_ceiling = _cash_ceiling(f)
    lean_floor = (base_schedule[0]["payment"] if base_schedule else ZERO) + (
        f["lean_living_monthly"] or ZERO) + (f["property_costs_monthly"] or ZERO)
    flags = [f[key] for key in FLAGS[:3]]
    physical = {"status": _classify([v is False for v in flags], None in flags),
                "missing_inputs": f.missing(FLAGS[:3]), "flags": dict(zip(FLAGS[:3], flags))}
    values = (
        ("V2", cash, _when(lambda b: 2 * b, lean), cash_ceiling, lean_floor * 2, CASH_KEYS + LEAN_KEYS),
        ("V3", _when(lambda c, k: c - k, cash, f["urgent_works"]), lean,
         _when(lambda c: c - (f["urgent_works"] or ZERO), cash_ceiling), lean_floor, CASH_KEYS + LEAN_KEYS + ("urgent_works",)),
        ("V4", income, lean, income, lean_floor, LEAN_KEYS + ("earner_incomes_monthly",)),
    )
    rows = {"V1": physical}
    for key, available, required, ceiling, floor, dependencies in values:
        fails = _when(lambda a, b: a < b, available, required)
        bounded_failure = _when(lambda a: a < floor, ceiling)
        rows[key] = {"status": _classify([fails, bounded_failure], fails is None),
                     **_cash_fields(available=available, required=required, available_upper_bound=ceiling,
                                    required_lower_bound=floor),
                     "missing_inputs": f.missing(dependencies)}
    return rows


def _break_even(principal, term, room):
    """Nominal annual rate that exhausts lean income at the initial debt balance."""
    if None in (principal, term, room):
        return None, "unresolved"
    if not principal:
        return None, "no_loan" if room >= 0 else "deficit_without_debt"
    if monthly_payment(principal, ZERO, term) > room:
        return None, "deficit_even_at_zero_rate"
    if monthly_payment(principal, ONE, term) < room:
        return None, "above_100_percent"
    low, high = ZERO, ONE
    for _ in range(46):
        mid = (low + high) / 2
        if monthly_payment(principal, mid, term) <= room:
            low = mid
        else:
            high = mid
    return low, "calculated"


def _cash_path(cash, schedule, non_mortgage_surplus, works, due, horizon, term, *, upper_bound=False):
    """Keep cash known before a future unpriced repair or an unknown first payment."""
    amounts = [cash]
    paid = ZERO
    for month in range(1, horizon + 1):
        if schedule:
            row = schedule[month - 1]
            if row["annual_rate_decimal"] == ZERO:
                paid = schedule[0]["opening_balance"] * min(month, term) / term
            else:
                paid += row["payment"]
        elif not upper_bound:
            paid = None
        charge = works if month >= due else ZERO
        amounts.append(_when(lambda c, s, p, k: c + month * s - p - k,
                             cash, non_mortgage_surplus, paid, charge))
    return amounts


def _storm_a(f, income, schedule):
    room = _when(lambda y, e, h: y - e - h, income, f["lean_living_monthly"], f["property_costs_monthly"])
    premium = _when(lambda i: i * INSURANCE_SHOCK / 12, f["insurance_annual"])
    works = _when(lambda k: max(k * WORKS_MULTIPLIER, WORKS_FLOOR), f["first_year_works"])
    payment = schedule[0]["payment"] if schedule else None
    available = _when(lambda y, i: y - i, room, premium)
    lean_surplus = _when(lambda y, m: y - m, available, payment)
    normal_surplus = _when(lambda y, e, h, i, m: y - e - h - i - m, income, f["normal_living_monthly"],
                           f["property_costs_monthly"], premium, payment)
    stressed_burn = _when(lambda m, e, h: m + e + h, payment, f["lean_living_monthly"], f["property_costs_monthly"])
    balances = _cash_path(f["cash_after_settlement"], schedule, available, works, 3, 12, f["term_months"])
    c3, c12 = balances[3], balances[12]
    upper_room = _when(lambda y: y - (f["lean_living_monthly"] or ZERO) - (f["property_costs_monthly"] or ZERO), income)
    upper_operating = _when(lambda y: y - (premium or ZERO), upper_room)
    ceilings = _cash_path(_cash_ceiling(f), schedule, upper_operating, works if works is not None else WORKS_FLOOR,
                          3, 12, f["term_months"], upper_bound=True)
    # Compare debt service directly at the threshold to preserve exact equality.
    inadequate_margin = _when(lambda m, y: m > y, payment, room)
    threshold, threshold_state = _break_even(f["principal"], f["term_months"], room)
    margin = _when(lambda r, base: r - base, threshold, f["annual_rate_decimal"])
    red = [inadequate_margin, _when(lambda c: c < 0, c3), _when(lambda c: c < 0, c12),
           _when(lambda y: y < (payment or ZERO), upper_room) is True,
           any(c is not None and c < 0 for c in (ceilings[3], ceilings[12]))]
    green = _when(lambda s, n, c, end, burn: s >= 0 and n >= 0 and c >= burn and end >= 3 * burn,
                  lean_surplus, normal_surplus, c3, c12, stressed_burn)
    deps = LEAN_KEYS + CASH_KEYS + ("first_year_works", "earner_incomes_monthly", "insurance_annual", "normal_living_monthly")
    missing = f.missing(deps)
    if f["annual_rate_decimal"] is not None and f["annual_rate_decimal"] + RATE_SHOCK > ONE:
        missing.append("stressed_rate_outside_supported_range")
    return {"status": _classify(red, None in red or green is None, green is False), "missing_inputs": missing,
            "monthly_cash": [money(v) for v in balances],
            "break_even_rate_decimal": _display_decimal(threshold), "break_even_state": threshold_state,
            "rate_margin_decimal": _display_decimal(margin),
            **_cash_fields(stressed_payment=payment, incremental_premium_monthly=premium,
                           works_month3=works, stressed_lean_burn=stressed_burn, lean_surplus=lean_surplus,
                           normal_surplus=normal_surplus, cash_month3=c3, cash_month12=c12,
                           cash_month3_upper_bound=ceilings[3], cash_month12_upper_bound=ceilings[12])}


def _storm_b(f, lean):
    incomes = f["earner_incomes_monthly"]
    nominated = incomes.index(max(incomes)) if incomes else None
    remaining = sum(incomes, ZERO) - incomes[nominated] if incomes else None
    locked = _when(lambda b, k: b + k, lean, f["locked_commitments_monthly"])
    gap = _when(lambda b, y: max(ZERO, b - y), locked, remaining)
    cash = f["cash_after_settlement"]
    available = _when(lambda c, r, a: c + r + a, cash, f["redundancy_available"], f["leave_available"])
    duration = f["loss_duration_months"]
    runway = _when(lambda c, g: c / g if g else None, available, gap)
    if gap == ZERO and cash is not None and cash >= ZERO:
        runway_state = "self_funding"
        runway_fails = tight_runway = False
    else:
        runway_state = "unresolved" if runway is None else "finite"
        runway_fails = _when(lambda c, g, n: c < g * n, available, gap, duration)
        tight_runway = _when(lambda c, g, n: c < g * (n + 2), available, gap, duration)
    # Job termination entitlements and death/TPD benefits are unavailable in
    # this separate illness waiting-period scenario.
    wait_gap = _when(lambda c, g, w: max(ZERO, g * w - c), cash, gap, f["ip_wait_months"])
    if gap == ZERO and cash is not None and cash >= ZERO:
        wait_gap = ZERO
    required = _when(lambda p: p * D(".80"), f["principal"])
    def cover_gap(key):
        if required == ZERO:
            return ZERO
        return _when(lambda r, a: max(ZERO, r - a), required, f[key])
    death_gap, tpd_gap = cover_gap("death_cover"), cover_gap("tpd_cover")
    cautions = [tight_runway, *[_when(lambda a: a > 0, v) for v in (wait_gap, death_gap, tpd_gap)]]
    # A known caution settles B only once a more severe runway failure is ruled out.
    unresolved = duration is None or runway_fails is None or (True not in cautions and None in cautions)
    return {"status": _classify([runway_fails], unresolved, True in cautions),
            "missing_inputs": f.missing(CASH_KEYS + LEAN_KEYS + PROTECTION_FIELDS +
                                         ("earner_incomes_monthly", "locked_commitments_monthly")),
            "nominated_earner_index": nominated, "loss_duration_months": int(duration) if duration else None,
            "runway_state": runway_state, "runway_months": _display_decimal(runway),
            **_cash_fields(remaining_income=remaining, locked_burn=locked, monthly_gap=gap,
                           redundancy_available=f["redundancy_available"], leave_available=f["leave_available"],
                           job_loss_cash=available, illness_wait_gap=wait_gap, required_event_cover=required,
                           death_cover_gap=death_gap, tpd_cover_gap=tpd_gap)}


def _storm_c(f, income, schedule):
    price = f["purchase_price"]
    dip = None if f["illiquid"] is None else D(".15") if f["illiquid"] else D(".10")
    sale = _when(lambda p, d: p * (ONE - d), price, dip)
    costs = _when(lambda v: v * EXIT_FEE + EXIT_FIXED, sale)
    debt = schedule[-1]["closing_balance"] if schedule else None
    if schedule and f["annual_rate_decimal"] == ZERO:
        # Subtracting a recurring decimal repayment 24 times can put an exact
        # LVR or wealth-loss boundary a few units off in the 40th digit.
        term = f["term_months"]
        debt = f["principal"] * max(ZERO, term - 24) / term
    equity = _when(lambda s, c, l: s - c - l, sale, costs, debt)
    lvr = _when(lambda l, s: l / s, debt, sale)
    initial = _when(lambda d, a: d + a, f["deposit"], f["acquisition_costs"])
    loss = _when(lambda i, e, w: (i - e) / w if w else None, initial, equity, f["cash_before_settlement"])
    operating = _when(lambda y, e, h: y - e - h, income, f["normal_living_monthly"], f["property_costs_monthly"])
    path = _cash_path(f["cash_after_settlement"], schedule, operating, f["first_year_works"], 12, 24, f["term_months"])
    upper_operating = _when(lambda y: y - (f["normal_living_monthly"] or ZERO) - (f["property_costs_monthly"] or ZERO), income)
    ceilings = _cash_path(_cash_ceiling(f), schedule, upper_operating, f["first_year_works"] or ZERO,
                          12, 24, f["term_months"], upper_bound=True)
    cash = path[-1]
    known = [value for value in path if value is not None]
    first_short = next((m for m, c in enumerate(path) if c is not None and c < 0), None)
    short_by = next((m for m, c in enumerate(ceilings) if c is not None and c < 0), None)
    proceeds = _when(lambda e, c: e + c, equity, cash)
    presale_failed = True if first_short is not None else False if None not in path else None
    red = [presale_failed, short_by is not None, _when(lambda n: n < 0, proceeds),
           _when(lambda n: n > D(".75"), loss)]
    green = _when(lambda e, l, n: e >= 0 and l <= D(".80") and n < D(".40"), equity, lvr, loss)
    missing = f.missing(CASH_KEYS + DEBT_KEYS + ("earner_incomes_monthly", "normal_living_monthly",
                                                  "property_costs_monthly", "first_year_works", "illiquid"))
    if f["cash_before_settlement"] == ZERO:
        missing.append("wealth_loss_fraction_undefined_at_zero_cash")
    return {"status": _classify(red, None in red or green is None, green is False), "missing_inputs": missing,
            "dip_decimal": _display_decimal(dip), "lvr_decimal": _display_decimal(lvr),
            "wealth_loss_fraction": _display_decimal(loss), "first_presale_shortfall_month": first_short,
            "presale_shortfall_by_month": short_by,
            "monthly_cash": [money(v) for v in path],
            **_cash_fields(sale_price=sale, selling_costs=costs, balance_month24=debt, net_sale_equity=equity,
                           cash_month24=cash, minimum_presale_cash=min(known) if len(known) == len(path) else None,
                           cash_after_sale=proceeds)}


def evaluate_storms(profile: dict) -> dict:
    """Evaluate one normalized profile without mutating it. All rates are decimal annual rates."""
    if not isinstance(profile, dict):
        raise FinanceInputError("storm profile must be an object")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        f = _Profile(profile)
        (schedule, shocked), income, lean, baseline = _base(f)
        vetoes = _vetoes(f, income, lean, schedule)
        storms = {"A": _storm_a(f, income, shocked), "B": _storm_b(f, lean), "C": _storm_c(f, income, schedule)}
        rows = [*vetoes.values(), *storms.values()]
        states = [row["status"] for row in rows]
        return {"rule_version": RULE_VERSION,
                "verdict": _classify(["red" in states], "unresolved" in states, "amber" in states),
                "baseline": baseline, "vetoes": vetoes, "storms": storms,
                "missing_inputs": sorted(set().union(*(row["missing_inputs"] for row in rows))),
                "input_issues": f.issues,
                "assumptions": {
                    "cash": "Day-two cash equals starting liquid cash less deposit and acquisition costs. Financed LMI adds to principal.",
                    "living": "Lean and normal living exclude property costs. Property costs include the base annual insurance premium. Additional locked commitments are a separate Storm B stress input.",
                    "loan": "Level monthly principal and interest at nominal annual rates. Payments stop at maturity. Money is rounded only for presentation.",
                    "A": "Rate rises by 0.015. Insurance rises 20%. Month 3 works cost the greater of 1.25 times first-year works or AUD 15,000. The break-even rate uses base property costs.",
                    "B": "Remove the largest monthly take-home income. Ties nominate the first listed earner. Only confirmed, immediately available net job-loss entitlements count. Illness, death and TPD are separate events.",
                    "C": "Sell at month 24 after a single 10% dip, or 15% if illiquid. Selling costs are 2.5% plus AUD 3,500. First-year works are charged once at month 12. Check every pre-sale cash balance.",
                }}
