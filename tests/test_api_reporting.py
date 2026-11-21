"""Presentation gates: exact recorded values, complete scope and inert content."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path

from riskengine.engine import evaluate_case
from riskengine.reporting import render_assessment


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.attributes, self.points, self.checks, self.pre_blocks = [], [], [], [], []
        self.in_pre = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags.append(tag)
        self.attributes.extend(attrs)
        if tag == "circle":
            self.points.append(values)
        if tag == "tr" and "data-check-id" in values:
            self.checks.append(values["data-check-id"])
        if tag == "pre":
            self.in_pre = True
            self.pre_blocks.append("")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False

    def handle_data(self, data):
        if self.in_pre:
            self.pre_blocks[-1] += data


def demo_result():
    examples = Path(__file__).resolve().parents[1] / "examples"
    return evaluate_case(json.loads((examples / "case.json").read_text()), json.loads((examples / "observations.json").read_text()))


def test_report_preserves_engine_amounts_breach_duration_and_complete_manifest():
    result = demo_result()
    before = deepcopy(result)
    report = render_assessment(result)
    parsed = ReportParser()
    parsed.feed(report)
    assert result == before
    assert "A$4,316.76" in report and "A$983.24" in report
    assert "A$25,301.37" in report and "A$5,602.74" in report and "A$15,000.00" in report
    assert "Month 10" in report and "No breach within this period" in report
    for scenario in result["financial_scenarios"]["scenarios"]:
        actual = [(int(point["data-month"]), point["data-cash"]) for point in parsed.points if point["data-scenario"] == scenario["scenario_id"]]
        expected = [(0, scenario["initial_cash"])] + [(row["month"], row["closing_cash"]) for row in scenario["monthly_schedule"]]
        assert actual == expected
        assert actual[-1][0] == scenario["duration_months"]
    assert len(parsed.checks) == 65
    assert parsed.checks == [check["check_id"] for check in result["check_results"]]
    assert json.loads(parsed.pre_blocks[-1]) == result
    assert all(tag != "script" for tag in parsed.tags)
    assert not any(name == "open" for name, _ in parsed.attributes)


def test_report_and_svg_escape_untrusted_titles_scenario_ids_and_text():
    result = demo_result()
    unsafe = '\"><script>alert("x")</script><img src=x onerror=alert(1)>'
    result["property_id"] = unsafe
    result["findings"][0]["title"] = unsafe
    result["findings"][0]["summary"] = unsafe
    result["opportunities"][0]["benefit"] = unsafe
    result["financial_scenarios"]["scenarios"][0]["scenario_id"] = unsafe
    report = render_assessment(result)
    parsed = ReportParser()
    parsed.feed(report)
    assert unsafe not in report and "&lt;script&gt;" in report
    assert "script" not in parsed.tags and "img" not in parsed.tags
    assert not any(name.lower().startswith("on") for name, _ in parsed.attributes)
    assert any(point["data-scenario"] == unsafe for point in parsed.points)
    assert json.loads(parsed.pre_blocks[-1]) == result


def test_report_does_not_turn_missing_finance_or_missing_months_into_zero():
    report = render_assessment({"property_id": "test", "status": "INCOMPLETE", "financial_scenarios": {}, "check_results": []})
    assert "A$0.00" not in report and "<svg" not in report
    assert "No stress scenarios were supplied" in report
    result = demo_result()
    scenarios = result["financial_scenarios"]["scenarios"]
    scenarios[0]["monthly_schedule"].pop(3)
    scenarios[1]["monthly_schedule"] = []
    report = render_assessment(result)
    assert "<polyline" not in report
    assert "A$5,602.74" in report  # The recorded scenario result is still shown.
