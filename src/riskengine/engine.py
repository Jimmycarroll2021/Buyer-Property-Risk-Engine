"""Versioned, deterministic property due-diligence assessment.

The manifest defines what must be checked. Evidence defines what can be said.
Priorities are ordinal actions, not probabilities, expected loss, valuation or
an average. Missing knowledge and known adverse facts remain separate outputs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
import platform
from typing import Any

import pyproj
import shapely

from .finance import evaluate_finance, amount, money, FinanceInputError
from .paths import project_root
from .spatial import assess_spatial, vertical_clearance

ENGINE_VERSION = "0.1.0"
RULE_VERSION = "0.2.0"
SUPPORTED_RULE_VERSIONS = frozenset({"0.1.0", RULE_VERSION})
RUNTIME_VERSIONS = {"python":platform.python_version(), "shapely":shapely.__version__,
                    "geos":shapely.geos_version_string,"pyproj":pyproj.__version__,"proj":pyproj.proj_version_str}
CONFIDENCE = {"Low": 0, "Medium": 1, "High": 2}
UNORDERED_KEYS = {"observations", "checks", "requirements", "scenarios", "supersedes",
                  "source_ids", "rule_ids", "evidence_ids", "snapshot_ids", "input_snapshot_ids",
                  "dependencies", "milestones", "impacts", "source_refs", "rate_schedule"}
PRIVATE_BASES = {"uploaded_document", "private_inspection", "buyer_finances", "buyer_upload"}
PRIVATE_CHECKS = {"S056", "S057", "S058", "S059", "S060", "S064", "S065"}
FUTURE_KINDS = {"project", "opportunity"}
# These catalogue signals require stock-normalisation, time-series conversion
# or structural scarcity models that are not the same as counting projects.
CONTEXT_ONLY_SUPPLY_CHECKS = {"S038", "S039", "S040"}
RULE_PAYLOADS = {
    "ID01":{"reviewed_fact","spatial"}, "GE01":{"spatial","vertical_clearance","reviewed_fact"},
    "FL01":{"spatial","reviewed_fact"}, "FL02":{"spatial","reviewed_fact"},
    "FI01":{"spatial","reviewed_fact"}, "BD01":{"inspection","reviewed_fact"},
    "BD02":{"document","reviewed_fact"}, "LG01":{"restriction","reviewed_fact"},
    "IN01":{"insurance","reviewed_fact"}, "DV01":{"project","reviewed_fact"},
    "DV02":{"project","reviewed_fact"}, "SP01":{"project"}, "CR01":{"context"},
    "OP01":{"opportunity","project"}
}


class EngineInputError(ValueError):
    pass


def _canonical(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise EngineInputError("JSON object keys must be strings")
        return {k: _canonical(v, k) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        items = [_canonical(v) for v in value]
        if key in UNORDERED_KEYS:
            items.sort(key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return items
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise EngineInputError("Non-finite decimal input")
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise EngineInputError("Non-finite numeric input")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise EngineInputError(f"Unsupported input type: {type(value).__name__}")


def canonical_hash(value: Any) -> str:
    body = json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _date(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EngineInputError(f"{name} must be an explicit ISO date or timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EngineInputError(f"{name} is not an ISO date or timestamp") from exc
    if parsed.tzinfo is None:
        if len(value) != 10:
            raise EngineInputError(f"{name} must include a timezone")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_checks(checks: list[dict] | dict | None) -> list[dict]:
    if checks is None:
        with (project_root() / "config" / "checks.json").open(encoding="utf-8") as handle:
            checks = json.load(handle)
    if isinstance(checks, dict):
        checks = checks.get("checks")
    if not isinstance(checks, list):
        raise EngineInputError("Check manifest must contain a checks list")
    result = []
    seen = set()
    for row in checks:
        if not isinstance(row, dict) or not isinstance(row.get("check_id"), str) or not row["check_id"]:
            raise EngineInputError("Every check requires a non-empty check_id")
        if row["check_id"] in seen:
            raise EngineInputError("Duplicate check_id in manifest")
        seen.add(row["check_id"])
        item = {"label": row["check_id"], "domain": "Other", "critical": False,
                "required": True, "public_check": True, "rule_ids": [], **row}
        if any(not isinstance(item[k], bool) for k in ("critical", "required", "public_check")):
            raise EngineInputError("Check required, critical and public_check flags must be booleans")
        result.append(item)
    return sorted(result, key=lambda x: x["check_id"])


def _essential(case: dict, requirement_id: str | None) -> bool:
    return bool(requirement_id and any(r.get("requirement_id") == requirement_id and r.get("essential") is True
                                     for r in case.get("requirements", [])))


def _na(reason: str, *, detail: str | None = None) -> dict:
    return {"state": "NOT_ASSESSED", "priority": None, "reason": reason, "detail": detail,
            "findings": [], "opportunities": [], "extra_gaps": []}


def _finding(rule: str, priority: int, summary: str, *, details: dict | None = None,
             factor_id: str | None = None, method: str = "deterministic_rule") -> dict:
    return {"rule_id": rule, "priority": priority, "summary": summary,
            "details": details or {}, "factor_id": factor_id or rule, "method": method}


def _assessed(findings: list[dict] | None = None, *, opportunities: list[dict] | None = None,
              details: dict | None = None, extra_gaps: list[dict] | None = None) -> dict:
    findings = findings or []
    priorities = [f["priority"] for f in findings if f.get("priority") is not None]
    return {"state": "ASSESSED", "priority": max(priorities) if priorities else None, "reason": None,
            "findings": findings, "opportunities": opportunities or [], "details": details or {},
            "extra_gaps": extra_gaps or []}


def _gate(observation: dict, case: dict, as_of: datetime) -> str | None:
    """Eligibility gate returns a stable reason; no fallback to payload claims."""
    if observation.get("property_id") != case["property_id"]:
        return "PROPERTY_SCOPE_MISMATCH"
    if not observation.get("observation_id") or not observation.get("source_id") or not observation.get("snapshot_id"):
        return "PROVENANCE_MISSING"
    scope = observation.get("visibility_scope")
    if scope not in ("public", "private"):
        return "VISIBILITY_SCOPE_MISSING"
    if scope == "private":
        if not case.get("owner_tenant_id") or observation.get("owner_tenant_id") != case.get("owner_tenant_id") or observation.get("case_scope_id") != case["case_id"]:
            return "PRIVATE_SCOPE_MISMATCH"
    elif observation.get("owner_tenant_id") is not None or observation.get("case_scope_id") is not None or observation.get("evidence_basis") in PRIVATE_BASES or observation.get("origin_visibility_scope") == "private":
        return "PRIVATE_DATA_IN_PUBLIC_SCOPE"
    rights = observation.get("rights") or {}
    if rights.get("process") is not True:
        return "PROCESSING_NOT_AUTHORISED"
    if rights.get("display_derived") is not True:
        return "DERIVED_DISPLAY_NOT_AUTHORISED"
    quality = observation.get("quality") or {}
    if quality.get("retrieval_status") != "SUCCESS":
        return "SOURCE_RETRIEVAL_FAILED"
    if quality.get("schema_valid", True) is not True:
        return "SCHEMA_UNRESOLVED"
    if quality.get("units_valid", True) is not True:
        return "UNITS_UNRESOLVED"
    if quality.get("coverage_status") != "COVERED":
        return "OUTSIDE_COVERAGE" if quality.get("coverage_status") == "OUTSIDE_COVERAGE" else "COVERAGE_UNKNOWN"
    if quality.get("complete") is not True:
        return "SOURCE_INCOMPLETE"
    if quality.get("current") is not True:
        return "STALE_OR_CURRENCY_UNKNOWN"
    if quality.get("identity_match") is not True:
        return "UNRESOLVED_PROPERTY_ID"
    if quality.get("conflict") is True:
        return "CONFLICT_UNRESOLVED"
    if observation.get("confidence") not in CONFIDENCE:
        return "CONFIDENCE_UNDECLARED"
    if not observation.get("evidence_basis"):
        return "EVIDENCE_BASIS_MISSING"
    try:
        # Publication is knowledge time for public evidence; an uploaded private
        # document cannot have been known to this case before it was received.
        if scope == "private":
            known = _date(observation.get("received_at"), "received_at")
            if observation.get("published_at") is not None:
                known = max(known, _date(observation["published_at"], "published_at"))
        else:
            known = _date(observation.get("published_at"), "published_at")
        if known > as_of:
            return "NOT_KNOWN_AS_OF"
        if rights.get("expires_at") and _date(rights["expires_at"], "rights.expires_at") <= as_of:
            return "RIGHTS_EXPIRED"
        payload = observation.get("payload")
        if not isinstance(payload, dict):
            return "PAYLOAD_MISSING"
        if observation.get("effective_from") and _date(observation["effective_from"], "effective_from") > as_of and payload.get("kind") not in FUTURE_KINDS:
            return "NOT_EFFECTIVE_AS_OF"
        if observation.get("effective_to") and _date(observation["effective_to"], "effective_to") <= as_of:
            return "NO_LONGER_EFFECTIVE_AS_OF"
    except EngineInputError:
        return "KNOWLEDGE_DATE_UNRESOLVED"
    return None


def _supersession(rows: list[dict]) -> tuple[list[dict], str | None]:
    by_id = {r["observation_id"]: r for r in rows}
    edges: dict[str, set[str]] = {}
    for row in rows:
        ids = row.get("supersedes", [])
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            return rows, "SUPERSESSION_INVALID"
        valid = set()
        for old in ids:
            if old in by_id:
                if row["source_id"] != by_id[old]["source_id"] and row.get("supersession_reviewed") is not True:
                    return rows, "SUPERSESSION_REVIEW_REQUIRED"
                valid.add(old)
        edges[row["observation_id"]] = valid
    def cyclic(node: str, path: set[str]) -> bool:
        if node in path:
            return True
        return any(cyclic(n, path | {node}) for n in edges.get(node, set()))
    if any(cyclic(n, set()) for n in edges):
        return rows, "SUPERSESSION_CYCLE"
    obsolete = set().union(*edges.values()) if edges else set()
    return [r for r in rows if r["observation_id"] not in obsolete], None


def _claim_key(payload: dict) -> str:
    if payload.get("kind") in ("project", "opportunity"):
        return str(payload.get("project_id", ""))
    return "|".join(str(payload.get(k, "")) for k in
                    ("kind", "fact_key", "subject_scope", "mechanism", "factor_id", "reference_period"))


def _resolve(rows: list[dict], *, unit_register: bool = False) -> tuple[list[dict], str | None]:
    active, error = _supersession(rows)
    if error:
        return active, error
    claims: dict[str, set[str]] = defaultdict(set)
    for row in active:
        p = row["payload"]
        if unit_register and p.get("kind") == "unit_register":
            continue  # Both complementary registers are checked together below.
        if p.get("kind") not in ("project", "opportunity"):
            claims[_claim_key(p)].add(canonical_hash(p))
    if any(len(values) > 1 for values in claims.values()):
        return active, "CONFLICT_UNRESOLVED"
    return active, None


def _unit_register(rows: list[dict], case: dict) -> dict:
    """Resolve an ACT registered unit scheme from two dated, independently gated sources."""
    by_source = {row["source_id"]: row for row in rows}
    if len(rows) != 2 or set(by_source) != {"act_addresses", "act_unit"}:
        return _na("UNIT_REGISTER_PAIR_REQUIRED")
    if any(row.get("visibility_scope") != "public" or row.get("evidence_basis") != "official_record"
           or row["payload"].get("kind") != "unit_register" for row in rows):
        return _na("OFFICIAL_UNIT_REGISTER_EVIDENCE_REQUIRED")
    if len({row["snapshot_id"] for row in rows}) != 2:
        return _na("INDEPENDENT_UNIT_REGISTER_SNAPSHOTS_REQUIRED")
    addresses = by_source["act_addresses"]["payload"].get("records")
    units = by_source["act_unit"]["payload"].get("records")
    if (not isinstance(addresses, list) or len(addresses) != 1 or not isinstance(addresses[0], dict)
            or not isinstance(units, list) or not units or not all(isinstance(unit, dict) for unit in units)):
        return _na("UNIT_REGISTER_SELECTION_UNRESOLVED")

    def identifier(record, key):
        value = record.get(key)
        return str(value).strip() if type(value) in (str, int) else ""

    address = addresses[0]
    subject = case["property"]
    if subject.get("jurisdiction") != "ACT" or address.get("ASSIGNED") != "ASSIGNED" or address.get("SUBADDTYPE") != "Unit":
        return _na("UNIT_REGISTER_SELECTION_UNRESOLVED")
    dwelling = subject.get("property_type")
    if not isinstance(dwelling, str) or dwelling.lower().strip() not in {"unit", "apartment", "flat", "house", "townhouse", "villa", "duplex"}:
        return _na("DECLARED_DWELLING_TYPE_UNRESOLVED")
    address_id = identifier(address, "ADDRESS_ID")
    block = identifier(address, "BLOCK_KEY")
    unit_no = identifier(address, "UNIT_TITLE")
    plan = identifier(address, "UNITPLAN_NO")
    unit_class = address.get("UNIT_CLASS")
    if (not all((address_id, block, unit_no, plan)) or unit_class not in ("A", "B")
            or identifier(address, "DOOR_NO") != unit_no
            or (address_id, block, unit_no) != tuple(identifier(subject, key) for key in ("address_id", "block_key", "unit_id"))):
        return _na("UNIT_REGISTER_SUBJECT_MISMATCH")
    if (subject.get("ownership_form") not in (None, "unit_title", "strata")
            or subject.get("unit_class") not in (None, unit_class)
            or (subject.get("units_plan_no") is not None and identifier(subject, "units_plan_no") != plan)):
        return _na("UNIT_REGISTER_SUBJECT_MISMATCH")
    scheme_id = identifier(units[0], "ID")
    for unit in units:
        if (not scheme_id or identifier(unit, "ID") != scheme_id or unit.get("CURRENT_LIFECYCLE_STAGE") != "REGISTERED"
                or unit.get("UNIT_CLASS") != unit_class or identifier(unit, "UNIT_PLAN_NO") != plan
                or identifier(unit, "UNIT_NUMBER") != unit_no or identifier(unit, "BLOCK_KEY") != block):
            return _na("UNIT_REGISTER_RECORDS_DISAGREE")
    details = {"declared_dwelling_type": dwelling, "ownership_scheme": "unit_title", "unit_class": unit_class,
               "units_plan_no": plan, "unit_number": unit_no, "block_key": block, "address_id": address_id,
               "registered_unit_id": scheme_id,
               "scope": "Public register scheme classification. Building form is declared. Titleholder, title terms, lease obligations and encumbrances require separate evidence."}
    return _assessed([_finding("ID01", 0, f"The ACT registers match Unit {unit_no} to Class {unit_class}, Units Plan {plan}.",
                               details=details, method="official_register_join")])


def _manual(payload: dict, case: dict, check: dict) -> dict:
    kind = payload.get("kind")
    if payload.get("reviewed") is not True:
        return _na("REVIEW_REQUIRED", detail="Extracted or asserted document claims require explicit human review")
    if payload.get("extraction_reviewed") is False:
        return _na("EXTRACTION_UNREVIEWED")
    rules = check["rule_ids"]
    rule = next((r for r in rules if r in ("BD01", "BD02", "LG01", "IN01", "ID01", "FI01")), "REVIEWED_FACT")
    requirement = payload.get("requirement_id")
    essential_conflict = payload.get("conflict") is True and _essential(case, requirement)
    summary = payload.get("statement") or payload.get("summary")
    details = {"evidence_kind": kind, "reviewed": True, "requirement_id": requirement,
               "scope": payload.get("scope", "Submitted structured review"),
               "modelled": False}
    gaps = []
    if kind == "inspection":
        rule = "BD01"
        if not isinstance(payload.get("material_defect"), bool):
            return _na("MATERIALITY_UNRESOLVED")
        if payload["material_defect"]:
            priority = 4 if essential_conflict else 3
            summary = summary or "Reviewed inspection reports a material defect"
            if payload.get("cost_known") is not True:
                gaps.append({"reason": "REPAIR_COST_UNKNOWN", "priority": 2,
                             "summary": "The observed defect has no reviewed repair-cost evidence"})
        elif payload.get("scope_complete") is not True:
            return _na("INSPECTION_SCOPE_INCOMPLETE")
        else:
            priority = 1 if payload.get("minor_issue") is True else 0
            summary = summary or "No material defect reported within the reviewed inspection scope"
        # Numerical costs never arise from free text or an unreviewed extraction.
        if payload.get("repair_cost") is not None:
            if payload.get("cost_known") is True and payload.get("cost_source_ref"):
                details["repair_cost"] = money(amount(payload["repair_cost"], "repair_cost"))
                details["cost_source_ref"] = payload["cost_source_ref"]
            else:
                gaps.append({"reason": "COST_EVIDENCE_UNREVIEWED", "priority": 2,
                             "summary": "A supplied cost was withheld because its reviewed source is missing"})
    elif kind == "document":
        rule = "BD02"
        if payload.get("scope_complete") is not True:
            return _na("DOCUMENT_SCOPE_INCOMPLETE")
        if essential_conflict:
            priority = 4
        elif payload.get("material_liability_unresolved") is True:
            priority = 3
        elif payload.get("liability_amount") is not None:
            liability = amount(payload["liability_amount"], "liability_amount")
            details["liability_amount"] = money(liability)
            priority = 2 if liability > 0 else 0
        elif payload.get("no_material_liability") is True:
            priority = 0
        else:
            return _na("LIABILITY_UNRESOLVED")
        summary = summary or "Reviewed common-property financial and document position"
    elif kind in ("restriction", "insurance"):
        rule = "LG01" if kind == "restriction" else "IN01"
        if not isinstance(payload.get("conflict"), bool):
            return _na("CONFLICT_STATUS_UNRESOLVED")
        if essential_conflict:
            priority = 4
        elif payload.get("material_question") is True or payload.get("material_exclusion") is True:
            priority = 3
        elif payload["conflict"] or payload.get("nonessential_constraint") is True:
            priority = 2
        elif payload.get("scope_complete") is True:
            priority = 0
        else:
            return _na("REVIEW_SCOPE_INCOMPLETE")
        summary = summary or ("Reviewed legal compatibility" if kind == "restriction" else "Reviewed quoted insurance cover")
    else:
        if not isinstance(payload.get("issue_present"), bool) or not summary:
            return _na("REVIEWED_FACT_INCOMPLETE")
        if payload["issue_present"]:
            priority = 4 if essential_conflict else (3 if payload.get("material") is True else (1 if payload.get("minor") is True else 2))
        elif payload.get("scope_complete") is True:
            priority = 0
        else:
            return _na("REVIEW_SCOPE_INCOMPLETE")
    return _assessed([_finding(rule, priority, summary, details=details,
                              factor_id=payload.get("factor_id"), method="reviewed_structured_fact")], extra_gaps=gaps)


def _context(payload: dict, check: dict, as_of: datetime) -> dict:
    if "CR01" in check["rule_ids"]:
        required = ("count", "denominator", "period_start", "period_end", "area_id", "boundary_version", "definition")
        if any(payload.get(k) is None for k in required) or payload.get("comparable") is not True:
            return _na("CRIME_COMPARABILITY_UNRESOLVED")
        count = amount(payload["count"], "count")
        denominator = amount(payload["denominator"], "denominator")
        if denominator == 0 or count != count.to_integral_value():
            return _na("DENOMINATOR_INVALID")
        if _date(payload["period_end"], "period_end") <= _date(payload["period_start"], "period_start"):
            return _na("PERIOD_INVALID")
        if _date(payload["period_end"], "period_end") > as_of:
            return _na("NOT_EFFECTIVE_AS_OF")
        base = amount(payload.get("rate_base", 1000), "rate_base")
        if base == 0:
            return _na("DENOMINATOR_INVALID")
        rate = count / denominator * base
        threshold = payload.get("declared_rate_threshold")
        priority = 2 if threshold is not None and rate > amount(threshold, "declared_rate_threshold") else 1
        return _assessed([_finding("CR01", priority, "Area-level recorded crime context",
            details={"count": str(count), "denominator": str(denominator), "rate": money(rate),
                     "rate_base": str(base), "period_start": payload["period_start"], "period_end": payload["period_end"],
                     "area_id": payload["area_id"], "definition": payload["definition"], "boundary_version": payload["boundary_version"],
                     "scope": "Recorded events in an area; not the probability of victimisation at this dwelling"},
            factor_id=payload.get("factor_id", "crime_context"))])
    if not payload.get("summary"):
        return _na("CONTEXT_INCOMPLETE")
    details = {"modelled": False, "scope": "Evidence context; no property-value or event-probability model"}
    priority = 1
    if payload.get("measure") is not None:
        measure = amount(payload["measure"], "measure", minimum=None)
        if not payload.get("unit") or not payload.get("definition"):
            return _na("MEASURE_DEFINITION_MISSING")
        details.update(measure=str(measure), unit=payload["unit"], definition=payload["definition"])
        if payload.get("threshold") is not None:
            if payload.get("comparable") is not True or not payload.get("threshold_basis"):
                return _na("THRESHOLD_BASIS_MISSING")
            threshold = amount(payload["threshold"], "threshold", minimum=None)
            direction = payload.get("threshold_direction", "above")
            if direction not in ("above", "below"):
                return _na("THRESHOLD_DIRECTION_INVALID")
            breach = measure > threshold if direction == "above" else measure < threshold
            priority = 2 if breach else 1
            details.update(threshold=str(threshold), threshold_basis=payload["threshold_basis"])
    return _assessed([_finding("CONTEXT", priority, payload["summary"], details=details,
                              factor_id=payload.get("factor_id"), method="structured_context")])


def _spatial(payload: dict, check: dict) -> dict:
    spatial = assess_spatial(payload, coverage_status="COVERED")
    if spatial["state"] != "ASSESSED":
        return {**_na(spatial["reason"]), "details": spatial}
    overlap = spatial["relation"] == "POSITIVE_OVERLAP"
    rule = "FI01" if "FI01" in check["rule_ids"] or payload.get("mechanism") == "bushfire" else "FL01" if "FL01" in check["rule_ids"] else "GE01"
    priority = (3 if overlap else 0) if rule != "GE01" else (2 if overlap else 0)
    gaps = []
    if overlap and payload.get("resolution_reviewed") is True:
        if payload.get("resolution_source_ref") and payload.get("consequence_resolved") is True:
            priority = 1
            spatial["designation_retained"] = True
            spatial["resolution_source_ref"] = payload["resolution_source_ref"]
        else:
            gaps.append({"reason":"RESOLUTION_EVIDENCE_MISSING", "priority":3,
                         "summary":"A claimed resolution is not backed by a reviewed source"})
    summary = "Mapped extent overlaps the assessed polygon" if overlap else "No overlap in the stated mapped mechanism and covered area"
    return _assessed([_finding(rule, priority, summary, details=spatial,
                              factor_id=payload.get("factor_id", payload.get("mechanism", rule)))], extra_gaps=gaps)


def _projects(rows: list[dict], case: dict, check: dict, as_of: datetime) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not row["payload"].get("project_id"):
            return _na("PROJECT_ID_UNRESOLVED")
        grouped[str(row["payload"]["project_id"])].append(row)
    projects, findings, opportunities, gaps = [], [], [], []
    total = Decimal(0)
    supply_scope_complete = True
    for project_id, records in sorted(grouped.items()):
        payloads = [r["payload"] for r in records]
        milestones = []
        for r in records:
            for m in r["payload"].get("milestones", []):
                if not m.get("kind") or not m.get("date"):
                    gaps.append({"reason":"MILESTONE_INCOMPLETE", "priority":2, "summary":"A project milestone lacks an explicit kind or date"})
                    continue
                known = _date(m.get("published_at", r["published_at"]), "milestone.published_at")
                event = _date(m["date"], "milestone.date")
                if known > as_of or (event > as_of and m["kind"] not in ("expected_completion", "planned_completion", "revised_completion")):
                    continue
                milestones.append({"kind":m["kind"], "date":m["date"], "published_at":m.get("published_at",r["published_at"]),
                                   "source_id":r["source_id"]})
        milestones = sorted({canonical_hash(m):m for m in milestones}.values(),key=lambda m:(m["kind"],m["date"],m["source_id"]))
        expected = {p["expected_completion"] for p in payloads if p.get("expected_completion")}
        if len(expected) > 1:
            return _na("PROJECT_TIMING_CONFLICT")
        completion = next(iter(expected), None)
        if completion:
            _date(completion, "expected_completion")
        net = {str(amount(p["net_dwellings"], "net_dwellings", minimum=None).normalize()) for p in payloads if p.get("net_dwellings") is not None}
        if len(net) > 1:
            return _na("PROJECT_QUANTITY_CONFLICT")
        quantity = Decimal(next(iter(net))) if net else None
        if quantity is not None and quantity != quantity.to_integral_value():
            return _na("PROJECT_QUANTITY_INVALID")
        comparable = any(p.get("scope_comparable") is True for p in payloads)
        cancelled = any(m["kind"] in ("cancelled", "cancellation") for m in milestones)
        actual_completion_dates = {m["date"] for m in milestones if m["kind"] == "completed"}
        if len(actual_completion_dates) > 1:
            return _na("PROJECT_COMPLETION_CONFLICT")
        completed = bool(actual_completion_dates)
        actual_completion = next(iter(actual_completion_dates),None)
        included = not cancelled and not completed
        if "SP01" in check["rule_ids"] and included:
            if quantity is None or not comparable:
                supply_scope_complete = False
            else:
                total += quantity
        project = {"project_id":project_id, "milestones":milestones, "net_dwellings":int(quantity) if quantity is not None else None,
                   "expected_completion":completion, "cancelled":cancelled,
                   "actual_completion":actual_completion,"included_in_future_supply":included,
                   "scope":"Milestones are independently evidenced; approval does not imply funding or construction"}
        projects.append(project)
        impacts = {canonical_hash(i):i for p in payloads for i in p.get("impacts", [])}
        for _, impact in sorted(impacts.items()):
            if impact.get("supported") is not True:
                gaps.append({"reason":"PROJECT_IMPACT_UNSUPPORTED", "priority":2, "summary":"A proposed project impact lacks supporting analysis"})
                continue
            req = impact.get("requirement_id")
            if impact.get("measured_value") is not None or impact.get("threshold") is not None:
                if any(impact.get(k) is None for k in ("measured_value", "threshold", "method", "unit")):
                    gaps.append({"reason":"IMPACT_MEASUREMENT_INCOMPLETE", "priority":3, "summary":"Measured impact needs a method, unit and threshold"})
                    continue
                measure = amount(impact["measured_value"], "measured_value", minimum=None)
                threshold = amount(impact["threshold"], "threshold", minimum=None)
                direction = impact.get("threshold_direction", "above")
                if direction not in ("above", "below"):
                    return _na("THRESHOLD_DIRECTION_INVALID")
                breach = measure > threshold if direction == "above" else measure < threshold
                priority = (4 if impact.get("current_condition") is True else 3) if breach and _essential(case,req) else (2 if breach else 0)
                rule = "DV02"
            else:
                priority = 3 if impact.get("material") is True and _essential(case,req) else (2 if impact.get("material") is True else 1)
                rule = "DV01"
            findings.append(_finding(rule, priority, impact.get("description", "Supported project impact"),
                details={"project_id":project_id, **impact}, factor_id=impact.get("factor_id", project_id)))
        for p in payloads:
            if p.get("kind") == "opportunity" or p.get("benefit"):
                if p.get("benefit_supported") is not True or p.get("timing_known") is not True or not p.get("benefit"):
                    gaps.append({"reason":"OPPORTUNITY_EVIDENCE_INCOMPLETE", "priority":2,
                                 "summary":"Potential benefit needs supporting evidence and known timing"})
                elif not cancelled:
                    if not completion and not any(m["kind"] == "completed" for m in milestones):
                        gaps.append({"reason":"BENEFIT_TIMING_UNRESOLVED", "priority":2,
                                     "summary":"Benefit availability has no evidenced completion or expected date"})
                    else:
                        opportunities.append({"rule_id":"OP01", "project_id":project_id, "benefit":p["benefit"],
                            "available_from":actual_completion or completion, "conditional":not completed,
                            "dependencies":sorted(p.get("dependencies", [])), "milestones":milestones,
                            "priority":None, "price_uplift":None,
                            "scope":"Supported potential benefit; does not offset adverse findings or forecast a price change"})
    if "SP01" in check["rule_ids"]:
        if not supply_scope_complete:
            return {**_na("COMPETING_SUPPLY_SCOPE_UNRESOLVED"), "details":{"projects":projects}}
        thresholds = {str(p["declared_net_dwellings_threshold"]) for r in rows for p in [r["payload"]] if p.get("declared_net_dwellings_threshold") is not None}
        if len(thresholds) > 1:
            return _na("SUPPLY_THRESHOLD_CONFLICT")
        threshold = amount(next(iter(thresholds)), "declared_net_dwellings_threshold") if thresholds else None
        priority = 2 if threshold is not None and total > threshold else (1 if total != 0 else 0)
        findings.append(_finding("SP01",priority,"Canonical competing dwelling pipeline",
            details={"net_dwellings":int(total), "unique_projects":len(projects),
                     "scope":"Signed unweighted future net stock change in declared comparable scope; cancelled and completed projects excluded; no completion probability or price forecast"}, factor_id="competing_supply"))
    elif not findings and not opportunities and not gaps:
        findings.append(_finding("DV01",1,"Project context has been recorded",details={"projects":projects},method="structured_context"))
    unique_opps = list({canonical_hash(o):o for o in opportunities}.values())
    return _assessed(findings, opportunities=unique_opps, details={"projects":projects}, extra_gaps=gaps)


def _evaluate_payloads(rows: list[dict], case: dict, check: dict, as_of: datetime) -> dict:
    kinds = {r["payload"].get("kind") for r in rows}
    required_kinds = set().union(*(RULE_PAYLOADS[r] for r in check["rule_ids"] if r in RULE_PAYLOADS))
    if check["check_id"] in CONTEXT_ONLY_SUPPLY_CHECKS:
        required_kinds = {"context", "reviewed_fact"}
        if not kinds <= required_kinds:
            return _na("SIGNAL_MODEL_NOT_IMPLEMENTED", detail="Project totals alone do not calculate approvals intensity, conversion/delay or structural scarcity; supply reviewed findings or scoped context")
    if required_kinds and not kinds <= required_kinds:
        return _na("PAYLOAD_NOT_SUITABLE_FOR_RULE",detail="This check requires a structured evidence kind suitable for its rule")
    if kinds <= {"project", "opportunity"}:
        return _projects(rows, case, check, as_of)
    findings, opportunities, details, gaps = [], [], [], []
    failures = []
    seen = set()
    for row in rows:
        p = row["payload"]
        signature = canonical_hash(p)
        if signature in seen:
            continue
        seen.add(signature)
        kind = p.get("kind")
        try:
            if kind == "spatial":
                result = _spatial(p, check)
            elif kind in ("inspection", "document", "restriction", "insurance", "reviewed_fact"):
                result = _manual(p, case, check)
            elif kind == "context":
                result = _context(p, check, as_of)
            elif kind == "vertical_clearance":
                v = vertical_clearance(p.get("floor_height"),p.get("flood_height"),floor_datum=p.get("floor_datum"),flood_datum=p.get("flood_datum"),unit=p.get("unit","m"))
                result = _assessed([_finding("GE01",1,"Declared floor and flood height comparison",details=v)]) if v["state"]=="ASSESSED" else _na(v["reason"])
            else:
                result = _na("UNSUPPORTED_PAYLOAD_KIND", detail=str(kind))
        except (FinanceInputError, EngineInputError, InvalidOperation, TypeError, ValueError) as exc:
            result = _na("INVALID_STRUCTURED_INPUT", detail=str(exc))
        for f in result.get("findings", []):
            f["evidence_ids"] = [row["observation_id"]]
        for o in result.get("opportunities", []):
            o["evidence_ids"] = [row["observation_id"]]
        findings += result.get("findings", [])
        opportunities += result.get("opportunities", [])
        gaps += result.get("extra_gaps", [])
        if result.get("details"):
            details.append(result["details"])
        if result["state"] != "ASSESSED":
            failures.append({"reason":result["reason"],"detail":result.get("detail"),"observation_id":row["observation_id"]})
    required_mechanisms = set(check.get("required_mechanisms", []))
    observed_mechanisms = {r["payload"].get("mechanism") for r in rows if r["payload"].get("kind")=="spatial"}
    if required_mechanisms - observed_mechanisms:
        failures.append({"reason":"MECHANISM_COVERAGE_INCOMPLETE", "detail":", ".join(sorted(required_mechanisms-observed_mechanisms))})
    result = _assessed(findings,opportunities=opportunities,details={"observations":details},extra_gaps=gaps)
    if failures:
        result.update(state="NOT_ASSESSED", priority=None, reason=failures[0]["reason"], failures=failures)
    return result


def _finance_result(check: dict, finance: dict, case: dict) -> dict | None:
    cid, rules = check["check_id"], check["rule_ids"]
    if cid == "S060":
        items = [("CONDITIONAL_EXIT", finance["exit"], "Conditional sale proceeds after debt and supplied exit costs")]
    elif "FN04" in rules:
        items = [("FN04", finance["settlement"], "Settlement funding sufficiency")]
    elif "FN03" in rules or cid == "S058":
        selected = [s for s in finance["scenarios"] if str(s.get("assumptions", {}).get("income_factor", "1")) not in ("1", "1.0", "1.00")]
        items = [("FN03", finance["buffer"], "Post-settlement reserve sufficiency")]
        items += [("FN02", s, f"Income stress: {s['scenario_id']}") for s in selected]
        if cid == "S058" and not selected:
            items.append(("FN02", {"state":"NOT_ASSESSED", "reason":"INCOME_SCENARIO_MISSING", "priority":None}, "Income stress"))
    elif "FN02" in rules:
        selected = finance["scenarios"]
        if cid == "S057":
            selected = [s for s in selected if str(s.get("assumptions", {}).get("rate_delta_bps", 0)) not in ("0", "0.0", "0.00")]
        items = [("FN02", s, f"Conditional stress: {s['scenario_id']}") for s in selected]
        if not items:
            items = [("FN02", {"state":"NOT_ASSESSED", "reason":"STRESS_SCENARIO_MISSING", "priority":None}, "Stress scenario")]
    elif "FN01" in rules:
        items = [("FN01", finance["baseline"], "Baseline monthly cash flow")]
    else:
        return None
    findings, failures = [], []
    for rule, part, summary in items:
        if part["state"] == "ASSESSED":
            details = {k:v for k,v in part.items() if k not in ("state", "priority", "monthly_schedule")}
            findings.append(_finding(rule,part.get("priority",0),summary,details=details,
                                    factor_id=f"cash_flow:{part.get('scenario_id','baseline')}" if rule in ("FN01","FN02") else rule,
                                    method="conditional_financial_calculation"))
        else:
            failures.append({"rule_id":rule, "reason":part.get("reason","MISSING_INPUT"),
                             "missing_inputs":part.get("missing_inputs", []), "detail":part.get("detail")})
    result = _assessed(findings)
    if failures:
        result.update(state="NOT_ASSESSED",priority=None,reason=failures[0]["reason"],failures=failures)
    return result


def _coverage(results: list[dict], *, public_only: bool = False) -> dict:
    required = [r for r in results if r["required"] and (not public_only or r["public_check"])]
    applicable = [r for r in required if r["state"] != "NOT_APPLICABLE"]
    assessed = [r for r in applicable if r["state"] == "ASSESSED" and r["complete"]]
    count = len(applicable)
    critical = [r["check_id"] for r in applicable if r["critical"] and (r["state"]!="ASSESSED" or not r["complete"])]
    gaps = [r["check_id"] for r in applicable if r["state"]!="ASSESSED" or not r["complete"]]
    return {"required":len(required), "required_applicable":count,"assessed":len(assessed),
            "not_assessed":count-len(assessed),"not_applicable":len(required)-count,
            "percentage":round(100*len(assessed)/count,2) if count else None,
            "ratio":round(len(assessed)/count,6) if count else None,
            "reason":"NO_REQUIRED_APPLICABLE_CHECKS" if count==0 else None,
            "complete":bool(count and not gaps),"critical_gaps":critical,"unresolved_checks":gaps}


def _evaluate_case(case: dict, observations: list[dict], checks: list[dict] | dict | None, rule_version: str) -> dict:
    """Assess a case without network, clock, storage mutation or model calls.

    ``checks`` is a trusted, versioned server manifest override for integration
    and tests. There is intentionally no case-level skip or waiver API that can
    remove required checks. All supplied evidence is pinned into ``input_hash``.
    """
    if not isinstance(case, dict) or not isinstance(observations, list) or any(not isinstance(o,dict) for o in observations):
        raise EngineInputError("Case must be an object and observations a list of objects")
    # Validate serialisability before doing work; NaN cannot enter hashes or maths.
    _canonical(case)
    _canonical(observations)
    for name in ("case_id", "property_id"):
        if not isinstance(case.get(name), str) or not case[name]:
            raise EngineInputError(f"{name} is required")
    as_of = _date(case.get("as_of"), "as_of")
    if not isinstance(case.get("property", {}),dict) or not isinstance(case.get("finance",{}),dict):
        raise EngineInputError("property and finance must be objects")
    if case.get("finance") and not case.get("owner_tenant_id"):
        raise EngineInputError("Financial inputs require a tenant-scoped case")
    requirements = case.get("requirements", [])
    scenarios = case.get("scenarios", [])
    if not isinstance(requirements,list) or any(not isinstance(r,dict) for r in requirements):
        raise EngineInputError("requirements must be a list of objects")
    if not isinstance(scenarios,list) or any(not isinstance(s,dict) for s in scenarios):
        raise EngineInputError("scenarios must be a list of objects")
    requirement_ids = [r.get("requirement_id") for r in requirements]
    if any(not isinstance(i,str) or not i for i in requirement_ids) or len(set(requirement_ids)) != len(requirement_ids):
        raise EngineInputError("Requirement IDs must be non-empty and unique")
    if any(not isinstance(r.get("essential"),bool) for r in requirements):
        raise EngineInputError("Every requirement must explicitly declare whether it is essential")
    scenario_ids = [s.get("scenario_id") for s in scenarios]
    if any(not isinstance(i,str) or not i for i in scenario_ids) or len(set(scenario_ids)) != len(scenario_ids):
        raise EngineInputError("Scenario IDs must be non-empty and unique")
    manifest = _load_checks(checks)
    by_check = {c["check_id"]:c for c in manifest}
    unique: dict[str,dict] = {}
    for obs in observations:
        oid = obs.get("observation_id")
        if not isinstance(oid,str) or not oid:
            raise EngineInputError("Every observation requires an observation_id")
        if oid in unique and canonical_hash(unique[oid]) != canonical_hash(obs):
            raise EngineInputError("An observation_id cannot identify two different records")
        unique[oid] = obs
    pinned = sorted(unique.values(),key=lambda o:o["observation_id"])
    input_hash = canonical_hash({"case":case,"observations":pinned,"checks":manifest,
                                 "engine_version":ENGINE_VERSION,"rule_version":rule_version,
                                 "runtime_versions":RUNTIME_VERSIONS})
    grouped: dict[str,list[dict]] = defaultdict(list)
    excluded = []
    rejected: dict[str,list[dict]] = defaultdict(list)
    for obs in pinned:
        reason = _gate(obs,case,as_of)
        if obs.get("check_id") not in by_check:
            reason = reason or "CHECK_NOT_IN_MANIFEST"
        if reason:
            safe_id = None if reason in ("PRIVATE_SCOPE_MISMATCH", "PROPERTY_SCOPE_MISMATCH", "PRIVATE_DATA_IN_PUBLIC_SCOPE") else obs["observation_id"]
            entry = {"observation_id":safe_id,"check_id":obs.get("check_id"),"reason":reason}
            excluded.append(entry)
            rejected[str(obs.get("check_id"))].append(entry)
        else:
            grouped[obs["check_id"]].append(obs)
    property_info = case.get("property", {})
    identity = property_info.get("identity_confirmed") is True and property_info.get("ambiguous") is not True
    if property_info.get("unit_required") is True and not property_info.get("unit_id"):
        identity = False
    finance = evaluate_finance(case.get("finance"),scenarios,requirements)
    finance_known = True
    if case.get("finance",{}).get("received_at"):
        finance_known = _date(case["finance"]["received_at"],"finance.received_at") <= as_of
        if not finance_known:
            finance = evaluate_finance(None)
            for key in ("repayment","baseline","settlement","buffer","exit"):
                finance[key]["reason"] = "NOT_KNOWN_AS_OF"
    check_results, findings, gaps, opportunities, used_ids, used_snapshots = [], [], [], [], set(), set()
    retained = True
    for check in manifest:
        cid = check["check_id"]
        applicable = True
        applicability_reason = None
        # Only explicit, versioned manifest rules can establish inapplicability.
        # A missing attribute never satisfies a formal exclusion.
        for attr, allowed in check.get("applicable_when", {}).items():
            if property_info.get(attr) is not None and property_info[attr] not in allowed:
                applicable = False
                applicability_reason = f"Manifest applicability excludes {attr}={property_info[attr]}"
        register_enabled = cid == "S002" and rule_version != "0.1.0"
        rows, resolution_error = _resolve(grouped.get(cid, []), unit_register=register_enabled)
        confidence = min((r["confidence"] for r in rows),key=lambda c:CONFIDENCE[c]) if rows else "Low"
        automatic = _finance_result(check,finance,case)
        if not applicable:
            evaluated = {**_na("FORMAL_APPLICABILITY_EXCLUSION"), "state":"NOT_APPLICABLE", "detail":applicability_reason}
        elif not identity and cid not in PRIVATE_CHECKS and not any(r.startswith("FN") for r in check["rule_ids"]):
            evaluated = _na("UNRESOLVED_PROPERTY_ID")
        elif resolution_error:
            evaluated = _na(resolution_error)
        elif automatic is not None:
            evaluated = automatic
            confidence = "Medium"
            # Financial arithmetic consumes the pinned case inputs. A generic
            # observation must not substitute for those mandatory numbers.
            rows = []
        elif register_enabled and any(row["payload"].get("kind") == "unit_register" for row in rows):
            evaluated = _unit_register(rows, case)
        elif rows:
            try:
                evaluated = _evaluate_payloads(rows,case,check,as_of)
            except (EngineInputError,FinanceInputError,InvalidOperation,ValueError,TypeError,KeyError) as exc:
                evaluated = _na("INVALID_STRUCTURED_INPUT",detail=str(exc))
        elif cid == "S001" and identity:
            evaluated = _assessed([_finding("ID01",0,"Property selection explicitly confirmed in the case",
                details={"property_id":case["property_id"],"basis":"Case assertion; authoritative ownership and unit facts are separate checks"},method="case_input")])
            confidence = "Medium"
        elif cid == "S064" and requirements:
            evaluated = _assessed([_finding("BUYER_BRIEF",0,"Buyer requirements and essential conditions recorded",
                details={"requirement_ids":sorted(requirement_ids),"scope":"Compatibility must be established by the relevant legal, cover, physical or finance rule"},method="case_input")])
            confidence = "Medium"
        else:
            reasons = sorted({r["reason"] for r in rejected.get(cid,[])})
            evaluated = _na(reasons[0] if reasons else "MISSING_REQUIRED_EVIDENCE")
        evidence_ids = sorted(r["observation_id"] for r in rows)
        snapshots = sorted({r["snapshot_id"] for r in rows})
        if evaluated["state"] == "ASSESSED" or evaluated.get("findings") or evaluated.get("opportunities"):
            used_ids.update(evidence_ids)
            used_snapshots.update(snapshots)
            retained &= all(r["rights"].get("retain_raw") is True for r in rows)
        extra_gaps = evaluated.get("extra_gaps", [])
        result = {"check_id":cid,"label":check["label"],"domain":check["domain"],
                  "required":check["required"],"critical":check["critical"],"public_check":check["public_check"],
                  "rule_ids":check["rule_ids"],"state":evaluated["state"],"priority":evaluated.get("priority"),
                  "reason":evaluated.get("reason"),"confidence":confidence,
                  "complete":evaluated["state"]=="ASSESSED" and not extra_gaps,
                  "evidence_ids":evidence_ids,"snapshot_ids":snapshots,
                  "details":evaluated.get("details",{}),"failures":evaluated.get("failures",[])}
        if evaluated["state"] == "NOT_ASSESSED" or extra_gaps:
            result["next_action"] = check.get("missing_evidence_handling", "Obtain and review the missing evidence for this check.")
        if evaluated.get("detail"):
            result["detail"] = evaluated["detail"]
        check_results.append(result)
        for f in evaluated.get("findings",[]):
            f = {**f,"check_id":cid,"domain":check["domain"],"confidence":confidence,
                 "evidence_ids":f.get("evidence_ids", evidence_ids),"snapshot_ids":snapshots}
            f["finding_id"] = "finding:" + canonical_hash(f).split(":")[1][:24]
            findings.append(f)
        for o in evaluated.get("opportunities",[]):
            o = {**o,"check_id":cid,"confidence":confidence,"evidence_ids":o.get("evidence_ids",evidence_ids),"snapshot_ids":snapshots}
            o["opportunity_id"] = "opportunity:" + canonical_hash(o).split(":")[1][:24]
            opportunities.append(o)
        if evaluated["state"] == "NOT_ASSESSED":
            reasons = [f.get("reason") for f in evaluated.get("failures",[])] or [evaluated.get("reason")]
            for reason in sorted(set(reasons)):
                gaps.append({"check_id":cid,"domain":check["domain"],"priority":3 if check["critical"] else 2 if check["required"] else 1,
                             "reason":reason,"summary":f"{check['label']}: evidence does not support a completed assessment",
                             "required":check["required"],"critical":check["critical"],"substantive_priority":None,
                             "evidence_ids":evidence_ids,
                             "next_action":check.get("missing_evidence_handling", "Obtain and review the missing evidence for this check.")})
        for gap in extra_gaps:
            gaps.append({**gap,"check_id":cid,"domain":check["domain"],"required":check["required"],
                         "critical":check["critical"],"substantive_priority":None,"evidence_ids":evidence_ids,
                         "next_action":check.get("missing_evidence_handling", "Obtain and review the missing evidence for this check.")})
    findings.sort(key=lambda f:(-f["priority"],f["check_id"],f["rule_id"],f["finding_id"]))
    gaps.sort(key=lambda g:(-g["priority"],g["check_id"],g["reason"]))
    opportunities.sort(key=lambda o:(o["check_id"],o["opportunity_id"]))
    full = _coverage(check_results)
    public = _coverage(check_results,public_only=True)
    domains = []
    for domain in sorted({c["domain"] for c in manifest}):
        df = [f for f in findings if f["domain"]==domain]
        dg = [g for g in gaps if g["domain"]==domain]
        domains.append({"domain":domain,"priority":max((f["priority"] for f in df),default=None),
                        "gap_priority":max((g["priority"] for g in dg),default=None),
                        "coverage":_coverage([r for r in check_results if r["domain"]==domain]),
                        "independent_factor_count":len({f["factor_id"] for f in df}),
                        "confidence":min((f["confidence"] for f in df),key=lambda c:CONFIDENCE[c]) if df else "Low"})
    review_count = len(case.get("reviews",[])) if isinstance(case.get("reviews",[]),list) else 0
    output = {
        "case_id":case["case_id"],"property_id":case["property_id"],"as_of":case["as_of"],
        "engine_version":ENGINE_VERSION,"rule_version":rule_version,"input_hash":input_hash,
        "runtime_versions":RUNTIME_VERSIONS,
        "manifest_hash":canonical_hash(manifest),
        "assessment_mode":case.get("assessment_mode","full_due_diligence"),
        "status":"COMPLETE" if full["complete"] else "INCOMPLETE",
        "priority":max((f["priority"] for f in findings),default=None),
        "gap_priority":max((g["priority"] for g in gaps),default=None),
        "findings":findings,"gaps":gaps,"opportunities":opportunities,"domains":domains,
        "coverage":{**full,"full_due_diligence":full,"public_screen":public},
        "financial_scenarios":finance,"check_results":check_results,
        "input_snapshot_ids":sorted(used_snapshots),"input_observation_ids":sorted(used_ids),
        "excluded_observations":sorted(excluded,key=lambda r:(str(r["check_id"]),str(r["observation_id"]),r["reason"])),
        "replay_level":"FULL_PINNED_INPUTS" if retained else "METADATA_ONLY_EVIDENCE_REPLAY",
        "review_state":{"review_records_supplied":review_count,"waivers_change_evidence_coverage":False},
        "limitations":[
            "Priorities 0–4 describe actions under versioned rules; they are not calibrated probabilities, loss estimates or a property valuation.",
            "Public screening cannot complete private inspections, legal advice, insurance quotations or buyer funding checks.",
            "Unimplemented signal models remain structured reviewed context or NOT_ASSESSED; the manifest contains the full required scope.",
            "Opportunities and correlated evidence do not subtract from adverse findings or multiply confidence.",
            "Case finances are explicit input assumptions; historical verification requires a dated received_at and pinned supporting evidence.",
            "Geometry describes the stated parcel or footprint and mapped mechanism; it does not establish floor-level loss or insurance availability.",
            "FULL_PINNED_INPUTS identifies reproducible supplied inputs, not independent verification that every upstream raw file is retained."
        ]
    }
    output["assessment_id"] = "assessment:" + canonical_hash(output).split(":")[1]
    # Return a clean JSON object, preserving coordinate-array order where present.
    return _canonical(output)


def evaluate_case(case: dict, observations: list[dict], checks: list[dict] | dict | None = None, *,
                  rule_version: str = RULE_VERSION) -> dict:
    """Public deterministic entry point; see ENGINE_CONTRACT.md for input kinds."""
    if rule_version not in SUPPORTED_RULE_VERSIONS:
        raise EngineInputError("Unsupported check rule version")
    with localcontext() as ctx:
        ctx.prec = 40
        return _evaluate_case(case, observations, checks, rule_version)


def apply_purchase_rules(case: dict, assessment: dict, decision_evidence: dict, *, rule_version: str | None = None) -> dict:
    """Bind a completed check assessment and its captured local evidence to one decision."""
    from .purchase_decision import PURCHASE_RULE_VERSION, purchase_decision

    if rule_version is None:
        rule_version = PURCHASE_RULE_VERSION
    evidence = {k: v for k, v in decision_evidence.items() if k != "assessment_id"}
    if any(evidence.get(k) != case[k] for k in ("case_id", "case_version", "as_of")):
        raise EngineInputError("Decision evidence does not match the case version and assessment date")
    with localcontext() as ctx:
        ctx.prec = 40
        decision = purchase_decision(case, assessment, evidence, rule_version=rule_version)
    # IDs point at the completed content. Omit both self-references from its digest.
    decision.pop("assessment_id", None)
    result = {k: v for k, v in assessment.items() if k != "assessment_id"}
    result.update(
        purchase_rule_version=rule_version,
        input_hash=canonical_hash({"check_input_hash": assessment["input_hash"], "decision_evidence": evidence,
                                   "purchase_rule_version": rule_version}),
        decision_evidence=evidence, purchase_decision=decision,
    )
    aid = "assessment:" + canonical_hash(result).split(":")[1]
    result["assessment_id"] = decision["assessment_id"] = aid
    return _canonical(result)
