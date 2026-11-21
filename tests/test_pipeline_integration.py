"""Cross-module gates: capture -> evidence -> immutable decision -> API/replay."""
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from shapely.geometry import box, mapping

from riskengine import cli, pipeline, storage
from riskengine.api import create_app
from riskengine.engine import canonical_hash, evaluate_case
from riskengine.storage import Conflict, Store


def reviewed_case():
    return {"case_id": "integration-case", "property_id": "integration-property", "as_of": "2026-11-21T00:00:00Z",
            "property": {"property_type": "house", "jurisdiction": "ACT", "identity_confirmed": True,
                         "parcel_geometry": mapping(box(690000, 6080000, 690020, 6080020)), "crs": "EPSG:7855"},
            "source_assertions": {"act_flood_extent": {"reviewed": True, "reviewer": "synthetic-reviewer",
                "reviewed_at": "2026-11-20T00:00:00Z", "coverage_basis": "Synthetic complete study coverage for this fixture",
                "coverage_status": "COVERED", "published_at": "2026-01-01T00:00:00Z", "current": True,
                "identity_match": True, "positional_uncertainty_m": 1.0}}}


def source():
    return {"source_id": "act_flood_extent", "adapter": "arcgis", "endpoint": "https://example.test/FeatureServer/0",
            "rights": {"process": True, "display_raw": False, "display_derived": True, "retain_raw": True}}


def capture_result():
    return {"source_id": "act_flood_extent", "snapshot_id": "sha256:synthetic-capture-one", "adapter_version": "test-1",
            "status": "SUCCESS", "retrieved_at": "2026-11-20T01:00:00Z", "source_published_at": "2026-01-01T00:00:00Z",
            "raw_files": [{"sha256": "abc", "bytes": 25, "relative_path": "raw/ab/abc.json", "path": "/private/secret/path", "kind": "features"}],
            "records": [{"geometry_status": "PRESENT", "geometry": mapping(box(690010, 6080010, 690030, 6080030)),
                         "crs": {"wkid": 7855}, "attributes": {"restricted_field": "raw licensed value"}}],
            "completeness": {"status": "COMPLETE", "expected_count": 1, "returned_count": 1, "query_scope": {"where": "1=1", "bbox": [689900, 6079900, 690100, 6080100], "in_sr": 7855}},
            "coverage": {"status": "NOT_ESTABLISHED", "reason": "Download does not establish coverage"}, "schema": {"fields": []}, "errors": [], "bytes_received": 25}


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "riskengine.sqlite3")
    result.save_case("tenant-a", reviewed_case())
    return result


def stub_capture(monkeypatch, result=None, selected=None):
    captured = result or capture_result()
    contract = selected or source()
    monkeypatch.setattr(pipeline, "selected_source", lambda *_args, **_kwargs: deepcopy(contract))
    monkeypatch.setattr(pipeline, "collect", lambda *_args, **_kwargs: deepcopy(captured))
    return captured


def collect(store, tmp_path):
    return pipeline.collect_case(store=store, tenant_id="tenant-a", case_id="integration-case",
                                 source_id="act_flood_extent", output_dir=tmp_path / "snapshots")


def test_capture_is_idempotent_and_public_result_does_not_expose_raw_payloads(store, tmp_path, monkeypatch):
    captured = stub_capture(monkeypatch)
    first = collect(store, tmp_path)
    first_observations = store.list_observations("tenant-a", "integration-case")
    assert len(first_observations) == 2
    captured["retrieved_at"] = "2026-11-20T02:00:00Z"
    second = collect(store, tmp_path)
    assert first["snapshot_id"] == second["snapshot_id"] and first["observation_ids"] == second["observation_ids"]
    assert store.list_observations("tenant-a", "integration-case") == first_observations
    assert len(store.list_snapshots("tenant-a", "integration-case")) == 1
    for visible in (first, second, store.get_source_health("tenant-a")):
        text = json.dumps(visible)
        assert "raw licensed value" not in text and "/private/secret/path" not in text and '"raw_files"' not in text
    redacted = store.list_observations("tenant-a", "integration-case", redact=True)
    assert all("payload" not in row and row["raw_redacted"] for row in redacted)


