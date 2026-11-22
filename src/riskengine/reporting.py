"""Readable standalone presentation of a permission-checked assessment.

This module formats engine values. It never reruns risk rules or calculates a
new cash scenario. Text, HTML attributes and SVG tooltips are all escaped.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import html
import json
from typing import Any
from urllib.parse import urlsplit


def _text(value: Any) -> str:
    if value is None:
        return "Not assessed"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return str(value)


def _e(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _words(value: Any) -> str:
    return _text(value).replace("_", " ").lower().capitalize()


def _number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or len(str(value)) > 120:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and abs(number) < Decimal("1e30") else None
    except (InvalidOperation, ValueError):
        return None


def _money(value: Any) -> str:
    number = _number(value)
    return "Not assessed" if number is None else ("−" if number < 0 else "") + "A$" + format(abs(number), ",.2f")


def _priority(value: Any) -> str:
    return f"{value} / 4" if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4 else "Not assessed"


def _tone(value: Any) -> str:
    return "high" if value in (3, 4) else "medium" if value in (1, 2) else "neutral"


def _details(title: str, value: Any) -> str:
    return f'<details class="evidence"><summary>{_e(title)}</summary><pre>{_e(value)}</pre></details>'


def _decision_reference(value: str) -> str:
    try:
        address = urlsplit(value)
        if address.scheme in ("https", "http") and address.hostname and not address.username:
            return f'<a href="{_e(value)}">{_e(value)}</a>'
    except ValueError:
        pass
    return _e(value)


def _brief_values(data):
    """Show captured price evidence and assumptions in the same order as the result."""
    if isinstance(data, dict):
        return '<dl>' + ''.join(f'<dt><strong>{_e(_words(key))}</strong></dt><dd>{_brief_values(value)}</dd>'
                                for key, value in data.items()) + '</dl>'
    if isinstance(data, list):
        if not data:
            return '<span class="muted">None recorded</span>'
        return '<ul>' + ''.join(f'<li>{_brief_values(value)}</li>' for value in data) + '</ul>'
    if isinstance(data, str):
        return _decision_reference(data)
    return _e(data)


def _household_decision(result):
    brief = result.get("preoffer_brief") or {}
    survival = brief.get("survival")
    if not survival:
        return ""
    combined, baseline = survival["combined"], survival["baseline"]
    settlement = survival["settlement"]
    tag = "Illustrative household scenario" if brief.get("illustrative_finance") else "Household scenario"
    month = combined.get("first_reserve_breach_month")
    breach = ("At settlement" if month == 0 else f"Month {month}") if month is not None else (
        "Held through month 12" if combined.get("timeline") and settlement.get("protected_reserve") is not None else "Not assessed")
    metrics = [
        _metric("Cash after settlement", _money(settlement.get("cash_after_settlement")), "Available to the household"),
        _metric("First-year cash out", _money(combined["first_year"].get("total_cash_out")), "Includes settlement, household expenses, repayments and the repair"),
        _metric("Lowest first-year cash", _money(combined.get("minimum_cash")), "Under the combined scenario"),
        _metric("First reserve breach", breach, "Protected reserve " + _money(settlement.get("protected_reserve"))),
    ]
    content = [f'<section class="section"><p class="card-meta">{tag}</p><h2>Can the household carry the first year?</h2>',
               f'<p class="intro"><strong>{_e(survival["headline"])}</strong></p><p>{_e(survival.get("detail"))}</p>',
               '<div class="metric-grid">' + ''.join(metrics) + '</div>',
               f'<p><strong>Property decision</strong> {_e(brief["property_decision"]["headline"])}</p>',
               f'<p><strong>Next action</strong> {_e(brief.get("next_action"))}</p>']
    if survival.get("missing_inputs"):
        content.append('<p><strong>Inputs still needed</strong> ' +
                       ', '.join(_e(_words(key)) for key in survival["missing_inputs"]) + '</p>')
    for heading, scenario in (("Ordinary first year", baseline), ("Combined stress", combined)):
        timeline = scenario.get("timeline", [])
        summary = {key: value for key, value in scenario.items() if key != "timeline"}
        table = ""
        if timeline:
            columns = ("income", "mortgage", "outgoings", "repair", "net", "cash")
            body = ''.join('<tr><th scope="row">' + _e(row.get("month")) + '</th>' +
                           ''.join(f'<td>{_money(row.get(key))}</td>' for key in columns) + '</tr>' for row in timeline)
            table = ('<div class="table-wrap"><table><thead><tr><th>Month</th>' +
                     ''.join(f'<th>{_e(_words(key))}</th>' for key in columns) +
                     '</tr></thead><tbody>' + body + '</tbody></table></div>')
        content.append(f'<details class="group-details"><summary>{heading}</summary>{_brief_values(summary)}{table}</details>')
    for heading, value in (("What changed under stress", survival.get("first_year_difference")), ("Settlement and purchase costs", settlement),
                           ("Resale after three and five years", survival.get("exit_scenarios")),
                           ("Interest rate at break-even (%)", survival.get("break_even_rate_pct")),
                           ("Household assumptions", survival.get("assumptions")), ("Calculation basis", survival.get("basis"))):
        content.append(f'<details class="group-details"><summary>{heading}</summary>{_brief_values(value)}</details>')
    content.append('</section>')
    for heading, group, key in (("Insurance, income and life changes", "protection", "rows"),
                                ("Property condition, price and negotiating position", "underwriting", "sections")):
        content.append(f'<section class="section"><h2>{heading}</h2>')
        for row in brief[group].get(key, []):
            content.append(f'<article class="evidence-card"><h3>{_e(row["title"])}</h3><p class="card-meta">{_e(_words(row.get("status")))}</p>'
                           f'<p>{_e(row.get("detail"))}</p><p><strong>Next action</strong> {_e(row.get("action"))}</p>')
            if row.get("metrics"):
                content.append('<details><summary>Figures and assumptions</summary>' + _brief_values(row["metrics"]) + '</details>')
            for ref in row.get("references", []) or []:
                content.append(f'<p class="support">{_brief_values(ref)}</p>')
            if row.get("source_url"):
                content.append(f'<p class="support">{_brief_values(row["source_url"])}</p>')
            content.append('</article>')
        content.append('</section>')
    return ''.join(content)


def _preoffer(result):
    brief = result.get("preoffer_brief")
    if not isinstance(brief, dict):
        return ""
    cards = []
    for index, item in enumerate(brief.get("top_three", []), 1):
        detail = [f'<p class="card-meta">{_e(item.get("kind"))}</p>', f'<p>{_e(item.get("detail"))}</p>']
        for key, title in (("action", "Next action"), ("changes_outcome", "What could change this"),
                           ("confidence", "Confidence"), ("geography", "Geographic scope"), ("as_of", "Evidence date")):
            if item.get(key):
                detail.append(f'<p><strong>{title}</strong> {_e(item[key])}</p>')
        refs = item.get("references") or []
        if refs:
            detail.append('<p class="support">' + ' · '.join(_decision_reference(ref) for ref in refs if isinstance(ref, str)) + '</p>')
        cards.append(f'<article class="evidence-card"><h3>{index}. {_e(item["title"])}</h3>{"".join(detail)}</article>')
    costs = brief.get("costs") or {}
    price = costs.get("price_evidence") or {}
    finance = costs.get("offer_comparison") or []
    offer = brief.get("offer") or {}
    terms = ""
    if offer.get("offer_price") is not None:
        basis = {"asking": "Asking price", "proposed_offer": "Proposed offer"}.get(offer.get("price_basis"), "Entered price")
        terms = f'<p><strong>{basis}</strong> {_money(offer["offer_price"])}'
        if offer.get("intended_use"):
            terms += f' · {_e(_words(offer["intended_use"]))}'
        terms += '</p>'
    summary = ""
    if price.get("summary"):
        summary = f'<h3>Comparable sales</h3><p>{_e(price["summary"])}</p>'
    if finance:
        columns = (("offer_price", "Offer"), ("cash_required", "Cash required"), ("monthly_repayment", "Monthly repayment"),
                   ("minimum_cash", "Lowest cash balance"), ("break_even_resale", "Break-even resale"))
        cells = ''.join('<tr><th scope="row">' + _e(row.get("label")) + '</th>'
                        + ''.join(f'<td>{_money(row.get(key))}</td>' for key, _ in columns) + '</tr>' for row in finance)
        summary += ('<h3>Offer comparison</h3><div class="table-wrap"><table><thead><tr><th>Scenario</th>'
                    + ''.join(f'<th>{label}</th>' for _, label in columns)
                    + '</tr></thead><tbody>' + cells + '</tbody></table></div>')
    breakdown = ''.join(f'<details class="group-details"><summary>{_e(_words(key))}</summary>{_brief_values(costs[key])}</details>'
                        for key in ("price_evidence", "offer_comparison", "assumptions") if key in costs)
    coverage = brief.get("coverage") or {}
    return ('<section class="section" aria-labelledby="preoffer-heading"><h2 id="preoffer-heading">Pre-offer brief</h2>'
            f'<p class="intro"><strong>{_e(brief.get("headline"))}</strong></p><p>{_e(brief.get("summary"))}</p>'
            f'<p><strong>Next action</strong> {_e(brief.get("next_action"))}</p>'
            + terms + '<div class="card-grid">' + ''.join(cards) + '</div>' + summary + breakdown
            + _details("Pre-offer coverage and check states", coverage) + '</section>')


def _purchase_decision(result: dict) -> str:
    decision = result.get("purchase_decision")
    if not isinstance(decision, dict):
        return ""
    sections = []
    for key, label in (("drivers", "What drives this decision"), ("open_checks", "Checks to resolve"),
                       ("context_notes", "Local evidence and its scope")):
        cards = []
        for item in decision.get(key, []):
            refs = [_decision_reference(r) for r in item.get("references", []) if isinstance(r, str)]
            parts = [f'<h4>{_e(item["title"])}</h4>', f'<p>{_e(item["detail"])}</p>']
            if item.get("as_of"):
                parts.append(f'<p class="card-meta">Evidence as of {_e(item["as_of"])}</p>')
            if item.get("action"):
                parts.append(f'<p><strong>Action</strong> {_e(item["action"])}</p>')
            if item.get("changes_outcome"):
                parts.append(f'<p><strong>What could change this</strong> {_e(item["changes_outcome"])}</p>')
            if refs:
                parts.append('<p class="support">' + ' · '.join(refs) + '</p>')
            cards.append('<article class="evidence-card">' + ''.join(parts) + '</article>')
        if cards:
            sections.append(f'<h3>{label}</h3><div class="card-grid">' + ''.join(cards[:3]) + '</div>')
            if len(cards) > 3:
                sections.append(f'<details class="group-details"><summary>Show {len(cards) - 3} more</summary>'
                                '<div class="card-grid">' + ''.join(cards[3:]) + '</div></details>')
    illustration = '<p class="support">Buyer finances use illustrative assumptions.</p>' if decision.get("illustrative_finance") else ''
    return (
        '<section class="section" aria-labelledby="decision-heading"><h2 id="decision-heading">Purchase decision</h2>'
        f'<p class="intro"><strong>{_e(decision["headline"])}</strong></p><p>{_e(decision["summary"])}</p>'
        f'<p><strong>Next action</strong> {_e(decision["next_action"])}</p>{illustration}'
        + ''.join(sections) + _details("Captured decision evidence", result.get("decision_evidence")) + '</section>'
    )


def _checks(result: dict) -> list[dict]:
    checks = result.get("check_results", [])
    if isinstance(checks, dict):
        checks = [{"check_id": key, **value} if isinstance(value, dict) else {"check_id": key, "result": value} for key, value in checks.items()]
    return [check for check in checks if isinstance(check, dict)] if isinstance(checks, list) else []


def _cards(items: list, empty: str, kind: str, labels: dict) -> str:
    if not items:
        return f'<p class="muted empty">{_e(empty)}</p>'
    cards = []
    for item in items:
        if not isinstance(item, dict):
            cards.append(f'<article class="evidence-card"><p>{_e(item)}</p></article>')
            continue
        cid = item.get("check_id")
        priority = item.get("action_priority", item.get("priority", item.get("gap_priority")))
        label = item.get("title") or item.get("label") or labels.get(cid) or item.get("domain") or "Evidence item"
        if kind == "opportunity":
            summary = item.get("benefit") or item.get("summary") or item.get("scope")
            tag = "Conditional opportunity" if item.get("conditional") is not False else "Recorded opportunity"
            tone = "opportunity"
        elif kind == "gap":
            summary = _words(item.get("reason")) if item.get("reason") else item.get("summary")
            tag = ("Critical gap" if item.get("critical") is True else "Evidence gap") + " · priority " + _priority(priority)
            tone = "high" if item.get("critical") is True else "medium"
        else:
            summary = item.get("summary") or item.get("finding") or item.get("reason")
            tag, tone = "Finding priority " + _priority(priority), _tone(priority)
        metadata = [str(value) for value in (cid, item.get("domain"), (str(item["confidence"]) + " confidence") if item.get("confidence") else None) if value]
        extra = []
        if item.get("next_action"):
            extra.append(f'<p class="support"><strong>Next action:</strong> {_e(item["next_action"])}</p>')
        if kind == "opportunity":
            if item.get("available_from"):
                extra.append(f'<p class="support"><strong>Stated availability:</strong> {_e(item["available_from"])}</p>')
            dependencies = item.get("dependencies")
            if isinstance(dependencies, list) and dependencies:
                extra.append('<p class="support"><strong>Depends on:</strong> ' + _e("; ".join(_text(value) for value in dependencies)) + '</p>')
            if item.get("price_uplift") is None:
                extra.append('<p class="support">No price uplift quantified. This benefit does not reduce adverse priorities.</p>')
        detail = item.get("details")
        if (kind == "finding" and item.get("rule_id") == "LG01" and priority == 3
                and isinstance(detail, dict) and detail.get("evidence_kind") == "restriction" and detail.get("reviewed")):
            tag = "Source statement · legal effect awaits title verification · priority " + _priority(priority)
            extra.append('<p class="support">Have the conveyancer verify the registered title, plan and instruments before relying on this statement.</p>')
        if isinstance(detail, dict) and detail.get("scope"):
            extra.append(f'<p class="support">{_e(detail["scope"])}</p>')
        cards.append(f'<article class="evidence-card {tone}"><div class="card-meta">{_e(" · ".join(metadata))}</div>'
                     f'<h3>{_e(label)}</h3><p class="tag {tone}">{_e(tag)}</p>'
                     + (f'<p class="card-summary">{_e(summary)}</p>' if summary is not None else '')
                     + ''.join(extra) + _details("Evidence and calculation details", item) + '</article>')
    return '<div class="card-grid">' + ''.join(cards) + '</div>'


def _metric(label: str, value: Any, note: str = "", tone: str = "") -> str:
    return f'<div class="metric {tone}"><div class="metric-label">{_e(label)}</div><div class="metric-value">{_e(value)}</div><p>{_e(note)}</p></div>'


def _state_note(component: dict, default: str = "") -> str:
    if component.get("state") == "ASSESSED":
        return default
    note = _words(component.get("reason") or "NOT_ASSESSED")
    missing = component.get("missing_inputs")
    if isinstance(missing, list) and missing:
        note += ": " + ", ".join(_text(value).replace("_", " ") for value in missing)
    return note


def _assumptions(scenario: dict) -> str:
    assumptions = scenario.get("assumptions", {})
    if not isinstance(assumptions, dict):
        return ""
    result = []
    shock = _number(assumptions.get("rate_delta_bps"))
    if shock is not None:
        result.append(f"Loan rate {shock / Decimal(100):+.2f} percentage points")
    for key, label in (("income_factor", "income"), ("property_cost_factor", "property costs"), ("rent_factor", "rent")):
        value = _number(assumptions.get(key))
        if value is not None:
            result.append(f"{label} {value * 100:g}% of baseline")
    return "; ".join(result)


def _reserve_chart(scenarios: list[dict]) -> str:
    """Plot captured cash values; missing monthly values are never invented."""
    series = []
    for scenario in scenarios:
        if scenario.get("state") != "ASSESSED":
            continue
        initial, reserve = _number(scenario.get("initial_cash")), _number(scenario.get("protected_reserve"))
        schedule = scenario.get("monthly_schedule")
        if initial is None or reserve is None or not isinstance(schedule, list) or not schedule:
            continue
        points = [(Decimal(0), initial, scenario.get("initial_cash"))]
        valid = True
        for row in schedule:
            if not isinstance(row, dict):
                valid = False
                break
            month, cash = _number(row.get("month")), _number(row.get("closing_cash"))
            if month is None or cash is None or month != points[-1][0] + 1:
                valid = False
                break
            points.append((month, cash, row.get("closing_cash")))
        if valid:
            series.append((scenario, points, reserve))
    if not series:
        return '<p class="muted empty">A cash chart will appear when an assessed scenario includes its monthly cash schedule.</p>'
    left, right, top, bottom = Decimal(110), Decimal(910), Decimal(30), Decimal(300)
    max_month = max(points[-1][0] for _, points, _ in series)
    values = [cash for _, points, _ in series for _, cash, _ in points] + [reserve for _, _, reserve in series]
    low, high = min(Decimal(0), min(values)), max(values)
    span = high - low or Decimal(1)
    high += span * Decimal("0.10")
    if low < 0:
        low -= span * Decimal("0.06")
    span = high - low
    def x(month):
        return float(left + month / max_month * (right - left))
    def y(cash):
        return float(bottom - (cash - low) / span * (bottom - top))
    marks = []
    for index in range(5):
        cash = low + span * Decimal(index) / 4
        marks.append(f'<line x1="{left}" y1="{y(cash):.2f}" x2="{right}" y2="{y(cash):.2f}" class="chart-grid"/>'
                     f'<text x="98" y="{y(cash) + 4:.2f}" text-anchor="end" class="axis-label">{_e(_money(cash))}</text>')
    step = max(1, (int(max_month) + 5) // 6)
    for month in sorted(set(range(0, int(max_month) + 1, step)) | {int(max_month)}):
        marks.append(f'<text x="{x(Decimal(month)):.2f}" y="326" text-anchor="middle" class="axis-label">{month}</text>')
    marks.append('<text x="510" y="350" text-anchor="middle" class="axis-label">Month from scenario start</text>')
    for reserve in sorted({reserve for _, _, reserve in series}):
        marks.append(f'<line x1="{left}" y1="{y(reserve):.2f}" x2="{right}" y2="{y(reserve):.2f}" class="reserve-line"/>'
                     f'<text x="{left + 8}" y="{y(reserve) - 9:.2f}" class="reserve-label">Protected reserve {_e(_money(reserve))}</text>')
    colours = ("#176b87", "#bd601c", "#7451a0", "#a63b50", "#087b6d", "#465a6e")
    legend, paths = [], []
    for index, (scenario, points, reserve) in enumerate(series):
        colour = colours[index % len(colours)]
        dash = ' stroke-dasharray="9 6"' if index % 2 else ''
        scenario_id = _text(scenario.get("scenario_id"))
        coords = " ".join(f"{x(month):.2f},{y(cash):.2f}" for month, cash, _ in points)
        paths.append(f'<polyline fill="none" stroke="{colour}" stroke-width="3.5" points="{coords}"{dash} data-scenario="{_e(scenario_id)}"/>')
        for month, cash, exact in points:
            breach = scenario.get("first_breach_month") == int(month)
            radius = "5.5" if breach else "3"
            title = f"{scenario_id}: month {int(month)}; cash {_money(exact)}; protected reserve {_money(reserve)}"
            if breach:
                title += "; first recorded reserve breach"
            paths.append(f'<circle cx="{x(month):.2f}" cy="{y(cash):.2f}" r="{radius}" fill="white" stroke="{colour}" stroke-width="2" '
                         f'data-scenario="{_e(scenario_id)}" data-month="{int(month)}" data-cash="{_e(exact)}"><title>{_e(title)}</title></circle>')
        end_month, end_cash, exact = points[-1]
        paths.append(f'<text x="{x(end_month) - 7:.2f}" y="{y(end_cash) - 12:.2f}" text-anchor="end" fill="{colour}" class="ending-label">{_e(_money(exact))}</text>')
        legend.append(f'<span><i style="background:{colour}"></i>{_e(scenario_id)} · ends at month {int(end_month)}</span>')
    return ('<div class="chart-frame"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 360" role="img" aria-labelledby="cash-chart-title cash-chart-description">'
            '<title id="cash-chart-title">Cash against the protected reserve</title><desc id="cash-chart-description">Monthly cash values from assessed scenarios. Dashed horizontal lines show the protected reserves. Each path ends at its stated duration.</desc>'
            + ''.join(marks + paths) + '</svg><div class="chart-legend">' + ''.join(legend) + '</div>'
            '<p class="support">Points use the engine’s recorded monthly cash values. Hover for exact amounts. Overlapping scenarios may follow the same path until the shorter one ends.</p></div>')


def _finance(finance: Any) -> str:
    if not isinstance(finance, dict):
        return '<p class="muted empty">No structured financial assessment supplied.</p>' + _details("Supplied financial output", finance)
    repayment, baseline, settlement, buffer = [finance.get(key, {}) if isinstance(finance.get(key, {}), dict) else {} for key in ("repayment", "baseline", "settlement", "buffer")]
    metrics = [
        _metric("Monthly loan repayment", _money(repayment.get("monthly_payment")) if repayment.get("state") == "ASSESSED" else "Not assessed", _state_note(repayment, "Initial principal and interest payment")),
        _metric("Baseline monthly surplus", _money(baseline.get("monthly_surplus")) if baseline.get("state") == "ASSESSED" else "Not assessed", _state_note(baseline, "After the submitted mortgage and household costs"), _tone(baseline.get("priority"))),
        _metric("Settlement funding gap", _money(settlement.get("funding_gap")) if settlement.get("state") == "ASSESSED" else "Not assessed", _state_note(settlement, "Day-one funding, separate from monthly cash flow"), _tone(settlement.get("priority"))),
        _metric("Cash after settlement", _money(buffer.get("cash_after_settlement")) if buffer.get("state") == "ASSESSED" else "Not assessed", _state_note(buffer, "Protected reserve: " + _money(buffer.get("protected_reserve")))),
    ]
    rows = []
    for label, component, fields in (
        ("Loan", repayment, (("principal", "Principal"), ("monthly_payment", "Monthly repayment"))),
        ("Monthly budget", baseline, (("income_monthly", "Income"), ("living_monthly", "Living costs"), ("other_debt_monthly", "Other debt"), ("property_costs_monthly", "Property costs"), ("monthly_surplus", "Surplus"))),
        ("Settlement", settlement, (("required_funds", "Required funds"), ("allocated_funds", "Allocated funds"), ("funding_gap", "Funding gap"))),
        ("Cash reserve", buffer, (("cash_after_settlement", "Cash available"), ("protected_reserve", "Protected reserve"), ("shortfall", "Reserve shortfall"))),
    ):
        amounts = " · ".join(f"{name}: {_money(component.get(key))}" for key, name in fields if component.get(key) is not None)
        note = _state_note(component, component.get("scope") or component.get("basis") or "")
        rows.append(f'<tr><th scope="row">{_e(label)}</th><td>{_e(_words(component.get("state")))}</td><td>{_e(amounts or note)}'
                    + (f'<div class="support">{_e(note)}</div>' if amounts and note else '') + '</td></tr>')
    scenarios = [row for row in finance.get("scenarios", []) if isinstance(row, dict)] if isinstance(finance.get("scenarios", []), list) else []
    scenario_rows = []
    for scenario in scenarios:
        assessed = scenario.get("state") == "ASSESSED"
        breach = scenario.get("first_breach_month")
        if not assessed:
            breach_text = _state_note(scenario)
        elif scenario.get("reserve_breached") is True:
            breach_text = "At scenario start" if breach == 0 else f"Month {breach}" if breach is not None else "Breach recorded; timing unavailable"
        elif scenario.get("reserve_breached") is False:
            breach_text = "No breach within this period"
        else:
            breach_text = "Not assessed"
        heading = f'<strong>{_e(scenario.get("scenario_id"))}</strong><span class="support block">{_e(_assumptions(scenario))}</span>'
        cells = [heading, _e(str(scenario["duration_months"]) + " months") if scenario.get("duration_months") is not None else "Not assessed"]
        cells += [_e(_money(scenario.get(key))) if assessed else "Not assessed" for key in ("minimum_cash", "ending_cash", "protected_reserve")]
        cells += [_e(breach_text), _e(_priority(scenario.get("priority")))]
        scenario_rows.append('<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>')
    scenario_table = ('<div class="table-wrap"><table class="scenario-table"><thead><tr><th>Scenario and assumptions</th><th>Duration</th><th>Lowest cash</th><th>Closing cash</th><th>Protected reserve</th><th>First reserve breach</th><th>Priority</th></tr></thead><tbody>' + ''.join(scenario_rows) + '</tbody></table></div>') if scenario_rows else '<p class="muted empty">No stress scenarios were supplied.</p>'
    return ('<div class="metric-grid finance-metrics">' + ''.join(metrics) + '</div>'
            '<div class="table-wrap"><table><thead><tr><th>Financial check</th><th>State</th><th>Recorded amounts and scope</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
            '<h3 class="subheading">Cash and reserve over time</h3>' + _reserve_chart(scenarios)
            + '<h3 class="subheading">Stress scenarios</h3><p class="section-note">Each duration is tested separately. These are conditional calculations under the supplied assumptions, not forecasts that the shocks will occur. Amounts are Australian dollars.</p>'
            + scenario_table + _details("Full financial calculations and monthly schedules", finance))


STYLE = """
:root{color-scheme:light;--ink:#17343e;--muted:#546a72;--line:#d9e3e6;--paper:#f1f5f5;--accent:#0c6473;--high:#9e442c;--high-bg:#fff0e9;--medium:#795514;--medium-bg:#fff7df}
*{box-sizing:border-box}body{font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--ink);background:var(--paper);margin:0}main{max-width:1220px;margin:0 auto;padding:42px 34px 64px}header{padding:30px 34px;background:#173c47;color:#fff;border-radius:16px;border-top:5px solid #49b7af}h1{font-size:36px;line-height:1.15;letter-spacing:-.025em;margin:10px 0 12px}h2{font-size:25px;line-height:1.25;margin:0 0 10px;letter-spacing:-.015em}h3{font-size:17px;line-height:1.4;margin:5px 0 10px}p{margin:8px 0}.eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:11px;font-weight:750;color:#b7e8df}.header-row{display:flex;gap:20px;align-items:flex-start;justify-content:space-between}.header-meta{font-size:13px;color:#d5e9ed;overflow-wrap:anywhere}.status{display:inline-block;background:#fff2db;color:#634819;border-radius:30px;padding:7px 14px;font-size:12px;font-weight:750;white-space:nowrap}.header-note{max-width:850px;color:#d5e9ed;font-size:13px;margin-top:18px}.intro{font-size:18px;max-width:950px;margin:0 0 16px}.section{margin-top:30px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.section-note,.support,.muted{color:var(--muted)}.section-note{font-size:13px;max-width:1000px;margin:0 0 18px}.support{font-size:12px;line-height:1.5}.block{display:block;margin-top:6px}.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0}.metric{padding:18px;border-radius:10px;background:#f3f7f8;border:1px solid #e1eaec;min-width:0}.metric-label{font-size:12px;font-weight:650;color:var(--muted)}.metric-value{font-size:28px;font-weight:750;line-height:1.2;margin-top:7px;letter-spacing:-.025em;overflow-wrap:anywhere}.metric p{font-size:12px;line-height:1.45;color:var(--muted);margin:9px 0 0}.metric.high{border-color:#e8bba9;background:#fff7f2}.coverage-track{display:flex;align-items:center;gap:20px;margin:18px 0}.coverage-track progress{width:100%;height:12px;accent-color:var(--accent);border:0;border-radius:12px;overflow:hidden;background:#e4edef}.coverage-track progress::-webkit-progress-bar{background:#e4edef}.coverage-track progress::-webkit-progress-value{background:var(--accent)}.coverage-track strong{font-size:13px;white-space:nowrap}.scope-line{font-size:13px;color:var(--muted)}.card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.evidence-card{padding:18px 19px;background:#fff;border:1px solid var(--line);border-left:4px solid #9ab5bc;border-radius:10px;min-width:0}.evidence-card.high{border-left-color:#c66c4d}.evidence-card.medium{border-left-color:#cfaa58}.evidence-card.opportunity{border-left-color:#2b8c80;background:#f7fcfa}.card-meta{font-size:11px;letter-spacing:.02em;color:var(--muted);overflow-wrap:anywhere}.card-summary{font-size:14px;line-height:1.55;margin:10px 0}.tag{display:inline-block;font-size:11px;font-weight:700;border-radius:5px;padding:3px 7px;margin:1px 0;background:#edf3f5;color:#435d66}.tag.high{background:var(--high-bg);color:var(--high)}.tag.medium{background:var(--medium-bg);color:var(--medium)}.tag.opportunity{background:#e3f3ed;color:#216454}.evidence{border-top:1px solid var(--line);margin-top:14px;padding-top:10px}.evidence summary,.group-details>summary{font-size:12px;font-weight:650;color:var(--accent);cursor:pointer}.evidence pre{margin:12px 0 0;max-height:560px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;background:#f3f7f8;padding:14px;border-radius:6px}.group-details{margin-top:18px;padding:15px 18px;border:1px solid var(--line);border-radius:9px;background:#fafcfc}.group-details[open]>summary{margin-bottom:16px}.group-details>summary{font-size:14px}.empty{padding:15px;background:#f5f8f9;border-radius:8px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:9px;margin-top:16px}table{width:100%;border-collapse:collapse;font-size:12px;background:#fff}th,td{text-align:left;padding:12px 13px;border-bottom:1px solid var(--line);vertical-align:top}thead th{font-size:11px;color:#48616b;background:#edf4f5;font-weight:750}tbody tr:last-child>*{border-bottom:0}tbody th{font-size:12px;min-width:120px}.scenario-table{min-width:910px}.scenario-table td:first-child{min-width:230px;max-width:300px}.scenario-table td:nth-child(n+2){font-variant-numeric:tabular-nums}.check-table{min-width:790px}.check-table th:nth-child(2){width:31%}.check-id{font-weight:750;color:var(--accent);white-space:nowrap}.state{font-size:10px;font-weight:700;white-space:nowrap;padding:3px 6px;display:inline-block;border-radius:4px;background:#eef3f4;color:#475f68}.state.assessed{background:#e4f2ed;color:#216454}.state.unassessed{background:#fff1e6;color:#8c4e24}.subheading{font-size:18px;margin:26px 0 10px}.chart-frame{border:1px solid var(--line);border-radius:10px;padding:14px 12px;background:#fbfdfd;overflow:hidden}.chart-frame svg{display:block;width:100%;height:auto;min-width:0}.chart-grid{stroke:#dce7ea;stroke-width:1}.axis-label{font-size:11px;fill:#5c7179}.reserve-line{stroke:#a13f3f;stroke-width:1.6;stroke-dasharray:6 5}.reserve-label{font-size:11px;font-weight:700;fill:#984747;paint-order:stroke;stroke:#fbfdfd;stroke-width:4px;stroke-linejoin:round}.ending-label{font-size:12px;font-weight:750;paint-order:stroke;stroke:#fbfdfd;stroke-width:4px;stroke-linejoin:round}.chart-legend{display:flex;flex-wrap:wrap;gap:10px 24px;font-size:12px;margin:8px 14px 12px}.chart-legend span{display:flex;align-items:center;gap:7px}.chart-legend i{width:18px;height:4px;display:inline-block;border-radius:2px}.chart-frame .support{margin:0 14px 6px}.limitations{padding-left:19px;font-size:13px;color:var(--muted)}.limitations li{margin:9px 0}.count{font-size:12px;color:var(--muted);white-space:nowrap}footer{margin-top:26px;color:var(--muted);font-size:11px;overflow-wrap:anywhere}footer p{margin:5px 0}.provenance-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 24px}
@media(max-width:900px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.card-grid{grid-template-columns:1fr}main{padding:22px 18px 40px}.section{padding:21px}header{padding:26px}.metric-value{font-size:26px}}
@media(max-width:560px){main{padding:12px 10px 30px}.header-row{display:block}.status{margin-top:12px}header{padding:22px}.section{padding:18px}.metric-grid{gap:9px}.metric{padding:13px}.metric-value{font-size:22px}.metric-label{font-size:11px}h1{font-size:29px}h2{font-size:23px}.intro{font-size:16px}.section-heading{align-items:flex-start}.provenance-grid{grid-template-columns:1fr}.chart-frame{padding:7px 3px}.chart-legend{font-size:11px;gap:8px}.coverage-track{gap:10px}.evidence-card{padding:15px}}
@media print{body{background:#fff}main{max-width:none;padding:0}header{print-color-adjust:exact;-webkit-print-color-adjust:exact}.section{padding:18px;margin-top:20px}.metric-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.metric-value{font-size:21px}.card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-card,.metric,.chart-frame,tr{break-inside:avoid}h2,h3{break-after:avoid}.table-wrap{overflow:visible}.scenario-table,.check-table{min-width:0}th,td{padding:8px}footer{font-size:10px}}
"""


def _weekend_report(result):
    """Standalone, escaped print view of the exact saved worksheet."""
    weekend = result["weekend"]
    model, capture, ceiling = weekend["result"], weekend["capture"], weekend["ceiling"]
    example = capture["example"]
    def cash(value):
        number = _number(value)
        return "Unknown" if number is None else f"AUD {number:,.2f}"
    title = example["property"]["label"]
    names = {"V1": "Insurance, approvals and structure", "V2": "Two months of cash after settlement",
             "V3": "One month of cash after urgent works", "V4": "Income covers lean spending",
             "A": "Higher rates, insurance and works", "B": "The largest income stops", "C": "A forced sale in two years"}
    actions = {"V1": "Confirm insurance, building approvals and structural condition in writing.",
               "V2": "Lower the bid or retain a larger cash buffer.", "V3": "Quote urgent works and retain a month of lean costs.",
               "V4": "Reconcile monthly income and essential expenses.", "A": "Quote the works and test a lower offer.",
               "B": "Confirm job-loss entitlements, income-protection waiting periods and policy benefits.",
               "C": "Recheck selling costs, the stressed price and the cash needed before sale."}
    protection = model["storms"]["B"]
    gaps = [(label, protection.get(key)) for key, label in
            (("tpd_cover_gap", "Disability cover shortfall"), ("death_cover_gap", "Death cover shortfall"),
             ("illness_wait_gap", "Illness waiting-period cash shortfall"))
            if (_number(protection.get(key)) or 0) > 0]
    if gaps:
        names["B"] += ": " + "; ".join(f"{label} {cash(value)}" for label, value in gaps)
        actions["B"] = "Confirm the specific shortfall with the insurer and test a lower offer or sufficient cover."
    rows = []
    next_actions = [weekend["price_issue"]] if weekend.get("price_issue") else []
    for code, row in {**model["vetoes"], **model["storms"]}.items():
        values = {key: value for key, value in row.items() if key not in {"status", "monthly_cash", "missing_inputs"}}
        rows.append(f'<article class="evidence-card"><h3>{code} ? {names[code]}</h3><p><strong>{_e(_words(row["status"]))}</strong></p>')
        if code in model["assumptions"]:
            rows.append(f'<p>{_e(model["assumptions"][code])}</p>')
        if code.startswith("V") and code != "V1":
            rows.append(f'<p>Available {cash(row["available"])} ? Required {cash(row["required"])}</p>')
        if row["status"] != "green":
            next_actions.append(actions[code])
            rows.append(f'<p>{_e(actions[code])}</p>')
        if row.get("missing_inputs"):
            rows.append(f'<p>Unknown inputs: {_e(", ".join(key.replace("_", " ") for key in row["missing_inputs"]))}</p>')
        rows.append(_brief_values(values))
        if row.get("monthly_cash"):
            balances = [f'Month {month}: {cash(value)}' for month, value in enumerate(row["monthly_cash"])]
            rows.append(_details("Monthly cash balances", balances))
        rows.append('</article>')
    baseline = model["baseline"]
    metrics = _metric("Offer tested", cash(weekend["profile"].get("purchase_price")), "Illustrative offer")
    metrics += _metric("Cash after settlement", cash(baseline["cash_after_settlement"]), "After deposit and acquisition costs")
    metrics += _metric("Normal monthly surplus", cash(baseline["normal_surplus"]), "After household costs and mortgage")
    proof = {"model": model["rule_version"], "worksheet": weekend["version"], "input_hash": weekend["input_hash"],
             "bid_policy_version": weekend.get("bid_policy_version"), "bid_policy_hash": weekend.get("bid_policy_hash"),
             "assessment_id": result["assessment_id"], "case_version": result.get("case_version", "Unknown")}
    bid_heading = {"qualified": "Highest tested offer avoiding red (includes Amber)", "range_ceiling": "Tested range endpoint (includes Amber)",
                   "unknown": "Offer ceiling unknown", "no_qualifying_bid": "No qualifying offer in this range"}[ceiling["status"]]
    if ceiling.get("highest_passing_price") is not None:
        bid_heading += " ? " + cash(ceiling["highest_passing_price"])
    return f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(title)} | Weekend buyer worksheet</title><style>{STYLE}</style></head><body><main>
<header><p>First-home buyer ? Fictional weekend worksheet</p><h1>{_e(title)}</h1><p>{_e(example["name"])} ? {_e(example["as_of"])} ? Saved version {_e(result.get("case_version", "Unknown"))}</p></header>
<section class="section"><h2>{_e(_words(model["verdict"]))} household result</h2><p>{_e(example["description"])}</p><div class="metric-grid">{metrics}</div></section>
<section class="section"><h2>{_e(bid_heading)}</h2><p>Green and Amber both qualify. Amber retains a weak spot; this is not a safe-offer recommendation. Higher offers outside the tested grid are untested.</p><p>{_e(ceiling["binding_reason"])}</p><p>Next failing offer: {cash(ceiling["next_failing_price"]) if ceiling["next_failing_price"] is not None else "None established"}. Binding figures refer to the identified grid offer, not necessarily the offer tested above.</p>{_brief_values(ceiling.get("grid"))}</section>
<section class="section"><h2>What to confirm before offering</h2>{_brief_values(next_actions or ["Confirm the modelled figures and property evidence in writing."])}</section>
<section class="section"><h2>Veto checks and three household storms</h2>{''.join(rows)}</section>
<section class="section"><h2>Inputs and bid policy</h2><p>All example figures and property conditions are fictional. Edits are assumptions unless a source reference is supplied. Unknown inputs are unassessed.</p><p>Total first-year works, including urgent works: {cash(weekend["profile"].get("first_year_works"))}. Urgent works subset: {cash(weekend["profile"].get("urgent_works"))}. Include urgent works in the total once; blank means unknown, never zero.</p>{_brief_values(weekend["profile"])}<h3>Price adjustments</h3>{_brief_values(example["bid_policy"])}{_brief_values(ceiling["assumptions"])}<h3>Edited inputs and source references</h3>{_brief_values(capture["changes"])}{_brief_values(capture["source_notes"])}</section>
<footer>{_brief_values(proof)}{_details("Full saved assessment", result)}</footer></main></body></html>"""


def render_assessment(result: dict) -> str:
    """Format a stored result; authorisation remains the caller's responsibility."""
    if "weekend" in result:
        return _weekend_report(result)
    checks = _checks(result)
    labels = {check.get("check_id"): check.get("label", check.get("name", check.get("check_id"))) for check in checks}
    findings, gaps, opportunities = [result.get(key, []) if isinstance(result.get(key, []), list) else [] for key in ("findings", "gaps", "opportunities")]
    coverage = result.get("coverage", {}) if isinstance(result.get("coverage", {}), dict) else {}
    full = coverage.get("full_due_diligence", coverage)
    full = full if isinstance(full, dict) else coverage
    public = coverage.get("public_screen", {})
    public = public if isinstance(public, dict) else {}
    assessed, applicable = full.get("assessed"), full.get("required_applicable", full.get("required"))
    critical = full.get("critical_gaps")
    critical_count = len(critical) if isinstance(critical, list) else len({gap.get("check_id") for gap in gaps if isinstance(gap, dict) and gap.get("critical")})
    top_line = f"{assessed} of {applicable} applicable required checks are fully assessed." if assessed is not None and applicable is not None else "Evidence coverage has not been fully supplied."
    if full.get("not_assessed") is not None:
        top_line += f" {full['not_assessed']} remain unresolved, including {critical_count} critical checks."
    status = {"INCOMPLETE": "Evidence incomplete", "COMPLETE": "Required evidence complete"}.get(result.get("status"), _words(result.get("status")))
    metrics = [
        _metric("Evidence coverage", f"{assessed} / {applicable}" if assessed is not None and applicable is not None else "Not assessed", "Applicable required checks fully assessed"),
        _metric("Highest finding priority", _priority(result.get("priority")), "Supported findings only; separate from evidence gaps", _tone(result.get("priority"))),
        _metric("Critical checks unresolved", critical_count, "A missing check does not establish that the property is clear", "high" if critical_count else ""),
        _metric("Recorded opportunities", len(opportunities), "Benefits stay separate from adverse findings"),
    ]
    percentage = _number(full.get("percentage"))
    progress = f'<div class="coverage-track"><progress max="100" value="{float(percentage):.2f}" aria-label="Required evidence coverage"></progress><strong>{_e(full["percentage"])}% assessed</strong></div>' if percentage is not None and 0 <= percentage <= 100 else ''
    public_text = f'Public screening: {public.get("assessed")} / {public.get("required_applicable", public.get("required"))} applicable checks assessed.' if public.get("assessed") is not None else ''
    critical_gaps = [gap for gap in gaps if isinstance(gap, dict) and gap.get("critical") is True]
    other_gaps = [gap for gap in gaps if not isinstance(gap, dict) or gap.get("critical") is not True]
    gap_html = _cards(critical_gaps, "No critical evidence gaps are listed in this result.", "gap", labels)
    if other_gaps:
        gap_html += f'<details class="group-details"><summary>Other evidence gaps ({len(other_gaps)})</summary>' + _cards(other_gaps, "", "gap", labels) + '</details>'
    check_rows = []
    for check in checks:
        state = check.get("assessment_state", check.get("state", check.get("status")))
        state_class = "assessed" if state == "ASSESSED" else "unassessed" if state == "NOT_ASSESSED" else ""
        check_rows.append(f'<tr data-check-id="{_e(check.get("check_id"))}"><td class="check-id">{_e(check.get("check_id"))}</td>'
                          f'<td>{_e(check.get("label", check.get("name", "")))}</td><td><span class="state {state_class}">{_e(_words(state))}</span></td>'
                          f'<td>{_e(_priority(check.get("action_priority", check.get("priority"))))}</td><td>{_e(check.get("confidence"))}</td>'
                          f'<td>{_e(_words(check["reason"])) if check.get("reason") else "—"}</td></tr>')
    if not check_rows:
        check_rows = ['<tr><td colspan="6">No check results supplied.</td></tr>']
    limitations = result.get("limitations", [])
    limitation_html = '<ul class="limitations">' + ''.join(f'<li>{_e(value)}</li>' for value in limitations) + '</ul>' if isinstance(limitations, list) and limitations else '<p class="muted">No additional limitations supplied.</p>'
    provenance = {key: result.get(key) for key in ("assessment_id", "case_id", "property_id", "as_of", "engine_version", "rule_version", "runtime_versions", "input_hash", "manifest_hash", "replay_level", "input_snapshot_ids", "input_observation_ids", "excluded_observations", "review_state")}
    return f'''<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer">
<title>Property risk assessment — {_e(result.get('property_id'))}</title><style>{STYLE}</style></head><body><main>
<header><div class="eyebrow">Property evidence · Buyer decisions</div><div class="header-row"><div><h1>Property risk assessment</h1><p class="header-meta">{_e(result.get('property_id'))}</p><p class="header-meta">Assessment as of {_e(result.get('as_of'))}</p></div><span class="status">{_e(status)}</span></div>
<p class="header-note">Action priorities describe the review workflow. They are not probabilities of loss, a valuation or a recommendation to buy.</p></header>
{_household_decision(result)}
{_preoffer(result)}
{_purchase_decision(result)}
<section class="section" aria-labelledby="summary-heading"><h2 id="summary-heading">At a glance</h2><p class="intro">{_e(top_line)}</p><div class="metric-grid">{''.join(metrics)}</div>{progress}<p class="scope-line">{_e(public_text)} Full due diligence also requires the applicable private, legal, inspection, insurance and buyer funding checks.</p><p class="scope-line"><strong>Go to:</strong> <a href="#findings-heading">Findings</a> · <a href="#finance-heading">Cash stress</a> · <a href="#gaps-heading">Evidence gaps</a> · <a href="#opportunities-heading">Opportunities</a> · <a href="#checks-heading">All checks</a></p>{_details('Coverage definitions and counts', coverage)}</section>
<section class="section" aria-labelledby="findings-heading"><div class="section-heading"><h2 id="findings-heading">Supported findings</h2><span class="count">{len(findings)} records</span></div><p class="section-note">Priority and confidence describe different things. A priority 0 finding means no flag within its assessed scope; it does not clear the whole property.</p>{_cards(findings, 'No supported findings in the assessed scope.', 'finding', labels)}</section>
<section class="section" aria-labelledby="finance-heading"><h2 id="finance-heading">Buyer finances and stress tests</h2><p class="section-note">Day-one settlement funding, monthly affordability and duration-bounded cash reserves are shown separately. Cash balances and calculated financial amounts come from the recorded engine output.</p>{_finance(result.get('financial_scenarios', result.get('finance', {})))}</section>
<section class="section" aria-labelledby="gaps-heading"><div class="section-heading"><h2 id="gaps-heading">Evidence still needed</h2><span class="count">{len(gaps)} gaps</span></div><p class="section-note">Gap priority is the priority of obtaining or resolving evidence. It is separate from the property's supported finding priority.</p>{gap_html}</section>
<section class="section" aria-labelledby="opportunities-heading"><div class="section-heading"><h2 id="opportunities-heading">Recorded opportunities</h2><span class="count">{len(opportunities)} records</span></div><p class="section-note">Timing and dependencies remain part of each benefit. Opportunities do not cancel adverse findings.</p>{_cards(opportunities, 'No supported opportunities identified.', 'opportunity', labels)}</section>
<section class="section" aria-labelledby="checks-heading"><div class="section-heading"><h2 id="checks-heading">Complete check register</h2><span class="count">{len(checks)} checks retained</span></div><p class="section-note">Every configured check appears below, including checks that could not be assessed. Unavailable priorities remain “Not assessed”.</p><div class="table-wrap"><table class="check-table"><thead><tr><th>Check</th><th>Description</th><th>State</th><th>Finding priority</th><th>Confidence</th><th>Reason</th></tr></thead><tbody>{''.join(check_rows)}</tbody></table></div>{_details('Complete check calculations and evidence references', checks)}</section>
<section class="section" aria-labelledby="limitations-heading"><h2 id="limitations-heading">Limits and interpretation</h2>{limitation_html}{_details('Domain summaries', result.get('domains', []))}</section>
<footer><div class="provenance-grid"><p><strong>Assessment</strong><br>{_e(result.get('assessment_id'))}</p><p><strong>Calculation versions</strong><br>Engine {_e(result.get('engine_version'))} · Rules {_e(result.get('rule_version'))}</p></div><p><strong>Input hash:</strong> {_e(result.get('input_hash'))}</p>{_details('Pinned provenance and replay information', provenance)}{_details('Full structured assessment JSON', result)}</footer>
</main></body></html>'''
