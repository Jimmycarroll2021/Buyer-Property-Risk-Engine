from riskengine.buyer_finance import finance_signals
from riskengine.finance import evaluate_finance


def signals(inputs, scenarios=()):
    case = {"as_of": "2026-11-01", "finance": inputs, "scenarios": list(scenarios)}
    assessment = {"as_of": case["as_of"], "financial_scenarios": evaluate_finance(inputs, list(scenarios))}
    rows = finance_signals(case, assessment)
    assert all(row["as_of"] == case["as_of"] and row["status"] for row in rows)
    return {row["title"]: row for row in rows}


def test_estimated_repayment_and_six_vs_twelve_month_reserve_breach():
    inputs = {"principal": "720000", "annual_rate_decimal": "0.06", "term_months": 360,
              "income_monthly": "11000", "living_monthly": "4800", "other_debt_monthly": 0,
              "property_costs_monthly": 900, "cash_after_settlement": 45000, "protected_reserve": 15000,
              "purchase_price": 900000, "acquisition_costs": 25000, "immediate_works": 10000,
              "loan_funds": 720000, "cash_allocated": 220000, "funding_confirmed": True}
    scenarios = [{"scenario_id": f"shock-{n}", "duration_months": n, "rate_delta_bps": 200,
                  "income_factor": "0.70"} for n in (6, 12)]
    rows = signals(inputs, scenarios)
    assert "A$4,316.76" in rows["Initial monthly loan repayment"]["detail"]
    assert "6% per year" in rows["Initial monthly loan repayment"]["detail"]
    assert "A$983.24 left over" in rows["Monthly household budget"]["detail"]
    assert "headroom of A$5,000.00" in rows["Settlement funding"]["detail"]
    assert "A$45,000.00" in rows["Cash reserve after settlement"]["detail"]
    six = rows["Stress test · shock-6"]
    assert "6 months" in six["detail"] and "70% of baseline" in six["detail"]
    assert "+2 percentage point" in six["detail"] and "A$25,301.37" in six["detail"]
    assert "stays at or above" in six["detail"]
    twelve = rows["Stress test · shock-12"]
    assert "12 months" in twelve["detail"] and "in month 10" in twelve["detail"]
    assert "A$5,602.74" in twelve["detail"] and twelve["status"] == "Below target"


def test_incomplete_inputs_keep_price_contribution_separate_from_settlement_shortfall():
    inputs = {"principal": 1040000, "annual_rate_decimal": "0.0639", "term_months": None,
              "purchase_price": 1300000, "loan_funds": 1040000}
    rows = signals(inputs, [{"scenario_id": "combined", "duration_months": 12,
                             "income_factor": "0.7", "rate_delta_bps": 200}])
    repayment = rows["Monthly repayment unknown"]
    assert "6.39% per year" in repayment["detail"] and "term in months" in repayment["detail"]
    funding = rows["Settlement funding incomplete"]
    assert "A$260,000.00 of the price to cover before" in funding["detail"]
    assert "purchase costs" in funding["detail"] and "shortfall" not in funding["detail"]
    assert "monthly household income" in rows["Monthly household budget unknown"]["detail"]
    assert "the cash reserve you want to keep" in rows["Cash reserve unknown"]["detail"]
    scenario = rows["Stress test pending · combined"]["detail"]
    assert "12-month" in scenario and "70% of baseline" in scenario and "loan term" in scenario


def test_unconfirmed_funding_distinguished_from_confirmed_funding_and_reserve_shortfall():
    inputs = {"purchase_price": 900000, "loan_funds": 720000, "acquisition_costs": 25000,
              "immediate_works": 10000, "cash_allocated": 200000, "cash_after_settlement": 10000,
              "protected_reserve": 15000}
    rows = signals(inputs)
    assert rows["Settlement funding"]["status"] == "Unconfirmed funding"
    assert "shortfall of A$15,000.00" in rows["Settlement funding"]["detail"]
    assert rows["Cash reserve after settlement"]["status"] == "Below target"
    assert "Another A$5,000.00" in rows["Cash reserve after settlement"]["detail"]
    inputs["funding_confirmed"] = True
    assert signals(inputs)["Settlement funding"]["status"] == "Funding shortfall"


def test_no_future_inputs_or_unassessed_balances_presented():
    inputs = {"purchase_price": 1300000, "loan_funds": 1040000, "principal": 1040000}
    finance = evaluate_finance(None)
    for key in ("repayment", "settlement", "buffer", "baseline"):
        finance[key]["reason"] = "NOT_KNOWN_AS_OF"
    rows = finance_signals({"finance": inputs}, {"as_of": "2020-01-01", "financial_scenarios": finance})
    assert len(rows) == 1 and rows[0]["title"] == "Buyer finances unavailable"
    assert "A$" not in rows[0]["detail"]
    rows = signals({})
    assert len(rows) == 1 and "A$" not in rows["Add your buyer finances"]["detail"]
