from copy import deepcopy

import pytest

from riskengine.engine import evaluate_case
from riskengine.pipeline import assess_case, replay_assessment
from riskengine.storage import Conflict, Store


def inputs():
    case = {"case_id": "local-case", "property_id": "local-unit", "as_of": "2026-02-01T00:00:00Z",
            "property": {"jurisdiction": "ACT", "identity_confirmed": True, "address_id": 8, "block_key": 24,
                         "unit_id": "3", "property_type": "townhouse", "units_plan_no": "12", "unit_class": "B"}}
    address = {"ADDRESS_ID": 8, "BLOCK_KEY": 24, "DOOR_NO": "3", "UNIT_TITLE": "3", "UNITPLAN_NO": "12",
               "UNIT_CLASS": "B", "ASSIGNED": "ASSIGNED", "SUBADDTYPE": "Unit"}
    unit = {"ID": 981, "BLOCK_KEY": 24, "UNIT_NUMBER": "3", "UNIT_PLAN_NO": "12", "UNIT_CLASS": "B",
            "CURRENT_LIFECYCLE_STAGE": "REGISTERED", "OBJECTID": 5}
    records = [("act_addresses", [address]), ("act_unit", [unit, {**unit, "OBJECTID": 6}])]
    rows = [{"check_id": "S002", "source_id": source, "observation_id": source, "property_id": "local-unit",
             "snapshot_id": "snapshot-" + source, "visibility_scope": "public", "evidence_basis": "official_record",
             "published_at": "2026-01-01", "confidence": "High",
             "rights": {"process": True, "display_derived": True, "retain_raw": True, "display_raw": False},
             "quality": {"retrieval_status": "SUCCESS", "identity_match": True, "current": True,
                         "complete": True, "coverage_status": "COVERED"},
             "payload": {"kind": "unit_register", "records": items}} for source, items in records]
    return case, rows


def check(assessment):
    return next(r for r in assessment["check_results"] if r["check_id"] == "S002")


def test_public_join_and_legacy_replay(tmp_path):
    case, rows = inputs()
    store = Store(tmp_path / "evidence.sqlite3")
    store.save_case("buyer", case)
    for row in rows:
        store.add_observation("buyer", case["case_id"], row, trusted_public=True)
    saved = assess_case(store, "buyer", case["case_id"])
    assert check(saved)["complete"] and check(saved)["priority"] == 0
    finding = next(f for f in saved["findings"] if f["check_id"] == "S002")
    assert finding["method"] == "official_register_join"
    assert finding["evidence_ids"] == ["act_addresses", "act_unit"]
    assert finding["snapshot_ids"] == ["snapshot-act_addresses", "snapshot-act_unit"]
    assert finding["details"]["declared_dwelling_type"] == "townhouse"
    assert finding["details"]["ownership_scheme"] == "unit_title"
    assert "Titleholder" in finding["details"]["scope"]
    assert check(saved)["state"] == "ASSESSED"
    assert replay_assessment(store, "buyer", saved["assessment_id"]) == (saved, saved)
    pinned_case, obs = store.assessment_inputs("buyer", case["case_id"])
    old = evaluate_case(pinned_case, obs, rule_version="0.1.0")
    assert not check(old)["complete"] and old["input_hash"] != saved["input_hash"]
    store.save_assessment("buyer", case["case_id"], old, obs)
    assert replay_assessment(store, "buyer", old["assessment_id"]) == (old, old)
    unavailable = {**old, "assessment_id": "unknown-version", "rule_version": "unavailable"}
    store.save_assessment("buyer", case["case_id"], unavailable, obs)
    with pytest.raises(Conflict, match="check rule version"):
        replay_assessment(store, "buyer", unavailable["assessment_id"])


@pytest.mark.parametrize(("source", "record", "change"), [
    (0, 0, {"BLOCK_KEY": 25}), (0, 0, {"ADDRESS_ID": 91}), (0, 0, {"UNIT_TITLE": "4"}),
    (0, 0, {"UNITPLAN_NO": "2"}), (0, 0, {"ASSIGNED": "RETIRED"}),
    (1, 1, {"ID": 982}), (1, 1, {"UNIT_PLAN_NO": "13"}), (1, 0, {"BLOCK_KEY": 25}),
    (1, 0, {"UNIT_CLASS": "A"}), (1, 0, {"CURRENT_LIFECYCLE_STAGE": "PROPOSED"}),
])
def test_register_disagreement_stays_unknown(source, record, change):
    case, rows = inputs()
    rows[source]["payload"]["records"][record].update(change)
    assert check(evaluate_case(case, rows))["state"] == "NOT_ASSESSED"


def test_source_dating_rights_subject_and_ambiguity_gate_complete_scheme():
    case, rows = inputs()
    for mutation in ({"published_at": "2028-01-01"}, {"property_id": "other"}, {"source_id": "unrecognised"},
                     {"rights": {**rows[1]["rights"], "process": False}}, {"snapshot_id": rows[0]["snapshot_id"]},
                     {"evidence_basis": "assertion"},
                     {"quality": {**rows[1]["quality"], "coverage_status": "UNKNOWN"}}):
        result = check(evaluate_case(case, [rows[0], {**rows[1], **mutation}]))
        assert result["state"] == "NOT_ASSESSED" and result["priority"] is None
    assert not check(evaluate_case(case, rows[:1]))["complete"]
    private = {**rows[1], "visibility_scope": "private", "received_at": "2026-01-01", "owner_tenant_id": "buyer",
               "case_scope_id": case["case_id"]}
    assert not check(evaluate_case({**case, "owner_tenant_id": "buyer"}, [rows[0], private]))["complete"]
    for change in ({"unit_id": "4"}, {"ownership_form": "standalone"}, {"property_type": "unknown"}, {"ambiguous": True}):
        assert not check(evaluate_case({**case, "property": {**case["property"], **change}}, rows))["complete"]
    ambiguous = deepcopy(rows)
    ambiguous[0]["payload"]["records"].append({**rows[0]["payload"]["records"][0], "ADDRESS_ID": 9})
    assert not check(evaluate_case(case, ambiguous))["complete"]