def test_successful_download_without_review_does_not_create_clear_findings(store, tmp_path, monkeypatch):
    stub_capture(monkeypatch)
    case = store.get_case("tenant-a", "integration-case")
    case["source_assertions"] = {}
    store.save_case("tenant-a", case)
    result = collect(store, tmp_path)
    assert result["status"] == "SUCCESS" and result["promotion_gaps"] == ["PROPERTY_COVERAGE_REVIEW_REQUIRED"]
    assert result["observation_ids"] == []
    assessment = pipeline.assess_case(store, "tenant-a", "integration-case")
    flood = next(check for check in assessment["check_results"] if check["check_id"] == "S005")
    assert flood["state"] == "NOT_ASSESSED" and flood["priority"] is None


@pytest.mark.parametrize("change,expected_gap", [
    ({"reviewed": False}, "PROPERTY_COVERAGE_REVIEW_REQUIRED"),
    ({"coverage_status": "OUTSIDE_COVERAGE"}, "PROPERTY_COVERAGE_REVIEW_REQUIRED"),
    ({"current": False}, "CURRENCY_OR_IDENTITY_UNCONFIRMED"),
    ({"identity_match": False}, "CURRENCY_OR_IDENTITY_UNCONFIRMED"),
    ({"positional_uncertainty_m": None}, "POSITIONAL_UNCERTAINTY_UNRESOLVED"),
    ({"positional_uncertainty_m": -1}, "INVALID_POSITIONAL_UNCERTAINTY"),
    ({"reviewed_at": "invalid"}, "REVIEW_DATE_UNRESOLVED"),
    ({"reviewed_at": "2027-01-01T00:00:00Z"}, "REVIEW_NOT_KNOWN_AS_OF"),
])
def test_review_prerequisites_are_fail_closed(change, expected_gap):
    case = reviewed_case()
    case["owner_tenant_id"] = "tenant-a"
    case["source_assertions"]["act_flood_extent"].update(change)
    observations, gaps = pipeline._promote_spatial(case, source(), capture_result())
    assert not observations and expected_gap in gaps


def test_malformed_assertions_crs_and_partial_queries_fail_without_crashing():
    case = reviewed_case()
    case["owner_tenant_id"] = "tenant-a"
    assert pipeline._promote_spatial({**case, "source_assertions": "invalid"}, source(), capture_result())[1] == ["PROPERTY_COVERAGE_REVIEW_REQUIRED"]
    broken = deepcopy(case)
    broken["property"]["crs"] = "unrecognised CRS"
    assert pipeline._promote_spatial(broken, source(), capture_result())[1] == ["GEOMETRY_OR_CRS_UNRESOLVED"]
    captured = capture_result()
    captured["completeness"]["query_scope"]["where"] = "HAZARD_TYPE='FLUVIAL'"
    assert pipeline._promote_spatial(case, source(), captured)[1] == ["FILTERED_MECHANISM_SCOPE_REQUIRES_REVIEW"]
    captured = capture_result()
    captured["completeness"]["query_scope"]["bbox"] = [690000, 6080000, 690020, 6080020]
    assert pipeline._promote_spatial(case, source(), captured)[1] == ["QUERY_SCOPE_DOES_NOT_COVER_SUBJECT"]
    captured = capture_result()
    captured["completeness"]["status"] = "PARTIAL"
    assert pipeline._promote_spatial(case, source(), captured)[1] == ["COLLECTION_INCOMPLETE"]


def test_analysis_rights_required_before_promotion(store, tmp_path, monkeypatch):
    contract = source()
    contract["rights"]["display_derived"] = False
    stub_capture(monkeypatch, selected=contract)
    result = collect(store, tmp_path)
    assert result["promotion_gaps"] == ["ANALYSIS_RIGHTS_UNCONFIRMED"] and not result["observation_ids"]
    assert result["record_count"] is None and result["completeness"]["status"] == "WITHHELD"
    assert store.list_observations("tenant-a", "integration-case") == []


