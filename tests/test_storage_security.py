"""Executable privacy, evidence immutability and worker recovery gates."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from riskengine.storage import Conflict, Forbidden, NotFound, Store, StoreError


def case(case_id="case-a", property_id="same-property"):
    return {"case_id": case_id, "property_id": property_id, "as_of": "2026-11-21T00:00:00Z",
            "property": {"property_type": "house"}, "finance": {"income_monthly": "12345"}}


def observation(obs_id="obs-a", public=False, **overrides):
    result = {"observation_id": obs_id, "check_id": "S005", "property_id": "same-property", "source_id": "flood-source",
              "snapshot_id": "snapshot-one", "published_at": "2026-01-01T00:00:00Z", "received_at": "2026-01-02T00:00:00Z",
              "visibility_scope": "public" if public else "private", "evidence_basis": "official_record",
              "rights": {"process": True, "display_raw": True, "display_derived": True, "retain_raw": True},
              "quality": {"complete": True, "coverage_status": "COVERED"}, "payload": {"secret_inspection": "private issue"}}
    result.update(overrides)
    return result


def assessment(aid="assessment-a", case_id="case-a"):
    return {"assessment_id": aid, "case_id": case_id, "property_id": "same-property", "as_of": "2026-11-21T00:00:00Z",
            "status": "REVIEW_REQUIRED", "findings": [{"finding_id": "f-1", "priority": 3}],
            "gaps": [{"check_id": "S006", "gap_priority": 3}], "coverage": {"assessed": 1, "required": 4}}


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "risk.sqlite3")
    result.save_case("tenant-a", case())
    result.save_case("tenant-a", case("case-a2"))
    result.save_case("tenant-b", case("case-b"))
    return result


def test_private_evidence_is_case_scoped_even_for_same_property(store):
    private = store.add_observation("tenant-a", "case-a", observation())
    assert private["owner_tenant_id"] == "tenant-a"
    assert private["case_scope_id"] == "case-a"
    assert store.list_observations("tenant-a", "case-a2") == []
    assert store.list_observations("tenant-b", "case-b") == []
    with pytest.raises(NotFound):
        store.list_observations("tenant-b", "case-a")
    with pytest.raises(Forbidden):
        store.add_observation("tenant-b", "case-b", observation(owner_tenant_id="tenant-a"))
    with pytest.raises(Forbidden):
        store.add_observation("tenant-a", "case-a2", observation("obs-2", case_scope_id="case-a"))


def test_only_trusted_ingestion_can_publish_reusable_observations(store):
    shared = observation("shared", public=True)
    with pytest.raises(Forbidden):
        store.add_observation("tenant-a", "case-a", shared)
    with pytest.raises(Forbidden):
        store.add_observation("tenant-a", "case-a", {**shared, "evidence_basis": "inspection"}, trusted_public=True)
    with pytest.raises(StoreError):
        store.add_observation("tenant-a", "case-a", {**shared, "owner_tenant_id": "tenant-a"}, trusted_public=True)
    store.add_observation("tenant-a", "case-a", shared, trusted_public=True)
    seen = store.list_observations("tenant-b", "case-b")
    assert len(seen) == 1 and seen[0]["owner_tenant_id"] is None and seen[0]["case_scope_id"] is None


def test_case_versions_and_observations_are_immutable_and_idempotent(store):
    first = store.get_case("tenant-a", "case-a")
    assert store.save_case("tenant-a", first)["case_version"] == 1
    second = store.save_case("tenant-a", {**first, "finance": {"income_monthly": "9000"}}, expected_version=1)
    assert second["case_version"] == 2
    assert store.get_case("tenant-a", "case-a", version=1)["finance"]["income_monthly"] == "12345"
    with pytest.raises(Conflict):
        store.save_case("tenant-a", case(), expected_version=1)
    with pytest.raises(Conflict):
        store.save_case("tenant-a", case(property_id="other-property"))
    obs = observation()
    obs.pop("received_at")
    initial = store.add_observation("tenant-a", "case-a", obs)
    assert store.add_observation("tenant-a", "case-a", obs) == initial
    with pytest.raises(Conflict):
        store.add_observation("tenant-a", "case-a", {**obs, "payload": {"changed": True}})


def test_assessment_pins_case_version_and_observations(store):
    store.add_observation("tenant-a", "case-a", observation())
    frozen_case, frozen_obs = store.assessment_inputs("tenant-a", "case-a")
    store.save_case("tenant-a", {**frozen_case, "finance": {"income_monthly": "99999"}})
    store.add_observation("tenant-a", "case-a", observation("obs-later"))
    result = assessment()
    store.save_assessment("tenant-a", "case-a", result, observations=frozen_obs, case_version=frozen_case["case_version"])
    assert store.get_assessment("tenant-a", result["assessment_id"]) == result
    assert store.list_assessments("tenant-a", "case-a")[0]["case_version"] == 1
    with store.connection() as conn:
        row = conn.execute("SELECT observation_refs FROM assessments WHERE assessment_id=?", (result["assessment_id"],)).fetchone()
        refs = json.loads(row[0])
        assert len(refs) == 1 and refs[0]["observation_id"] == "obs-a" and refs[0]["stored_content_hash"]
    with pytest.raises(Conflict):
        store.save_assessment("tenant-a", "case-a", {**result, "status": "CLEAR"})
    with pytest.raises(NotFound):
        store.get_assessment("tenant-b", result["assessment_id"])


def test_forged_assessment_input_scope_is_rejected(store):
    obs = store.add_observation("tenant-a", "case-a", observation())
    with pytest.raises(Forbidden):
        store.save_assessment("tenant-b", "case-b", assessment(case_id="case-b"), observations=[obs])
    with pytest.raises(Forbidden):
        store.save_assessment("tenant-a", "case-a", assessment(), observations=[{**obs, "visibility_scope": "public"}])


def test_replay_uses_original_case_and_evidence_set_after_new_inputs(store):
    store.add_observation("tenant-a", "case-a", observation())
    frozen_case, frozen_obs = store.assessment_inputs("tenant-a", "case-a")
    expected = assessment()
    store.save_assessment("tenant-a", "case-a", expected, observations=frozen_obs, case_version=1)
    store.save_case("tenant-a", {**frozen_case, "finance": {"income_monthly": "99999"}})
    store.add_observation("tenant-a", "case-a", observation("new-evidence"))
    replay_case, replay_obs, stored_result = store.replay_inputs("tenant-a", "assessment-a")
    assert replay_case == frozen_case and replay_obs == frozen_obs and stored_result == expected
    with pytest.raises(NotFound):
        store.replay_inputs("tenant-b", "assessment-a")


def test_replay_fails_after_rights_change_or_evidence_tampering(store):
    obs = store.add_observation("tenant-a", "case-a", observation())
    store.save_assessment("tenant-a", "case-a", assessment(), observations=[obs], case_version=1)
    store.set_source_policy("tenant-a", "flood-source", {"process": False})
    with pytest.raises(Forbidden):
        store.replay_inputs("tenant-a", "assessment-a")
    store.set_source_policy("tenant-a", "flood-source", {})
    store.set_source_policy("tenant-a", "flood-source", {"display_raw": False})
    with pytest.raises(Conflict):
        store.replay_inputs("tenant-a", "assessment-a")
    store.set_source_policy("tenant-a", "flood-source", {})
    with store.transaction() as conn:
        conn.execute("UPDATE observations SET body=? WHERE owner_scope=? AND observation_id=?", (json.dumps({**obs, "payload": {"changed": True}}), "tenant-a", "obs-a"))
    with pytest.raises(Conflict):
        store.replay_inputs("tenant-a", "assessment-a")


def test_raw_and_derived_rights_are_separate_and_current_revocation_applies(store):
    obs = observation()
    obs["rights"]["display_raw"] = False
    obs["unapproved_extra_text"] = "RAW SECRET"
    captured = store.add_observation("tenant-a", "case-a", obs)
    redacted = store.list_observations("tenant-a", "case-a", redact=True)[0]
    assert "payload" not in redacted and "unapproved_extra_text" not in redacted and redacted["raw_redacted"]
    store.save_assessment("tenant-a", "case-a", assessment(), observations=[captured])
    assert store.get_assessment("tenant-a", "assessment-a")["status"] == "REVIEW_REQUIRED"
    store.set_source_policy("tenant-a", "flood-source", {"display_derived": False})
    with pytest.raises(Forbidden):
        store.get_assessment("tenant-a", "assessment-a")
    listed = store.list_assessments("tenant-a", "case-a")[0]
    assert listed["display_allowed"] is False and "status" not in listed


def test_derived_permission_absent_fails_closed(store):
    obs = observation()
    obs["rights"]["display_derived"] = False
    captured = store.add_observation("tenant-a", "case-a", obs)
    store.save_assessment("tenant-a", "case-a", assessment(), observations=[captured])
    with pytest.raises(Forbidden):
        store.get_assessment("tenant-a", "assessment-a")


def test_no_retention_means_metadata_only_and_no_raw_payload(store):
    obs = observation()
    obs["rights"]["retain_raw"] = False
    captured = store.add_observation("tenant-a", "case-a", obs)
    assert "payload" not in captured and captured["replay_level"] == "METADATA_ONLY"


def test_review_waiver_does_not_change_priority_or_gap(store):
    result = assessment()
    store.save_assessment("tenant-a", "case-a", result, observations=[])
    review = store.add_review("tenant-a", "assessment-a", "waived", "Buyer accepts the unresolved gap", "f-1")
    assert review["assessment_unchanged"] is True
    assert store.get_assessment("tenant-a", "assessment-a") == result
    assert store.list_reviews("tenant-a", "assessment-a")[0] == review
    with pytest.raises(NotFound):
        store.list_reviews("tenant-b", "assessment-a")


def test_snapshot_raw_rights_and_tenant_scope(store):
    snap = {"snapshot_id": "snap", "source_id": "source", "rights": {"display_raw": False}, "raw_files": ["private"]}
    store.add_snapshot("tenant-a", "case-a", snap)
    with pytest.raises(Forbidden):
        store.get_snapshot("tenant-a", "case-a", "snap", require_raw=True)
    with pytest.raises(NotFound):
        store.get_snapshot("tenant-b", "case-b", "snap")
    with pytest.raises(Conflict):
        store.add_snapshot("tenant-a", "case-a", {**snap, "raw_files": ["different"]})


def test_job_idempotency_is_tenant_bound_and_cannot_replace_payload(store):
    job = store.enqueue_job("tenant-a", "case-a", "collect", {"source": "flood"}, "same-key", now="2026-01-01T00:00:00Z")
    same = store.enqueue_job("tenant-a", "case-a", "collect", {"source": "flood"}, "same-key")
    assert same["job_id"] == job["job_id"]
    with pytest.raises(Conflict):
        store.enqueue_job("tenant-a", "case-a", "collect", {"source": "crime"}, "same-key")
    other = store.enqueue_job("tenant-b", "case-b", "collect", {}, "same-key")
    assert other["job_id"] != job["job_id"]
    with pytest.raises(NotFound):
        store.get_job("tenant-b", job["job_id"])
    assert len(store.list_jobs("tenant-a")) == 1


def test_current_source_policy_hides_previous_job_derived_result(store):
    store.enqueue_job("tenant-a", "case-a", "collect", {"source_id": "flood-source"}, "licensed-job", now="2026-01-01T00:00:00Z")
    claimed = store.claim_job("worker", tenant_id="tenant-a", now="2026-01-01T00:00:01Z")
    store.complete_job("tenant-a", claimed["job_id"], claimed["lease_token"], {"record_count": 123, "status": "SUCCESS"}, now="2026-01-01T00:00:02Z")
    assert store.get_job("tenant-a", claimed["job_id"])["result"]["record_count"] == 123
    store.set_source_policy("tenant-a", "flood-source", {"display_derived": False})
    assert store.get_job("tenant-a", claimed["job_id"])["result"]["status"] == "DISPLAY_RESTRICTED"
    assert "record_count" not in store.list_jobs("tenant-a")[0]["result"]


def test_job_lease_recovers_after_restart_and_stale_worker_cannot_complete(store):
    store.enqueue_job("tenant-a", "case-a", "collect", {}, "restart", now="2026-01-01T00:00:00Z")
    first = store.claim_job("worker-a", tenant_id="tenant-a", lease_seconds=10, now="2026-01-01T00:00:00Z")
    assert first["attempts"] == 1
    restarted = Store(store.path)
    assert restarted.claim_job("worker-b", tenant_id="tenant-a", now="2026-01-01T00:00:09.999Z") is None
    second = restarted.claim_job("worker-b", tenant_id="tenant-a", now="2026-01-01T00:00:10Z")
    assert second["attempts"] == 2 and second["lease_token"] != first["lease_token"]
    with pytest.raises(Conflict):
        restarted.complete_job("tenant-a", first["job_id"], first["lease_token"], {}, now="2026-01-01T00:00:11Z")
    restarted.complete_job("tenant-a", second["job_id"], second["lease_token"], {"snapshot_id": "snapshot-a"}, now="2026-01-01T00:00:11Z")
    visible = restarted.get_job("tenant-a", second["job_id"])
    assert visible["status"] == "SUCCEEDED" and "lease_token" not in visible


def test_worker_failure_has_bounded_retries_and_dead_final_lease_is_terminal(store):
    store.enqueue_job("tenant-a", "case-a", "collect", {}, "bounded", max_attempts=2, now="2026-01-01T00:00:00Z")
    job = store.claim_job("worker", tenant_id="tenant-a", now="2026-01-01T00:00:00Z")
    store.fail_job("tenant-a", job["job_id"], job["lease_token"], "temporary timeout", retry_delay_seconds=5, now="2026-01-01T00:00:01Z")
    assert store.claim_job("worker", tenant_id="tenant-a", now="2026-01-01T00:00:05.999Z") is None
    final = store.claim_job("worker", tenant_id="tenant-a", lease_seconds=1, now="2026-01-01T00:00:06Z")
    assert final["attempts"] == 2
    assert store.claim_job("worker", tenant_id="tenant-a", now="2026-01-01T00:00:07Z") is None
    assert store.get_job("tenant-a", job["job_id"])["status"] == "FAILED"


def test_concurrent_workers_do_not_both_claim_one_job(store):
    store.enqueue_job("tenant-a", "case-a", "collect", {}, "once", now="2026-01-01T00:00:00Z")
    def claim(worker):
        return store.claim_job(worker, tenant_id="tenant-a", now="2026-01-01T00:00:01Z")
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ["first", "second"]))
    assert sum(item is not None for item in claims) == 1


@pytest.mark.parametrize("changed", [{"as_of": []}, {"as_of": "invalid"}, {"as_of": "2026-01-01"}, {"property": "invalid"}, {"finance": []}, {"scenarios": [1]}])
def test_invalid_case_input_is_validation_error(store, changed):
    with pytest.raises(StoreError):
        store.save_case("tenant-a", {**case(), **changed})
