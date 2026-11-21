"""Coordinate capture, reviewed normalisation and immutable assessment.

Acquisition is an external side effect. evaluate_case is a pure function over
captured inputs. Source assertions are explicit case-scoped review evidence;
neither a source bounding rectangle nor a successful HTTP response establishes
property coverage. This module never turns unreviewed raw text into a finding.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json

from shapely.geometry import shape, mapping, GeometryCollection
from shapely.ops import unary_union
from shapely.errors import GEOSException
from pyproj.exceptions import ProjError

from .engine import SUPPORTED_RULE_VERSIONS, apply_purchase_rules, evaluate_case, canonical_hash
from .buyer_context import buyer_context, LOCAL_SOURCES
from .ingestion import collect, load_registry
from .paths import project_root
from .storage import Conflict, NotFound, comparable_sources
from .preoffer_assessment import (IDENTITY_SOURCES, SALES_SOURCE, apply_preoffer, capture_home,
                                 case_with_home, sales_inputs)


SPATIAL_CHECKS = {
    "act_flood_extent": ["S005", "S006"],
    "act_bushfire_2026": ["S011"],
    "act_bushfire_overview_2026": ["S011"],
}


def selected_source(source_id, registry_path=None):
    matches = [r for r in load_registry(registry_path) if r["source_id"] == source_id]
    if len(matches) != 1:
        raise ValueError("Unknown source ID; select an exact ID from the configured registry")
    return deepcopy(matches[0])


def _rights(source):
    rights = source.get("rights", {})
    return {k: rights.get(k) is True for k in ("process", "display_raw", "display_derived", "retain_raw")}


def _promote_spatial(case, source, result):
    """Create reviewed, private observations for a limited exact mapping.

    Coverage, identity and currency assertions require reviewer provenance.
    Query scope must contain the parcel plus positional uncertainty buffer.
    A non-spatial attribute filter cannot be used to establish a negative.
    """
    ids = SPATIAL_CHECKS.get(source["source_id"], [])
    if not ids:
        return [], ["NORMALISATION_REVIEW_REQUIRED"]
    assertions = case.get("source_assertions", {})
    if not isinstance(assertions, dict):
        return [], ["PROPERTY_COVERAGE_REVIEW_REQUIRED"]
    review = assertions.get(source["source_id"], {})
    if not isinstance(review, dict):
        return [], ["PROPERTY_COVERAGE_REVIEW_REQUIRED"]
    if not (review.get("reviewed") is True and review.get("reviewer") and review.get("reviewed_at")
            and review.get("coverage_basis") and review.get("coverage_status") == "COVERED"):
        return [], ["PROPERTY_COVERAGE_REVIEW_REQUIRED"]
    rights = _rights(source)
    if not all(rights[k] for k in ("process", "display_derived", "retain_raw")):
        return [], ["ANALYSIS_RIGHTS_UNCONFIRMED"]
    if result["status"] != "SUCCESS" or result["completeness"].get("status") != "COMPLETE":
        return [], ["COLLECTION_INCOMPLETE"]
    if review.get("current") is not True or review.get("identity_match") is not True:
        return [], ["CURRENCY_OR_IDENTITY_UNCONFIRMED"]
    prop = case.get("property", {})
    if not prop.get("parcel_geometry") or not prop.get("crs") or prop.get("identity_confirmed") is not True:
        return [], ["PARCEL_GEOMETRY_UNRESOLVED"]
    published = review.get("published_at") or result.get("source_published_at")
    if not published:
        return [], ["SOURCE_PUBLICATION_DATE_UNRESOLVED"]
    try:
        reviewed_at = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
        known_at = datetime.fromisoformat(case["as_of"].replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None or reviewed_at > known_at:
            return [], ["REVIEW_NOT_KNOWN_AS_OF"]
    except (ValueError, TypeError, AttributeError, KeyError):
        return [], ["REVIEW_DATE_UNRESOLVED"]
    scope = result["completeness"].get("query_scope", {})
    if not isinstance(scope, dict) or not isinstance(scope.get("where", "1=1"), str) or scope.get("where", "1=1").replace(" ", "") != "1=1":
        return [], ["FILTERED_MECHANISM_SCOPE_REQUIRES_REVIEW"]
    from pyproj import CRS, Transformer
    from shapely.ops import transform
    from shapely.geometry import box
    try:
        subject = shape(prop["parcel_geometry"])
        if subject.is_empty or not subject.is_valid or subject.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Invalid parcel")
        working = CRS.from_user_input(prop["crs"])
        if not working.is_projected or any(a.unit_name.lower() not in ("metre", "meter") for a in working.axis_info[:2]):
            return [], ["METRE_WORKING_CRS_REQUIRED"]
        if review.get("positional_uncertainty_m") is None or isinstance(review.get("positional_uncertainty_m"), bool):
            return [], ["POSITIONAL_UNCERTAINTY_UNRESOLVED"]
        uncertainty = float(review["positional_uncertainty_m"])
        if not 0 <= uncertainty <= 10000:
            return [], ["INVALID_POSITIONAL_UNCERTAINTY"]
        if scope.get("bbox"):
            scope_crs = CRS.from_user_input(scope.get("in_sr", 4326))
            region = box(*scope["bbox"])
            if scope_crs != working:
                region = transform(Transformer.from_crs(scope_crs, working, always_xy=True).transform, region)
            if not region.covers(subject.buffer(uncertainty)):
                return [], ["QUERY_SCOPE_DOES_NOT_COVER_SUBJECT"]
        geometries = []
        for row in result["records"]:
            if row.get("geometry_status") != "PRESENT" or not row.get("geometry"):
                return [], ["SOURCE_GEOMETRY_INCOMPLETE"]
            sr = row.get("crs", {})
            sr = sr.get("latestWkid") or sr.get("wkid") or sr.get("wkt") if isinstance(sr, dict) else sr
            geom = shape(row["geometry"])
            if geom.is_empty or not geom.is_valid or geom.geom_type not in ("Polygon", "MultiPolygon"):
                return [], ["SOURCE_GEOMETRY_INVALID"]
            src_crs = CRS.from_user_input(sr)
            if src_crs != working:
                geom = transform(Transformer.from_crs(src_crs, working, always_xy=True).transform, geom)
            geometries.append(geom)
        extent = unary_union(geometries) if geometries else GeometryCollection()
    except (ValueError, TypeError, KeyError, AttributeError, ProjError, GEOSException):
        return [], ["GEOMETRY_OR_CRS_UNRESOLVED"]
    rows = []
    for check_id in ids:
        payload = {"kind": "spatial", "subject_geometry": prop["parcel_geometry"],
                   "hazard_geometry": mapping(extent), "crs": prop["crs"],
                   "positional_uncertainty_m": uncertainty,
                   "mechanism": "bushfire" if "bushfire" in source["source_id"] else "mapped_flood",
                   "coverage_basis": review["coverage_basis"], "reviewer": review["reviewer"],
                   "reviewed_at": review["reviewed_at"]}
        row = {"check_id": check_id, "property_id": case["property_id"],
               "source_id": source["source_id"], "snapshot_id": result["snapshot_id"],
               "published_at": published, "received_at": result["retrieved_at"],
               "evidence_basis": "reviewed_source_mapping", "confidence": review.get("confidence", "Medium"),
               "visibility_scope": "private", "owner_tenant_id": case["owner_tenant_id"],
               "case_scope_id": case["case_id"], "rights": rights,
               "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED",
                           "complete": True, "current": True, "identity_match": True}, "payload": payload}
        # Retrieval time is a capture receipt, so repeated snapshots reuse the
        # original observation and its original received_at in this case.
        identity = {k: v for k, v in row.items() if k != "received_at"}
        row["observation_id"] = "obs-" + canonical_hash(identity).split(":")[-1]
        rows.append(row)
    return rows, []


def collect_case(*, store, tenant_id, case_id, source_id, output_dir, max_records=1000,
                 max_bytes=20_000_000, bounds=None, registry_path=None):
    case = store.get_case(tenant_id, case_id)
    source = selected_source(source_id, registry_path)
    rights = _rights(source)
    for name, allowed in store.get_source_policy(tenant_id, source_id).items():
        if allowed is False:
            rights[name] = False
    source["rights"] = rights
    scope_dir = Path(output_dir) / canonical_hash({"tenant": tenant_id, "case": case_id}).split(":")[-1]
    result = collect(source, scope_dir, bounds=bounds, max_records=max_records, max_bytes=max_bytes)
    # Stable snapshot versus wall-clock receipt: identical bytes/query reuse one
    # snapshot; all capture receipts remain in the scoped receipt directory.
    snapshot = {k: deepcopy(result[k]) for k in ("source_id", "snapshot_id", "adapter_version", "status", "records",
                                                "completeness", "coverage", "schema", "source_published_at") if k in result}
    snapshot["rights"] = _rights(source)
    snapshot["raw_files"] = [{k: r[k] for k in ("sha256", "bytes", "relative_path", "kind") if k in r}
                             for r in result.get("raw_files", [])]
    if snapshot.get("snapshot_id"):
        store.add_snapshot(tenant_id, case_id, snapshot)
    rows, gaps = _promote_spatial(case, source, result)
    existing = {o["observation_id"]: o for o in store.list_observations(tenant_id, case_id)}
    promoted = []
    for row in rows:
        if row["observation_id"] in existing:
            row["received_at"] = existing[row["observation_id"]].get("received_at", row["received_at"])
        store.add_observation(tenant_id, case_id, row)
        promoted.append(row["observation_id"])
    safe = {"source_id": source_id, "snapshot_id": result.get("snapshot_id"), "status": result["status"],
            "retrieved_at": result["retrieved_at"], "record_count": len(result.get("records", [])),
            "bytes_received": result.get("bytes_received", 0), "completeness": result["completeness"],
            "coverage": result["coverage"], "errors": result["errors"],
            "observation_ids": promoted, "promotion_gaps": gaps,
            "scope_note": "Capture completeness is separate from property assessment coverage"}
    if rights["display_derived"] is not True:
        # Even a count from a parcel-specific query can reveal a restricted
        # hazard result. Preserve operation state, not licensed content metrics.
        safe["record_count"] = None
        safe["bytes_received"] = None
        safe["completeness"] = {"status": "WITHHELD", "reason": "DERIVED_DISPLAY_NOT_AUTHORISED"}
        safe["errors"] = [{"code": error.get("code"), "http_status": error.get("http_status"),
                           "message": "Source detail withheld under display policy"} for error in result["errors"]]
    store.update_source_health(tenant_id, source_id, safe)
    return safe


def assess_case(store, tenant_id, case_id, *, expected_version=None):
    from .buyer_underwriting import MARKETING_SOURCES, capture_public_marketing, underwriting_sources
    from .preoffer_locations import public_evidence, retained_location_evidence

    original = store.get_case(tenant_id, case_id)
    if expected_version is not None and original["case_version"] != expected_version:
        raise Conflict("Case version changed; refresh before assessing")
    restricted = store.restricted_decision_sources(tenant_id, (*LOCAL_SOURCES, *IDENTITY_SOURCES, SALES_SOURCE))
    sale_sources = comparable_sources(original)
    underwriting_ids = set(underwriting_sources(original))
    marketing_id = "jardine_agent_marketing"
    restricted.update(store.restricted_decision_sources(
        tenant_id, IDENTITY_SOURCES | {SALES_SOURCE, marketing_id} | sale_sources | underwriting_ids, raw=True))
    home = capture_home(original, restricted)
    case = case_with_home(original, home)
    local = []
    if home.get("property"):
        for row in public_evidence(case):
            if not store.restricted_decision_sources(tenant_id, {row["source_id"], *row.get("source_ids", [])}):
                store.add_observation(tenant_id, case_id, row, trusted_public=True)
        local = [row for row in retained_location_evidence(case)
                 if not store.restricted_decision_sources(tenant_id, row.get("source_ids", []))]
    _, observations = store.assessment_inputs(tenant_id, case_id, original["case_version"])
    dependencies = {source for row in observations for source in row.get("source_ids", [])}
    restricted.update(store.restricted_decision_sources(tenant_id, dependencies))
    observations = [row for row in observations if
                    all(row.get("rights", {}).get(key) is True for key in ("process", "retain_raw", "display_derived"))
                    and not restricted.intersection(row.get("source_ids", []))]
    checks = evaluate_case(case, observations)
    context = buyer_context(case, checks, restricted_sources=restricted)
    if home.get("issue"):
        from .buyer_context import missing
        context["location"] = {"label": case["property"].get("label"), "latitude": None, "longitude": None,
                               "suburb": None, "issue": home["issue"]}
        for key in ("planning", "spatial", "crime"):
            context[key] = missing("Property location unresolved", home["issue"], case["as_of"])
        context["source_ids"] = []
    context["retained_location_evidence"] = local
    marketing = capture_public_marketing(case, restricted)
    context["public_marketing"] = marketing
    used = set(context["source_ids"]) | set(home.get("source_ids", []))
    used.update(source for row in [*local, *observations] for source in row.get("source_ids", []))
    restricted_sales = sorted(sale_sources & restricted)
    restricted_underwriting = bool(underwriting_ids & restricted)
    if not restricted_underwriting:
        used.update(underwriting_ids)
    if marketing:
        used.update(MARKETING_SOURCES)
    if not restricted_sales:
        used.update(sale_sources)
    if SALES_SOURCE not in restricted:
        used.add(SALES_SOURCE)
    context["source_ids"] = sorted(used)
    result = apply_purchase_rules(case, checks, context)
    sales_capture = sales_inputs(restricted)
    raw_sources = set(home.get("source_ids", []))
    if not restricted_sales:
        raw_sources.update(sale_sources)
    if not restricted_underwriting:
        raw_sources.update(underwriting_ids)
    if marketing:
        raw_sources.update(MARKETING_SOURCES)
    if sales_capture.get("records"):
        raw_sources.add(SALES_SOURCE)
    capture = {"home": home, "sales_capture": sales_capture, "private_sales_withheld": bool(restricted_sales),
               "private_underwriting_withheld": restricted_underwriting, "raw_source_ids": sorted(raw_sources)}
    result = apply_preoffer(case, result, capture)
    if "weekend_study" in case:
        from .weekend_study import attach_study
        result = attach_study(case, result)
    store.save_assessment(tenant_id, case_id, result, observations=observations, case_version=case["case_version"])
    return store.get_assessment(tenant_id, result["assessment_id"])


def replay_assessment(store, tenant_id, assessment_id):
    """Recompute the original result without reading today's location sources."""
    from .purchase_decision import SUPPORTED_PURCHASE_RULE_VERSIONS

    case, observations, saved = store.replay_inputs(tenant_id, assessment_id)
    preoffer = any(key in saved for key in ("preoffer_version", "preoffer_capture", "preoffer_brief"))
    if preoffer:
        capture = saved.get("preoffer_capture")
        if not isinstance(capture, dict) or not isinstance(capture.get("home"), dict):
            raise Conflict("The original pre-offer inputs are unavailable for replay")
        case = case_with_home(case, capture["home"])
    check_version = saved.get("rule_version")
    if not isinstance(check_version, str) or check_version not in SUPPORTED_RULE_VERSIONS:
        raise Conflict("The recorded check rule version is unavailable for replay")
    replayed = evaluate_case(case, observations, rule_version=check_version)
    if any(key in saved for key in ("purchase_rule_version", "purchase_decision", "decision_evidence")):
        version = saved.get("purchase_rule_version")
        if not isinstance(version, str) or version not in SUPPORTED_PURCHASE_RULE_VERSIONS:
            raise Conflict("The recorded purchase decision rule version is unavailable for replay")
        if not isinstance(saved.get("decision_evidence"), dict):
            raise Conflict("The original purchase decision evidence is unavailable for replay")
        replayed = apply_purchase_rules(case, replayed, saved["decision_evidence"], rule_version=version)
    if preoffer:
        replayed = apply_preoffer(case, replayed, capture, version=saved.get("preoffer_version"))
    if "weekend" in saved:
        from .weekend_study import attach_study
        if "weekend_study" not in case:
            raise Conflict("The pinned weekend study is unavailable")
        replayed = attach_study(case, replayed)
    return saved, replayed