def test_current_source_policy_applies_before_collection_and_to_old_health(store, tmp_path, monkeypatch):
    captured = stub_capture(monkeypatch)
    collect(store, tmp_path)
    assert store.get_source_health("tenant-a")[0]["health"]["record_count"] == 1
    store.set_source_policy("tenant-a", "act_flood_extent", {"display_derived": False, "retain_raw": False})
    assert store.get_source_health("tenant-a")[0]["health"]["status"] == "DISPLAY_RESTRICTED"
    captured["snapshot_id"] = "sha256:policy-restricted-capture"
    def checked_collection(source_contract, *_args, **_kwargs):
        assert source_contract["rights"]["retain_raw"] is False and source_contract["rights"]["display_derived"] is False
        return deepcopy(captured)
    monkeypatch.setattr(pipeline, "collect", checked_collection)
    outcome = collect(store, tmp_path)
    assert outcome["record_count"] is None and not outcome["observation_ids"]


def test_real_engine_replay_uses_pinned_case_and_evidence(store, tmp_path, monkeypatch):
    stub_capture(monkeypatch)
    collect(store, tmp_path)
    original = pipeline.assess_case(store, "tenant-a", "integration-case")
    original_case = store.get_case("tenant-a", "integration-case")
    store.save_case("tenant-a", {**original_case, "as_of": "2027-01-01T00:00:00Z"})
    pinned_case, observations, saved = store.replay_inputs("tenant-a", original["assessment_id"])
    assert pinned_case["case_version"] == 1
    def unavailable(*args):
        pytest.fail("Replay attempted to consult current location providers")
    monkeypatch.setattr(pipeline, "buyer_context", unavailable)
    stored, replayed = pipeline.replay_assessment(store, "tenant-a", original["assessment_id"])
    assert canonical_hash(replayed) == canonical_hash(stored) == canonical_hash(saved) == canonical_hash(original)
    assert replayed["purchase_decision"]["assessment_id"] == original["assessment_id"]
    flood = next(row for row in original["check_results"] if row["check_id"] == "S005")
    assert flood["state"] == "ASSESSED" and flood["priority"] > 0


def test_purchase_evidence_pinned_on_capture_and_in_assessment_identity(store, monkeypatch):
    first = pipeline.assess_case(store, "tenant-a", "integration-case")
    assert pipeline.assess_case(store, "tenant-a", "integration-case") == first
    updated = deepcopy(first["decision_evidence"])
    updated["planning"][0]["detail"] = "The offline extract has been updated."
    monkeypatch.setattr(pipeline, "buyer_context", lambda *_, **__: updated)
    second = pipeline.assess_case(store, "tenant-a", "integration-case")
    assert second["assessment_id"] != first["assessment_id"]
    assert second["input_hash"] != first["input_hash"]
    assert store.get_assessment("tenant-a", first["assessment_id"]) == first
    assert pipeline.replay_assessment(store, "tenant-a", first["assessment_id"]) == (first, first)


def test_legacy_assessment_replays_without_decision_capture(store, monkeypatch):
    case, obs = store.assessment_inputs("tenant-a", "integration-case")
    original = evaluate_case(case, obs)
    store.save_assessment("tenant-a", case["case_id"], original, obs, case["case_version"])
    def unavailable(*args):
        pytest.fail("Legacy replay consulted a new decision input")
    monkeypatch.setattr(pipeline, "buyer_context", unavailable)
    assert pipeline.replay_assessment(store, "tenant-a", original["assessment_id"]) == (original, original)


def test_purchase_replay_uses_pinned_rule_version_including_hashes(store):
    from riskengine.engine import apply_purchase_rules
    case, obs = store.assessment_inputs("tenant-a", "integration-case")
    checks = evaluate_case(case, obs)
    current = pipeline.assess_case(store, "tenant-a", case["case_id"])
    previous = apply_purchase_rules(case, checks, current["decision_evidence"], rule_version="1.0.0")
    store.save_assessment("tenant-a", case["case_id"], previous, obs, case["case_version"])
    assert current["purchase_rule_version"] == current["purchase_decision"]["rule_version"] == "1.0.1"
    assert previous["purchase_rule_version"] == previous["purchase_decision"]["rule_version"] == "1.0.0"
    assert current["input_hash"] != previous["input_hash"] and current["assessment_id"] != previous["assessment_id"]
    for result in (previous, current):
        assert pipeline.replay_assessment(store, "tenant-a", result["assessment_id"]) == (result, result)


