"""Import the fictional Paperbark Court exercise through normal store and assessment paths."""
import json

from .engine import canonical_hash
from .paths import project_root
from .pipeline import assess_case, import_observations
from .storage import Conflict


CASE_ID = "synthetic-full-coverage"
RIGHTS = {"process": True, "display_raw": True, "display_derived": True, "retain_raw": True}


def full_coverage_inputs(tenant_id):
    """Build private, dated observations and their source snapshots from the exercise files."""
    folder = project_root() / "examples" / "full_coverage_demo"
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    evidence = json.loads((folder / "evidence.json").read_text(encoding="utf-8"))
    case["owner_tenant_id"] = tenant_id
    if case["case_id"] != CASE_ID or case.get("demonstration") is not True:
        raise ValueError("Expected the synthetic Paperbark Court exercise")

    observations = []
    snapshots = []
    for source, title in evidence["sources"].items():
        source_id = "synthetic-paperbark-" + source
        records = [row for row in evidence["records"] if row["source"] == source]
        document = {"title": title, "notice": evidence["notice"], "records": records,
                    "property_id": case["property_id"], "published_at": evidence["published_at"]}
        if source == "household":
            document.update(budget=case["finance"], requirements=case["requirements"],
                            scenarios=case["scenarios"])
        snapshot_id = canonical_hash(document)
        snapshots.append({"snapshot_id": snapshot_id, "source_id": source_id, "rights": dict(RIGHTS),
                          "visibility_scope": "private", "demonstration": True, "status": "SUCCESS",
                          "retrieved_at": evidence["received_at"], "document": document})
        for page, row in enumerate(records, start=1):
            check = row["check"]
            observations.append({
                "observation_id": f"paperbark-{check}-{source}-{page}",
                "check_id": check, "property_id": case["property_id"], "source_id": source_id,
                "snapshot_id": snapshot_id, "source_section": page, "source_title": title,
                "source_note": evidence["notice"], "published_at": evidence["published_at"],
                "received_at": evidence["received_at"], "evidence_basis": "synthetic_case_record",
                "visibility_scope": "private", "owner_tenant_id": tenant_id,
                "case_scope_id": CASE_ID, "demonstration": True, "confidence": "Medium",
                "rights": dict(RIGHTS),
                "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED",
                            "complete": True, "current": True, "identity_match": True,
                            "schema_valid": True, "units_valid": True},
                "payload": row["payload"],
            })
    if len(observations) != len(evidence["records"]):
        raise ValueError("A synthetic record references an unknown exercise source")
    return case, observations, snapshots


def import_full_coverage_demo(store, tenant_id):
    """Install or resume the exercise in one tenant, then run its saved assessment."""
    case, observations, snapshots = full_coverage_inputs(tenant_id)
    try:
        store.save_case(tenant_id, case, expected_version=0)
    except Conflict:
        existing = store.get_case(tenant_id, CASE_ID)
        if {key: value for key, value in existing.items() if key != "case_version"} != case:
            raise Conflict("The full-coverage example case already exists with different inputs")
    for snapshot in snapshots:
        store.add_snapshot(tenant_id, CASE_ID, snapshot)
    import_observations(store, tenant_id, CASE_ID, observations, preserve_received_at=True)
    return assess_case(store, tenant_id, CASE_ID)
