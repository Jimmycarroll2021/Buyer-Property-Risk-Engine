-- Actual SQLite schema used by the local store. PostgreSQL/PostGIS is a future backend.

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