def test_report_labels_unresolved_legal_statement_without_changing_observation_text():
    from riskengine.reporting import render_assessment
    finding = {"rule_id": "LG01", "priority": 3, "summary": "The reviewed map depicts a proposed easement.",
               "details": {"reviewed": True, "evidence_kind": "restriction"}}
    tag = "Source statement · legal effect awaits title verification"
    report = render_assessment({"findings": [finding]})
    assert tag in report and finding["summary"] in report
    assert tag not in render_assessment({"findings": [{**finding, "priority": 4}]})


def test_local_evidence_permissions_apply_to_saved_and_new_decisions(store):
    from riskengine.buyer_location import example_case
    case = example_case()
    store.save_case("tenant-a", case)
    result = pipeline.assess_case(store, "tenant-a", case["case_id"])
    assert result["decision_evidence"]["spatial"][0]["status"] == "mapped"
    store.set_source_policy("tenant-a", "act_tp_zoning", {"display_derived": False})
    with pytest.raises(storage.Forbidden):
        store.get_assessment("tenant-a", result["assessment_id"])
    assert not store.list_assessments("tenant-a", case["case_id"])[0]["display_allowed"]
    with pytest.raises(storage.Forbidden):
        pipeline.replay_assessment(store, "tenant-a", result["assessment_id"])
    revised = pipeline.assess_case(store, "tenant-a", case["case_id"])
    assert revised["decision_evidence"]["spatial"][0]["status"] == "unknown"
    assert "act_tp_zoning" not in revised["decision_evidence"]["source_ids"]


def test_missing_provider_is_an_evidence_gap_not_a_failed_assessment(store, monkeypatch):
    from riskengine import buyer_context
    from riskengine.buyer_location import example_case
    case = example_case()
    store.save_case("tenant-a", case)
    def missing_file(*args):
        raise FileNotFoundError("unavailable local source")
    monkeypatch.setattr(buyer_context, "planning_signals", missing_file)
    result = pipeline.assess_case(store, "tenant-a", case["case_id"])
    assert result["decision_evidence"]["planning"][0]["status"] == "unknown"
    assert result["decision_evidence"]["crime"][0]["status"] == "available"


def test_future_address_and_boundary_captures_cannot_supply_historical_property_evidence(store):
    from riskengine.buyer_location import example_case
    case = example_case()
    for key in ("latitude", "longitude"):
        del case["property"][key]
    for cutoff in ("2024-01-01T00:00:00Z", "2026-11-21T07:51:00Z"):
        case["as_of"] = cutoff
        store.save_case("tenant-a", case)
        result = pipeline.assess_case(store, "tenant-a", case["case_id"])
        evidence = result["decision_evidence"]
        assert evidence["location"]["latitude"] is None
        assert all(evidence[group][0]["status"] == "unknown" for group in ("planning", "spatial", "crime"))


@pytest.mark.parametrize("change", [{"purchase_rule_version": "uninstalled"}, {"decision_evidence": None}])
def test_replay_fails_when_recorded_rules_or_evidence_are_unavailable(store, monkeypatch, change):
    result = pipeline.assess_case(store, "tenant-a", "integration-case")
    case, observations, saved = store.replay_inputs("tenant-a", result["assessment_id"])
    monkeypatch.setattr(store, "replay_inputs", lambda *_: (case, observations, {**saved, **change}))
    with pytest.raises(Conflict, match="unavailable for replay"):
        pipeline.replay_assessment(store, "tenant-a", result["assessment_id"])


def test_report_contains_recorded_decision_and_renders_reference_text_safely(store):
    from riskengine.reporting import render_assessment
    result = pipeline.assess_case(store, "tenant-a", "integration-case")
    decision = result["purchase_decision"]
    decision["open_checks"][0]["references"].extend(["javascript:alert(1)", "<script>", "https://example.test/evidence"])
    report = render_assessment(result)
    assert report.index("Purchase decision</h2>") < report.index("At a glance</h2>")
    assert decision["headline"] in report and decision["next_action"] in report
    assert 'href="https://example.test/evidence"' in report
    assert 'href="javascript:' not in report and "<script>" not in report


