"""SQLite persistence with immutable evidence and enforced tenant/case scope.

The Store is a trusted application boundary. HTTP callers never receive direct
SQL access or the ability to publish observations into the shared namespace.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any
import uuid
from decimal import Decimal, InvalidOperation


class StoreError(ValueError):
    pass


class NotFound(StoreError):
    pass


class Forbidden(StoreError):
    pass


class Conflict(StoreError):
    pass


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StoreError("Input must be finite JSON data") from exc


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def utc_now() -> str:
    return _stamp(datetime.now(timezone.utc))


def _time(value: str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str):
        raise StoreError("A timestamp must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StoreError("A timestamp must be a valid ISO 8601 string") from exc
    if parsed.tzinfo is None:
        raise StoreError("A timestamp must include its timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    # Fixed precision keeps SQLite lexical ordering equal to time ordering.
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_id(value: Any, label: str = "identifier") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
        raise StoreError(f"Invalid {label}; use 1–160 letters, digits, dots, colons, underscores or hyphens")
    return value


SURVIVAL_AMOUNTS = {
    "lost_income_monthly", "extra_expense_monthly", "repair_cost", "repair_overrun_pct", "rate_rise_bps",
    "sale_price_3y", "sale_price_5y", "selling_cost_pct", "selling_cost_fixed",
}
SURVIVAL_MONTHS = {"loss_months", "repair_month"}
UNDERWRITING_GROUPS = {
    "repair_quotes", "inspection_leads", "listing_periods", "guide_history", "market_dom", "market_inventory",
    "strata", "approved_layout", "registered_restrictions", "insurance_quote", "road", "layout", "competing_stock",
}
_LUMP_SUM_FIELDS = {"policy_confirmed", "benefit", "remaining_income_monthly", "ongoing_costs_monthly",
                    "one_off_costs", "horizon_months", "payout_delay_months"}
PROTECTION_FIELDS = {
    "property": {"scope", "written_confirmed", "annual_premium", "excess", "sum_insured", "rebuild_cost"},
    "illness": {"policy_confirmed", "waiting_days", "net_benefit_monthly", "lost_income_monthly"},
    "career": {"goal_monthly", "lost_income_monthly", "duration_months"},
    "disability": _LUMP_SUM_FIELDS, "death": _LUMP_SUM_FIELDS,
}


def _validate_underwriting(options):
    from .preoffer_costs import _instant

    inputs = options.get("underwriting", {})
    if not isinstance(inputs, dict) or set(inputs) - UNDERWRITING_GROUPS:
        raise StoreError("underwriting must contain recognised evidence groups")
    for group, records in inputs.items():
        rows = [records] if isinstance(records, dict) else records
        if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(r, dict) for r in rows):
            raise StoreError(f"{group} must contain up to 200 evidence records")
        for row in rows:
            if row.get("permission_confirmed") is not True:
                raise StoreError(f"Confirm permission to retain and use each {group} record")
            if row.get("source_id") is not None:
                validate_id(row["source_id"], "underwriting source ID")
            if not any(isinstance(row.get(k), str) and row[k].strip() for k in ("source_url", "source_ref")):
                raise StoreError(f"Each {group} record requires a source reference")
            if _instant(row.get("known_at")) is None:
                raise StoreError(f"Each {group} record requires a known_at date")


def _validate_preoffer(case):
    protection = case.get("buyer_protection", {})
    if not isinstance(protection, dict) or set(protection) - PROTECTION_FIELDS.keys():
        raise StoreError("buyer_protection must contain recognised protection sections")
    for name, section in protection.items():
        if not isinstance(section, dict) or set(section) - PROTECTION_FIELDS[name]:
            raise StoreError(f"Unknown or invalid {name} protection fields")
        for key, value in section.items():
            if value is None:
                continue
            if key == "scope":
                valid = value in ("owner", "strata")
            elif key in ("policy_confirmed", "written_confirmed"):
                valid = isinstance(value, bool)
            else:
                try:
                    number = Decimal(str(value))
                    valid = number.is_finite() and 0 <= number <= Decimal("1e15")
                    if key in ("waiting_days", "duration_months", "horizon_months", "payout_delay_months"):
                        limit = 3650 if key == "waiting_days" else 1200
                        valid = valid and number == number.to_integral_value() and number <= limit
                except InvalidOperation:
                    valid = False
            if not valid:
                raise StoreError(f"Invalid {name} protection value for {key}")
    if "preoffer" not in case:
        return
    options = case["preoffer"]
    if not isinstance(options, dict):
        raise StoreError("preoffer must be an object")
    _validate_underwriting(options)
    if "finance" in options and not isinstance(options["finance"], dict):
        raise StoreError("preoffer finance must be an object")
    for key in SURVIVAL_AMOUNTS | SURVIVAL_MONTHS:
        if options.get(key) is None:
            continue
        try:
            value = Decimal(str(options[key]))
            if not value.is_finite() or value < 0 or value > Decimal("1e15"):
                raise ValueError
            if key in SURVIVAL_MONTHS and (value != value.to_integral_value() or value > 1200 or (key == "repair_month" and value < 1)):
                raise ValueError
            if key == "selling_cost_pct" and value >= 100:
                raise ValueError
        except (ValueError, InvalidOperation):
            raise StoreError(f"Invalid first-year or exit scenario input: {key}") from None
    if "intended_use" in options and options["intended_use"] != "owner_occupier":
        raise StoreError("The pre-offer brief supports owner-occupier assessments")
    if "price_basis" in options and options["price_basis"] not in ("asking", "proposed_offer"):
        raise StoreError("Choose asking or proposed_offer for the price basis")
    for key in ("offer_price", "alternative_offer_price"):
        if options.get(key) is None:
            continue
        try:
            amount = Decimal(str(options[key]))
            if not amount.is_finite() or amount <= 0 or amount > Decimal("1e15"):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise StoreError(f"{key} must be a positive finite AUD amount") from None
    if "comparable_sales" in options and (not isinstance(options["comparable_sales"], list)
            or any(not isinstance(sale, dict) for sale in options["comparable_sales"])):
        raise StoreError("comparable_sales must be an array of reviewed sale records")
    sales = options.get("comparable_sales", [])
    if len(sales) > 200:
        raise StoreError("Use at most 200 comparable sales")
    for sale in sales:
        if sale.get("permission_confirmed") is not True:
            raise StoreError("Confirm permission to retain and use each comparable sale before saving it")
        if sale.get("source_id") is not None:
            validate_id(sale["source_id"], "sale source ID")


def comparable_sources(case):
    sales = (case.get("preoffer") or {}).get("comparable_sales", [])
    return ({"buyer_comparable_sales"} | {s["source_id"] for s in sales if s.get("source_id")}) if sales else set()


OBSERVATION_METADATA_FIELDS = {
    "observation_id", "check_id", "property_id", "source_id", "snapshot_id", "published_at",
    "effective_from", "effective_to", "received_at", "evidence_basis", "confidence", "visibility_scope",
    "owner_tenant_id", "case_scope_id", "rights", "quality", "replay_level", "supersedes_observation_id",
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS case_heads(
 tenant_id TEXT NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,case_id));
CREATE TABLE IF NOT EXISTS cases(
 tenant_id TEXT NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
 property_id TEXT NOT NULL, body TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,case_id,version));
CREATE TABLE IF NOT EXISTS observations(
 owner_scope TEXT NOT NULL, observation_id TEXT NOT NULL, case_id TEXT,
 property_id TEXT NOT NULL, source_id TEXT NOT NULL, snapshot_id TEXT,
 visibility TEXT NOT NULL CHECK(visibility IN('public','private')),
 body TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_scope,observation_id));
CREATE INDEX IF NOT EXISTS observation_case_idx ON observations(owner_scope,case_id);
CREATE INDEX IF NOT EXISTS observation_public_idx ON observations(visibility,property_id);
CREATE TABLE IF NOT EXISTS snapshots(
 tenant_id TEXT NOT NULL, case_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
 source_id TEXT NOT NULL, body TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,case_id,snapshot_id));
CREATE TABLE IF NOT EXISTS documents(
 tenant_id TEXT NOT NULL, document_id TEXT NOT NULL, case_id TEXT NOT NULL,
 body TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,document_id));
CREATE INDEX IF NOT EXISTS documents_case_idx ON documents(tenant_id,case_id);
CREATE TABLE IF NOT EXISTS assessments(
 tenant_id TEXT NOT NULL, assessment_id TEXT NOT NULL, case_id TEXT NOT NULL,
 case_version INTEGER NOT NULL, body TEXT NOT NULL, content_hash TEXT NOT NULL,
 observation_refs TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,assessment_id));
CREATE INDEX IF NOT EXISTS assessment_case_idx ON assessments(tenant_id,case_id);
CREATE TABLE IF NOT EXISTS reviews(
 tenant_id TEXT NOT NULL, review_id TEXT NOT NULL, assessment_id TEXT NOT NULL,
 body TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,review_id));
CREATE TABLE IF NOT EXISTS source_health(
 tenant_id TEXT NOT NULL, source_id TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,source_id));
CREATE TABLE IF NOT EXISTS source_policies(
 tenant_id TEXT NOT NULL, source_id TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,source_id));
CREATE TABLE IF NOT EXISTS jobs(
 tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, case_id TEXT NOT NULL,
 kind TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 max_attempts INTEGER NOT NULL, worker_id TEXT, lease_token TEXT, lease_until TEXT,
 available_at TEXT NOT NULL, result TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,job_id), UNIQUE(tenant_id,idempotency_key));
CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs(status,available_at,lease_until);
CREATE TABLE IF NOT EXISTS audit(
 audit_id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, case_id TEXT,
 event TEXT NOT NULL, object_id TEXT, detail TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR IGNORE INTO schema_version VALUES(1,?)", (utc_now(),))
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def _audit(self, conn, tenant_id, case_id, event, object_id, detail=None):
        conn.execute("INSERT INTO audit(tenant_id,case_id,event,object_id,detail,created_at) VALUES(?,?,?,?,?,?)",
                     (tenant_id, case_id, event, object_id, canonical_json(detail or {}), utc_now()))

    def _case(self, conn, tenant_id, case_id, version=None):
        if version is None:
            row = conn.execute("SELECT c.body FROM cases c JOIN case_heads h ON c.tenant_id=h.tenant_id AND c.case_id=h.case_id AND c.version=h.version WHERE c.tenant_id=? AND c.case_id=?", (tenant_id, case_id)).fetchone()
        else:
            row = conn.execute("SELECT body FROM cases WHERE tenant_id=? AND case_id=? AND version=?", (tenant_id, case_id, version)).fetchone()
        if not row:
            raise NotFound("Case not found")
        return json.loads(row["body"])

    def save_case(self, tenant_id, case, expected_version=None):
        from .buyer_underwriting import underwriting_sources
        validate_id(tenant_id, "tenant ID")
        if tenant_id == "_public":
            raise Forbidden("Reserved tenant identifier")
        if not isinstance(case, dict):
            raise StoreError("Case must be an object")
        case = json.loads(canonical_json(case))
        if case.get("sales_display_restricted") or case.get("underwriting_display_restricted"):
            raise Forbidden("An edit based on hidden evidence cannot replace the saved case")
        if case.get("owner_tenant_id") not in (None, tenant_id):
            raise Forbidden("Case owner does not match authenticated tenant")
        case_id = validate_id(case.get("case_id") or str(uuid.uuid4()), "case ID")
        property_id = validate_id(case.get("property_id"), "property ID")
        if not case.get("as_of"):
            raise StoreError("as_of is required for a reproducible assessment")
        _time(case["as_of"])
        _validate_preoffer(case)
        if "buyer_preferences" in case and not isinstance(case["buyer_preferences"], dict):
            raise StoreError("buyer_preferences must be an object")
        for name in ("property", "finance"):
            if name in case and case[name] is not None and not isinstance(case[name], dict):
                raise StoreError(f"{name} must be an object")
        for name in ("scenarios", "requirements"):
            if name in case and (not isinstance(case[name], list) or any(not isinstance(item, dict) for item in case[name])):
                raise StoreError(f"{name} must be an array of objects")
        case["owner_tenant_id"] = tenant_id
        case["case_id"] = case_id
        case.pop("case_version", None)
        case.pop("created_at", None)
        with self.transaction() as conn:
            for source_id in comparable_sources(case) | set(underwriting_sources(case)):
                policy = self._policy(conn, tenant_id, source_id)
                if any(policy.get(key) is False for key in ("process", "retain_raw", "display_raw", "display_derived")):
                    raise Forbidden("Current permissions restrict the submitted evidence")
            head = conn.execute("SELECT version FROM case_heads WHERE tenant_id=? AND case_id=?", (tenant_id, case_id)).fetchone()
            version = head["version"] if head else 0
            if expected_version is not None and expected_version != version:
                raise Conflict("Case version changed; refresh before updating")
            if head:
                previous = self._case(conn, tenant_id, case_id)
                previous.pop("case_version", None)
                if previous == case:
                    return {**case, "case_version": version}
                if previous["property_id"] != property_id:
                    raise Conflict("Create a new case to change the assessed property")
            version += 1
            body = {**case, "case_version": version}
            encoded = canonical_json(body)
            conn.execute("INSERT INTO cases VALUES(?,?,?,?,?,?,?)", (tenant_id, case_id, version, property_id, encoded, content_hash(body), utc_now()))
            conn.execute("INSERT INTO case_heads VALUES(?,?,?) ON CONFLICT(tenant_id,case_id) DO UPDATE SET version=excluded.version", (tenant_id, case_id, version))
            self._audit(conn, tenant_id, case_id, "case_version_created", case_id, {"version": version})
        return body

    def _case_display(self, conn, tenant_id, case):
        from .buyer_underwriting import underwriting_sources

        if any(self._policy(conn, tenant_id, source).get(key) is False for source in comparable_sources(case)
               for key in ("display_raw", "display_derived")):
            case = {**case, "preoffer": {**case["preoffer"], "comparable_sales": []}, "sales_display_restricted": True}
        if any(self._policy(conn, tenant_id, source).get(key) is False for source in underwriting_sources(case)
               for key in ("display_raw", "display_derived")):
            case = {**case, "preoffer": {**case["preoffer"], "underwriting": {}}, "underwriting_display_restricted": True}
        return case

    def get_case(self, tenant_id, case_id, version=None, *, for_display=False):
        with self.connection() as conn:
            case = self._case(conn, tenant_id, case_id, version)
            return self._case_display(conn, tenant_id, case) if for_display else case

    def list_cases(self, tenant_id):
        with self.connection() as conn:
            rows = conn.execute("SELECT c.body FROM cases c JOIN case_heads h ON c.tenant_id=h.tenant_id AND c.case_id=h.case_id AND c.version=h.version WHERE c.tenant_id=? ORDER BY c.case_id", (tenant_id,)).fetchall()
            return [self._case_display(conn, tenant_id, json.loads(r[0])) for r in rows]

    def add_observation(self, tenant_id, case_id, observation, trusted_public=False, server_received_at=False):
        if not isinstance(observation, dict):
            raise StoreError("Observation must be an object")
        obs = json.loads(canonical_json(observation))
        with self.transaction() as conn:
            case = self._case(conn, tenant_id, case_id)
            if obs.get("property_id") != case["property_id"]:
                raise StoreError("Observation property must match the resolved case property")
            obs_id = validate_id(obs.get("observation_id") or "obs-" + content_hash(obs), "observation ID")
            source_id = validate_id(obs.get("source_id"), "source ID")
            validate_id(obs.get("check_id"), "check ID")
            visibility = obs.get("visibility_scope", "private")
            if visibility not in ("public", "private", "tenant", "case"):
                raise StoreError("Unsupported visibility scope")
            if visibility == "public":
                if not trusted_public:
                    raise Forbidden("Shared observations can only be published by trusted ingestion")
                if obs.get("owner_tenant_id") or obs.get("case_scope_id"):
                    raise StoreError("Shared evidence cannot contain a private owner or case scope")
                if obs.get("evidence_basis") in ("inspection", "buyer_input", "private_document"):
                    raise Forbidden("Private evidence cannot be promoted to shared observations")
                owner_scope = "_public"
                observation_case = None
                obs.update(owner_tenant_id=None, case_scope_id=None, visibility_scope="public")
            else:
                if obs.get("owner_tenant_id") not in (None, tenant_id) or obs.get("case_scope_id") not in (None, case_id):
                    raise Forbidden("Observation owner/case does not match authenticated case")
                owner_scope = tenant_id
                observation_case = case_id
                visibility = "private"
                obs.update(owner_tenant_id=tenant_id, case_scope_id=case_id, visibility_scope="private")
            obs["observation_id"] = obs_id
            existing = conn.execute("SELECT content_hash,body,case_id FROM observations WHERE owner_scope=? AND observation_id=?", (owner_scope, obs_id)).fetchone()
            if visibility == "private":
                prior = json.loads(existing["body"]) if existing and existing["case_id"] == observation_case else {}
                if server_received_at:
                    obs["received_at"] = prior.get("received_at", utc_now())
                else:
                    obs.setdefault("received_at", prior.get("received_at", utc_now()))
                _time(obs["received_at"])
            rights = obs.get("rights")
            if not isinstance(rights, dict) or any(not isinstance(rights.get(k), bool) for k in ("process", "display_raw", "display_derived", "retain_raw")):
                raise StoreError("Explicit boolean process/display_raw/display_derived/retain_raw rights are required")
            if not rights["retain_raw"]:
                # Keep provenance, not arbitrary extra fields carrying raw text.
                obs = {k: v for k, v in obs.items() if k in OBSERVATION_METADATA_FIELDS}
                obs["replay_level"] = "METADATA_ONLY"
            encoded = canonical_json(obs)
            digest = content_hash(obs)
            if existing:
                if existing["content_hash"] != digest or existing["case_id"] != observation_case:
                    raise Conflict("Observation IDs are immutable; create a new observation and explicit supersession")
                return json.loads(existing["body"])
            conn.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)", (owner_scope, obs_id, observation_case, case["property_id"], source_id, obs.get("snapshot_id"), visibility, encoded, digest, utc_now()))
            self._audit(conn, tenant_id, case_id, "observation_created", obs_id, {"source_id": source_id, "visibility": visibility})
        return obs

    def _observation_rows(self, conn, tenant_id, case_id, case):
        return conn.execute("SELECT * FROM observations WHERE (owner_scope=? AND case_id=?) OR (visibility='public' AND property_id=?) ORDER BY owner_scope,observation_id", (tenant_id, case_id, case["property_id"])).fetchall()

    def _policy(self, conn, tenant_id, source_id):
        row = conn.execute("SELECT body FROM source_policies WHERE tenant_id=? AND source_id=?", (tenant_id, source_id)).fetchone()
        return json.loads(row[0]) if row else {}

    def _apply_policy(self, conn, tenant_id, obs):
        obs = json.loads(canonical_json(obs))
        policy = self._policy(conn, tenant_id, obs.get("source_id"))
        rights = obs.setdefault("rights", {})
        for key in ("process", "display_raw", "display_derived", "retain_raw"):
            if policy.get(key) is False:
                rights[key] = False
        return obs

    @staticmethod
    def redact_observation(obs):
        """Return provenance only when raw display permission is absent."""
        if obs.get("rights", {}).get("display_raw") is True:
            return obs
        return {**{k: v for k, v in obs.items() if k in OBSERVATION_METADATA_FIELDS}, "raw_redacted": True}

    def list_observations(self, tenant_id, case_id, redact=False):
        with self.connection() as conn:
            case = self._case(conn, tenant_id, case_id)
            records = [self._apply_policy(conn, tenant_id, json.loads(r["body"])) for r in self._observation_rows(conn, tenant_id, case_id, case)]
        if redact:
            records = [self.redact_observation(obs) for obs in records]
        return records

    def assessment_inputs(self, tenant_id, case_id, version=None):
        # One SQLite read transaction freezes the case and observation set.
        with self.connection() as conn:
            conn.execute("BEGIN")
            try:
                case = self._case(conn, tenant_id, case_id, version)
                observations = [self._apply_policy(conn, tenant_id, json.loads(r["body"])) for r in self._observation_rows(conn, tenant_id, case_id, case)]
                conn.execute("COMMIT")
                return case, observations
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def save_assessment(self, tenant_id, case_id, result, observations=None, case_version=None):
        body = json.loads(canonical_json(result))
        aid = validate_id(body.get("assessment_id"), "assessment ID")
        with self.transaction() as conn:
            self._check_decision_permissions(conn, tenant_id, body, ("process", "retain_raw", "display_derived"))
            version = case_version or body.get("case_version")
            case = self._case(conn, tenant_id, case_id, version)
            if body.get("case_id") != case_id or body.get("property_id") != case["property_id"]:
                raise StoreError("Assessment does not match the requested case/property")
            existing = conn.execute("SELECT content_hash,body FROM assessments WHERE tenant_id=? AND assessment_id=?", (tenant_id, aid)).fetchone()
            digest = content_hash(body)
            if existing:
                if existing["content_hash"] != digest:
                    raise Conflict("Assessment ID is immutable")
                return json.loads(existing["body"])
            obs = observations if observations is not None else [json.loads(r["body"]) for r in self._observation_rows(conn, tenant_id, case_id, case)]
            refs = []
            for record in obs:
                public = record.get("visibility_scope") == "public"
                if not public and (record.get("owner_tenant_id") != tenant_id or record.get("case_scope_id") != case_id):
                    raise Forbidden("Assessment inputs contain private evidence from another scope")
                stored = conn.execute("SELECT content_hash,case_id,property_id,visibility FROM observations WHERE owner_scope=? AND observation_id=?", ("_public" if public else tenant_id, record["observation_id"])).fetchone()
                if not stored or stored["property_id"] != case["property_id"] or (not public and stored["case_id"] != case_id):
                    raise Forbidden("Assessment input is not captured evidence for this case")
                refs.append({"owner_scope": "_public" if public else tenant_id,
                             "observation_id": record["observation_id"], "source_id": record["source_id"],
                             "rights": record.get("rights", {}), "stored_content_hash": stored["content_hash"],
                             "input_content_hash": content_hash(record)})
            refs.sort(key=lambda r: (r["owner_scope"], r["observation_id"]))
            conn.execute("INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?)", (tenant_id, aid, case_id, case["case_version"], canonical_json(body), digest, canonical_json(refs), utc_now()))
            self._audit(conn, tenant_id, case_id, "assessment_created", aid, {"case_version": case["case_version"], "observation_count": len(refs)})
        return body

    def restricted_decision_sources(self, tenant_id, sources, *, raw=False):
        with self.connection() as conn:
            policies = [(source_id, self._policy(conn, tenant_id, source_id)) for source_id in sources]
            rights = ("process", "retain_raw", "display_derived") + (("display_raw",) if raw else ())
            return {source_id for source_id, policy in policies
                    if any(policy.get(key) is False for key in rights)}

    def _check_decision_permissions(self, conn, tenant_id, result, required):
        evidence = result.get("decision_evidence", {})
        if not isinstance(evidence, dict) or ("purchase_decision" in result and "source_ids" not in evidence):
            raise Conflict("The original purchase decision evidence is unavailable")
        for source_id in evidence.get("source_ids", []):
            policy = self._policy(conn, tenant_id, source_id)
            if any(policy.get(key) is False for key in required):
                raise Forbidden("Current permissions restrict this assessment's captured local evidence")
        for source_id in (result.get("preoffer_capture") or {}).get("raw_source_ids", []):
            if self._policy(conn, tenant_id, source_id).get("display_raw") is False:
                raise Forbidden("Current permissions restrict this assessment's captured source records")

    def _assessment(self, conn, tenant_id, assessment_id, enforce_display=True):
        row = conn.execute("SELECT * FROM assessments WHERE tenant_id=? AND assessment_id=?", (tenant_id, assessment_id)).fetchone()
        if not row:
            raise NotFound("Assessment not found")
        self._case(conn, tenant_id, row["case_id"], row["case_version"])
        if enforce_display:
            self._check_decision_permissions(conn, tenant_id, json.loads(row["body"]), ("display_derived",))
            for ref in json.loads(row["observation_refs"]):
                if ref["rights"].get("display_derived") is not True or self._policy(conn, tenant_id, ref["source_id"]).get("display_derived") is False:
                    raise Forbidden("Derived display permission is unavailable for an assessment input")
        return row

    def get_assessment(self, tenant_id, assessment_id, enforce_display=True):
        with self.connection() as conn:
            return json.loads(self._assessment(conn, tenant_id, assessment_id, enforce_display)["body"])

    def replay_inputs(self, tenant_id, assessment_id):
        """Reconstruct precisely the captured inputs, or fail without guessing.

        This replays the deterministic decision over captured observations. It
        does not re-fetch upstream services or prove an external file remains
        unchanged. Current process/display/retention restrictions still apply.
        """
        with self.connection() as conn:
            conn.execute("BEGIN")
            try:
                row = self._assessment(conn, tenant_id, assessment_id)
                result = json.loads(row["body"])
                self._check_decision_permissions(conn, tenant_id, result, ("process", "retain_raw"))
                if content_hash(result) != row["content_hash"]:
                    raise Conflict("Stored assessment content hash no longer matches")
                case_row = conn.execute("SELECT body,content_hash FROM cases WHERE tenant_id=? AND case_id=? AND version=?", (tenant_id, row["case_id"], row["case_version"])).fetchone()
                case = json.loads(case_row["body"])
                if content_hash(case) != case_row["content_hash"]:
                    raise Conflict("Pinned case content hash no longer matches")
                observations = []
                for ref in json.loads(row["observation_refs"]):
                    if ref["owner_scope"] not in (tenant_id, "_public"):
                        raise Forbidden("Pinned observation belongs to another tenant")
                    evidence = conn.execute("SELECT * FROM observations WHERE owner_scope=? AND observation_id=?", (ref["owner_scope"], ref["observation_id"])).fetchone()
                    if not evidence or evidence["property_id"] != case["property_id"] or (evidence["visibility"] != "public" and evidence["case_id"] != row["case_id"]):
                        raise Conflict("Pinned observation is missing or no longer matches the case")
                    observation = json.loads(evidence["body"])
                    if content_hash(observation) != evidence["content_hash"] or evidence["content_hash"] != ref.get("stored_content_hash"):
                        raise Conflict("Pinned observation content hash no longer matches")
                    permitted = self._apply_policy(conn, tenant_id, observation)
                    if permitted.get("rights", {}).get("process") is not True or permitted.get("rights", {}).get("retain_raw") is not True:
                        raise Forbidden("Current processing/retention rights do not permit faithful replay")
                    if content_hash(permitted) != ref.get("input_content_hash"):
                        raise Conflict("Input rights or content changed; original assessment inputs cannot be reconstructed")
                    observations.append(permitted)
                conn.execute("COMMIT")
                return case, observations, result
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def list_assessments(self, tenant_id, case_id):
        with self.connection() as conn:
            self._case(conn, tenant_id, case_id)
            rows = conn.execute("SELECT assessment_id,case_version,created_at,body FROM assessments WHERE tenant_id=? AND case_id=? ORDER BY created_at,assessment_id", (tenant_id, case_id)).fetchall()
            result = []
            for row in rows:
                item = {"assessment_id": row["assessment_id"], "case_version": row["case_version"], "created_at": row["created_at"]}
                try:
                    self._assessment(conn, tenant_id, row["assessment_id"])
                    body = json.loads(row["body"])
                    item.update(status=body.get("status"), coverage=body.get("coverage"), display_allowed=True)
                except Forbidden:
                    item["display_allowed"] = False
                result.append(item)
            return result

    def add_review(self, tenant_id, assessment_id, action, note, finding_id=None):
        if action not in ("acknowledged", "waived", "investigate", "resolution_submitted"):
            raise StoreError("Unsupported review action")
        if not isinstance(note, str) or not note.strip() or len(note) > 5000:
            raise StoreError("A review note of 1–5000 characters is required")
        with self.transaction() as conn:
            assessment = self._assessment(conn, tenant_id, assessment_id)
            review = {"review_id": str(uuid.uuid4()), "assessment_id": assessment_id,
                      "action": action, "note": note, "finding_id": finding_id,
                      "created_at": utc_now(), "assessment_unchanged": True}
            conn.execute("INSERT INTO reviews VALUES(?,?,?,?,?)", (tenant_id, review["review_id"], assessment_id, canonical_json(review), review["created_at"]))
            self._audit(conn, tenant_id, assessment["case_id"], "review_added", review["review_id"], {"action": action})
            return review

    def list_reviews(self, tenant_id, assessment_id):
        with self.connection() as conn:
            self._assessment(conn, tenant_id, assessment_id)
            return [json.loads(r[0]) for r in conn.execute("SELECT body FROM reviews WHERE tenant_id=? AND assessment_id=? ORDER BY created_at,review_id", (tenant_id, assessment_id))]

    def set_source_policy(self, tenant_id, source_id, policy):
        if any(k not in ("process", "display_raw", "display_derived", "retain_raw") or not isinstance(v, bool) for k, v in policy.items()):
            raise StoreError("Source policy supports explicit boolean rights only")
        with self.transaction() as conn:
            conn.execute("INSERT INTO source_policies VALUES(?,?,?,?) ON CONFLICT(tenant_id,source_id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at", (tenant_id, source_id, canonical_json(policy), utc_now()))
            self._audit(conn, tenant_id, None, "source_policy_changed", source_id, policy)

    def get_source_policy(self, tenant_id, source_id):
        with self.connection() as conn:
            return self._policy(conn, tenant_id, source_id)

    def add_snapshot(self, tenant_id, case_id, snapshot):
        data = json.loads(canonical_json(snapshot))
        if data.get("owner_tenant_id") not in (None, tenant_id) or data.get("case_scope_id") not in (None, case_id):
            raise Forbidden("Snapshot owner/case does not match authenticated case")
        sid = validate_id(data.get("snapshot_id") or "snapshot-" + content_hash(data), "snapshot ID")
        source_id = validate_id(data.get("source_id"), "source ID")
        data.update(snapshot_id=sid, owner_tenant_id=tenant_id, case_scope_id=case_id)
        digest = content_hash(data)
        with self.transaction() as conn:
            self._case(conn, tenant_id, case_id)
            existing = conn.execute("SELECT body,content_hash FROM snapshots WHERE tenant_id=? AND case_id=? AND snapshot_id=?", (tenant_id, case_id, sid)).fetchone()
            if existing:
                if existing["content_hash"] != digest:
                    raise Conflict("Snapshot ID is immutable")
                return json.loads(existing["body"])
            conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?)", (tenant_id, case_id, sid, source_id, canonical_json(data), digest, utc_now()))
            self._audit(conn, tenant_id, case_id, "snapshot_created", sid, {"source_id": source_id})
        return data

    def add_document(self, tenant_id, case_id, document):
        """Capture immutable private metadata; document bytes are never rules."""
        data = json.loads(canonical_json(document))
        document_id = validate_id(data.get("document_id"), "document ID")
        if data.get("owner_tenant_id") not in (None, tenant_id) or data.get("case_scope_id") not in (None, case_id):
            raise Forbidden("Document owner/case does not match authenticated case")
        data.update(owner_tenant_id=tenant_id, case_scope_id=case_id, visibility_scope="private")
        rights = data.get("rights", {})
        if any(not isinstance(rights.get(k), bool) for k in ("process", "display_raw", "display_derived", "retain_raw")) or not rights["retain_raw"]:
            raise StoreError("Document capture requires explicit rights and raw retention permission")
        digest = content_hash(data)
        with self.transaction() as conn:
            self._case(conn, tenant_id, case_id)
            existing = conn.execute("SELECT body,content_hash,case_id FROM documents WHERE tenant_id=? AND document_id=?", (tenant_id, document_id)).fetchone()
            if existing:
                if existing["content_hash"] != digest or existing["case_id"] != case_id:
                    raise Conflict("Document metadata is immutable")
                return json.loads(existing["body"])
            conn.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", (tenant_id, document_id, case_id, canonical_json(data), digest, utc_now()))
            self._audit(conn, tenant_id, case_id, "document_captured", document_id, {"extraction_status": "NOT_ASSESSED"})
        return data

    def get_document(self, tenant_id, document_id, case_id=None, require_raw=False):
        with self.connection() as conn:
            row = conn.execute("SELECT body,case_id FROM documents WHERE tenant_id=? AND document_id=?", (tenant_id, document_id)).fetchone()
            if not row or case_id is not None and row["case_id"] != case_id:
                raise NotFound("Document not found")
            self._case(conn, tenant_id, row["case_id"])
            data = json.loads(row["body"])
            if require_raw and (data["rights"].get("display_raw") is not True or self._policy(conn, tenant_id, data["source_id"]).get("display_raw") is False):
                raise Forbidden("Raw display permission is unavailable")
            return data

    def list_documents(self, tenant_id, case_id):
        with self.connection() as conn:
            self._case(conn, tenant_id, case_id)
            return [json.loads(r[0]) for r in conn.execute("SELECT body FROM documents WHERE tenant_id=? AND case_id=? ORDER BY created_at,document_id", (tenant_id, case_id))]

    def get_snapshot(self, tenant_id, case_id, snapshot_id, require_raw=False):
        with self.connection() as conn:
            self._case(conn, tenant_id, case_id)
            row = conn.execute("SELECT body FROM snapshots WHERE tenant_id=? AND case_id=? AND snapshot_id=?", (tenant_id, case_id, snapshot_id)).fetchone()
            if not row:
                raise NotFound("Snapshot not found")
            data = json.loads(row[0])
            if require_raw and (data.get("rights", {}).get("display_raw") is not True or self._policy(conn, tenant_id, data["source_id"]).get("display_raw") is False):
                raise Forbidden("Raw display permission is unavailable")
            return data

    def list_snapshots(self, tenant_id, case_id):
        with self.connection() as conn:
            self._case(conn, tenant_id, case_id)
            return [json.loads(r[0]) for r in conn.execute("SELECT body FROM snapshots WHERE tenant_id=? AND case_id=? ORDER BY created_at,snapshot_id", (tenant_id, case_id))]

    def update_source_health(self, tenant_id, source_id, health):
        with self.transaction() as conn:
            conn.execute("INSERT INTO source_health VALUES(?,?,?,?) ON CONFLICT(tenant_id,source_id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at", (tenant_id, source_id, canonical_json(health), utc_now()))

    def get_source_health(self, tenant_id):
        with self.connection() as conn:
            result = []
            for row in conn.execute("SELECT source_id,body,updated_at FROM source_health WHERE tenant_id=? ORDER BY source_id", (tenant_id,)):
                health = json.loads(row[1])
                if self._policy(conn, tenant_id, row[0]).get("display_derived") is False:
                    health = {"status": "DISPLAY_RESTRICTED", "reason": "CURRENT_SOURCE_POLICY"}
                result.append({"source_id": row[0], "health": health, "updated_at": row[2]})
            return result

    def enqueue_job(self, tenant_id, case_id, kind, payload, idempotency_key, max_attempts=3, now=None):
        if not 1 <= max_attempts <= 10:
            raise StoreError("max_attempts must be between 1 and 10")
        validate_id(idempotency_key, "idempotency key")
        instant = _stamp(_time(now))
        digest = content_hash({"case_id": case_id, "kind": kind, "payload": payload})
        with self.transaction() as conn:
            self._case(conn, tenant_id, case_id)
            row = conn.execute("SELECT * FROM jobs WHERE tenant_id=? AND idempotency_key=?", (tenant_id, idempotency_key)).fetchone()
            if row:
                if row["payload_hash"] != digest:
                    raise Conflict("Idempotency key already used for a different job")
                return self._job_dict(row)
            job_id = str(uuid.uuid4())
            conn.execute("INSERT INTO jobs(tenant_id,job_id,case_id,kind,idempotency_key,payload_hash,payload,status,max_attempts,available_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?,?)", (tenant_id, job_id, case_id, kind, idempotency_key, digest, canonical_json(payload), max_attempts, instant, instant, instant))
            self._audit(conn, tenant_id, case_id, "job_enqueued", job_id, {"kind": kind})
            return self._job_dict(conn.execute("SELECT * FROM jobs WHERE tenant_id=? AND job_id=?", (tenant_id, job_id)).fetchone())

    def _job_dict(self, row, public=False):
        d = dict(row)
        for key in ("payload", "result"):
            if d.get(key) is not None:
                d[key] = json.loads(d[key])
        if public:
            d.pop("lease_token", None)
            d.pop("payload_hash", None)
        return d

    def _visible_job(self, conn, tenant_id, row):
        job = self._job_dict(row, public=True)
        source_id = job.get("payload", {}).get("source_id") if isinstance(job.get("payload"), dict) else None
        if source_id and self._policy(conn, tenant_id, source_id).get("display_derived") is False:
            job["result"] = {"source_id": source_id, "status": "DISPLAY_RESTRICTED", "reason": "CURRENT_SOURCE_POLICY"}
            if job["last_error"]:
                job["last_error"] = "WITHHELD_BY_SOURCE_POLICY"
        return job

    def claim_job(self, worker_id, tenant_id=None, lease_seconds=60, now=None):
        if not 1 <= lease_seconds <= 3600:
            raise StoreError("lease_seconds must be between 1 and 3600")
        instant = _time(now)
        stamp = _stamp(instant)
        with self.transaction() as conn:
            # A dead worker on its final attempt must not leave an immortal job.
            conn.execute("UPDATE jobs SET status='FAILED',last_error='Lease expired after maximum attempts',updated_at=? WHERE status='RUNNING' AND lease_until<=? AND attempts>=max_attempts", (stamp, stamp))
            sql = "SELECT * FROM jobs WHERE attempts<max_attempts AND ((status='PENDING' AND available_at<=?) OR (status='RUNNING' AND lease_until<=?))"
            args = [stamp, stamp]
            if tenant_id is not None:
                sql += " AND tenant_id=?"
                args.append(tenant_id)
            row = conn.execute(sql + " ORDER BY created_at,job_id LIMIT 1", args).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(24)
            conn.execute("UPDATE jobs SET status='RUNNING',attempts=attempts+1,worker_id=?,lease_token=?,lease_until=?,updated_at=? WHERE tenant_id=? AND job_id=?", (worker_id, token, _stamp(instant + timedelta(seconds=lease_seconds)), stamp, row["tenant_id"], row["job_id"]))
            return self._job_dict(conn.execute("SELECT * FROM jobs WHERE tenant_id=? AND job_id=?", (row["tenant_id"], row["job_id"])).fetchone())

    def _leased(self, conn, tenant_id, job_id, token, now):
        row = conn.execute("SELECT * FROM jobs WHERE tenant_id=? AND job_id=?", (tenant_id, job_id)).fetchone()
        if not row:
            raise NotFound("Job not found")
        if row["status"] != "RUNNING" or not secrets.compare_digest(row["lease_token"] or "", token or "") or _time(row["lease_until"]) <= _time(now):
            raise Conflict("Job lease is expired or no longer owned by this worker")
        return row

    def complete_job(self, tenant_id, job_id, lease_token, result, now=None):
        stamp = _stamp(_time(now))
        with self.transaction() as conn:
            row = self._leased(conn, tenant_id, job_id, lease_token, stamp)
            conn.execute("UPDATE jobs SET status='SUCCEEDED',result=?,lease_until=NULL,lease_token=NULL,updated_at=? WHERE tenant_id=? AND job_id=?", (canonical_json(result), stamp, tenant_id, job_id))
            self._audit(conn, tenant_id, row["case_id"], "job_succeeded", job_id)

    def fail_job(self, tenant_id, job_id, lease_token, error, retry_delay_seconds=5, now=None):
        instant = _time(now)
        if not 0 <= retry_delay_seconds <= 3600:
            raise StoreError("Invalid retry delay")
        with self.transaction() as conn:
            row = self._leased(conn, tenant_id, job_id, lease_token, _stamp(instant))
            status = "PENDING" if row["attempts"] < row["max_attempts"] else "FAILED"
            conn.execute("UPDATE jobs SET status=?,last_error=?,available_at=?,lease_until=NULL,lease_token=NULL,updated_at=? WHERE tenant_id=? AND job_id=?", (status, str(error)[:1000], _stamp(instant + timedelta(seconds=retry_delay_seconds)), _stamp(instant), tenant_id, job_id))

    def get_job(self, tenant_id, job_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE tenant_id=? AND job_id=?", (tenant_id, job_id)).fetchone()
            if not row:
                raise NotFound("Job not found")
            return self._visible_job(conn, tenant_id, row)

    def list_jobs(self, tenant_id, case_id=None):
        with self.connection() as conn:
            if case_id is not None:
                self._case(conn, tenant_id, case_id)
            sql = "SELECT * FROM jobs WHERE tenant_id=?"
            args = [tenant_id]
            if case_id is not None:
                sql += " AND case_id=?"
                args.append(case_id)
            return [self._visible_job(conn, tenant_id, r) for r in conn.execute(sql + " ORDER BY created_at,job_id", args)]

    def audit_events(self, tenant_id, case_id=None):
        with self.connection() as conn:
            sql = "SELECT event,object_id,detail,created_at FROM audit WHERE tenant_id=?"
            args = [tenant_id]
            if case_id is not None:
                self._case(conn, tenant_id, case_id)
                sql += " AND case_id=?"
                args.append(case_id)
            return [{"event": r[0], "object_id": r[1], "detail": json.loads(r[2]), "created_at": r[3]} for r in conn.execute(sql + " ORDER BY audit_id", args)]