def import_observations(store, tenant_id, case_id, rows, *, trusted_public=False, preserve_received_at=False):
    """CLI/admin import; HTTP users cannot declare their uploads public."""
    if isinstance(rows, dict):
        rows = rows.get("observations", [rows])
    if not isinstance(rows, list):
        raise ValueError("Expected an observation object or observations array")
    saved = []
    for row in rows:
        saved.append(store.add_observation(tenant_id, case_id, row, trusted_public=trusted_public,
                                          server_received_at=not preserve_received_at))
    return saved


def enqueue_collection(store, tenant_id, case_id, source_id, *, bounds=None, max_records=1000, max_bytes=20_000_000, idempotency_key):
    selected_source(source_id)
    return store.enqueue_job(tenant_id, case_id, "collect", {"source_id": source_id, "bounds": bounds,
                           "max_records": max_records, "max_bytes": max_bytes}, idempotency_key)


def work_once(store, output_dir, tenant_id=None):
    job = store.claim_job("local-worker", tenant_id=tenant_id, lease_seconds=3600)
    if not job:
        return None
    try:
        if job["kind"] != "collect":
            raise ValueError("Unsupported job type")
        result = collect_case(store=store, tenant_id=job["tenant_id"], case_id=job["case_id"],
                              output_dir=output_dir, **job["payload"])
        if result["status"] in ("UNAVAILABLE", "INVALID_RESPONSE"):
            store.fail_job(job["tenant_id"], job["job_id"], job["lease_token"],
                           json.dumps(result["errors"], sort_keys=True), retry_delay_seconds=5)
        else:
            store.complete_job(job["tenant_id"], job["job_id"], job["lease_token"], result)
    except Exception as exc:
        try:
            store.fail_job(job["tenant_id"], job["job_id"], job["lease_token"], type(exc).__name__, retry_delay_seconds=5)
        except Conflict:
            # Another worker may have reclaimed the lease during collection.
            # A stale token cannot change that worker's outcome.
            current = store.get_job(job["tenant_id"], job["job_id"])
            return {**current, "worker_outcome": "LEASE_LOST_AFTER_ERROR"}
    return store.get_job(job["tenant_id"], job["job_id"])