def test_worker_errors_retry_with_safe_metadata_and_stop_at_limit(store, tmp_path, monkeypatch):
    now = ["2026-11-21T00:00:00Z"]
    actual_time = storage._time
    monkeypatch.setattr(storage, "_time", lambda value=None: actual_time(value if value is not None else now[0]))
    def failure(**_kwargs):
        raise RuntimeError("secret credential and private filesystem path must not be stored")
    monkeypatch.setattr(pipeline, "collect_case", failure)
    store.enqueue_job("tenant-a", "integration-case", "collect", {"source_id": "act_flood_extent"}, "retry", max_attempts=2)
    first = pipeline.work_once(store, tmp_path, "tenant-a")
    assert first["status"] == "PENDING" and first["last_error"] == "RuntimeError" and first["attempts"] == 1
    assert pipeline.work_once(store, tmp_path, "tenant-a") is None
    now[0] = "2026-11-21T00:00:06Z"
    second = pipeline.work_once(store, tmp_path, "tenant-a")
    assert second["status"] == "FAILED" and second["attempts"] == 2
    assert "secret credential" not in json.dumps(second)


def test_worker_lost_lease_does_not_mutate_new_workers_result(store, tmp_path, monkeypatch):
    now = ["2026-11-21T00:00:00Z"]
    actual_time = storage._time
    monkeypatch.setattr(storage, "_time", lambda value=None: actual_time(value if value is not None else now[0]))
    initial = store.enqueue_job("tenant-a", "integration-case", "collect", {"source_id": "act_flood_extent"}, "slow")
    def slow_capture(**_kwargs):
        now[0] = "2026-11-21T01:00:01Z"
        newer = store.claim_job("replacement", tenant_id="tenant-a")
        assert newer["attempts"] == 2
        store.complete_job("tenant-a", newer["job_id"], newer["lease_token"], {"status": "SUCCESS", "winning_worker": "replacement"})
        return {"status": "SUCCESS", "stale_worker": True}
    monkeypatch.setattr(pipeline, "collect_case", slow_capture)
    outcome = pipeline.work_once(store, tmp_path, "tenant-a")
    assert outcome["worker_outcome"] == "LEASE_LOST_AFTER_ERROR"
    assert outcome["status"] == "SUCCEEDED" and outcome["result"] == {"status": "SUCCESS", "winning_worker": "replacement"}
    assert "lease_token" not in outcome


def test_collection_immutability_error_is_retryable_not_an_immortal_lease(store, tmp_path, monkeypatch):
    def conflicting_capture(**_kwargs):
        raise Conflict("Snapshot metadata changed under an immutable identifier")
    monkeypatch.setattr(pipeline, "collect_case", conflicting_capture)
    store.enqueue_job("tenant-a", "integration-case", "collect", {"source_id": "act_flood_extent"}, "conflict")
    outcome = pipeline.work_once(store, tmp_path, "tenant-a")
    assert outcome["status"] == "PENDING" and outcome["last_error"] == "Conflict"


def test_cli_demo_is_idempotent_api_visible_and_replayable(tmp_path, capsys):
    args = ["--data-dir", str(tmp_path), "--tenant", "demo"]
    assert cli.main(args + ["demo"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main(args + ["demo"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["assessment_id"] == second["assessment_id"]
    with TestClient(create_app(tmp_path)) as api:
        token = next(iter(json.loads((tmp_path / "api_keys.json").read_text())))
        headers = {"Authorization": f"Bearer {token}"}
        visible = api.get(f"/v1/cases/{first['case_id']}", headers=headers)
        assert visible.status_code == 200 and visible.json()["case_version"] == 1
        assert len(api.get(f"/v1/cases/{first['case_id']}/assessments", headers=headers).json()["assessments"]) == 1
        assert api.get(f"/v1/assessments/{first['assessment_id']}/report", headers=headers).status_code == 200
    assert cli.main(args + ["replay", first["assessment_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["exact_match"] is True


def test_cli_assess_writes_html_and_review_actions_match_store(tmp_path, capsys):
    args = ["--data-dir", str(tmp_path), "--tenant", "demo"]
    assert cli.main(args + ["demo"]) == 0
    demo = json.loads(capsys.readouterr().out)
    target = tmp_path / "report-output" / "assessment.json"
    assert cli.main(args + ["assess", demo["case_id"], "--output", str(target)]) == 0
    capsys.readouterr()
    assert target.is_file() and target.with_suffix(".html").is_file()
    assert cli.main(args + ["review", demo["assessment_id"], "investigate", "Specialist review required"]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["action"] == "investigate" and review["assessment_unchanged"]
