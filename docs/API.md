# API, storage and private evidence

The application stores captured evidence and buyer cases locally, then evaluates an immutable version of the case against an immutable observation set. The HTTP service derives the tenant from a bearer key or the configured local dashboard identity. A property identifier never grants access to another buyer's finances, inspection documents or assessments.

## Run and authenticate

Use the root quick-start instructions to initialise the application and generate a local key. `riskengine.api.create_app(data_dir=None, api_keys=None)` creates the FastAPI application. The default data directory is `RISK_DATA_DIR`, or `runtime` when that variable is absent. The SQLite database is `riskengine.sqlite3` inside that directory.

The key configuration is a JSON object mapping **secret to tenant**, not the reverse:

```json
{
  "replace-with-a-random-secret-of-at-least-24-characters": "buyer-team-a"
}
```

The service reads `RISK_API_KEYS_JSON` first, then `api_keys.json` in the data directory. A mapping supplied explicitly to `create_app` takes precedence over both. Missing keys leave all private endpoints inaccessible; the application never switches to anonymous mode. Keys must contain at least 24 characters and should be generated randomly. The tenant identifier must use the documented identifier syntax; `_public` is reserved.

The desktop launcher uses `serve --desktop` with a single mapped tenant and the literal loopback address `127.0.0.1`. After binding the port, it opens a private file whose single-use code establishes an HttpOnly browser session. Browser access is checked against the listener and request origin. A separate `--sample-preview` switch grants local access to sample data only in the dedicated `runtime/buyer-preview` directory under tenant `demo`. Processes on the same computer can access this sample workspace. Keep private records in a desktop workspace. Plain `serve` retains bearer authentication.

API clients supply the key in the request header:

```http
Authorization: Bearer YOUR_LOCAL_KEY
```

`GET /health`, the static application shell and the OpenAPI documentation are public. All `/v1/` routes require authentication. A local deployment should bind to loopback. Remote deployment requires a separate reviewed TLS, identity, backup and operations configuration. This package implements and tests SQLite; it does not claim to provide a production PostgreSQL deployment.

The server returns `Cache-Control: no-store` for API responses, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`. Bearer secrets are not written to reports or application audit records. Keep local API key files, the database, source files and uploaded documents out of source control.

## Endpoints

| Method and route | Request | Response |
|---|---|---|
| `GET /health` | None | Service status, backend and whether authentication is configured |
| `GET /v1/sources` | Bearer header | `{ "sources": [...] }`; registry metadata with nested credentials redacted |
| `GET /v1/source-health` | Bearer header | `{ "sources": [...] }` for this tenant |
| `POST /v1/cases` | Direct case object; optional `expected_version` query | Captured case including server tenant and `case_version` |
| `GET /v1/cases` | Bearer header | `{ "cases": [...] }`, current versions owned by this tenant |
| `GET /v1/cases/{case_id}` | Optional `version` query | Current or specified immutable case version |
| `POST /v1/cases/{case_id}/observations` | Direct observation object | Private captured observation, with raw content redacted when necessary |
| `GET /v1/cases/{case_id}/observations` | Bearer header | `{ "observations": [...] }`, private case evidence plus eligible shared parcel evidence |
| `POST /v1/cases/{case_id}/collect` | Source identifier and bounded collection options | Pipeline collection result; unavailable sources remain explicit |
| `POST /v1/cases/{case_id}/assessments` | Empty body or `{}` | Deterministic assessment over a transactionally pinned input set |
| `GET /v1/cases/{case_id}/assessments` | Bearer header | `{ "assessments": [...] }` with immutable versions and display permission |
| `GET /v1/assessments/{assessment_id}` | Bearer header | Stored result if derived display is permitted |
| `GET /v1/assessments/{assessment_id}/report` | Bearer header | Standalone, printable HTML report |
| `POST /v1/assessments/{assessment_id}/reviews` | Review action and note | Separate immutable review record |
| `GET /v1/assessments/{assessment_id}/reviews` | Bearer header | `{ "reviews": [...] }` |
| `POST /v1/cases/{case_id}/documents` | Filename, MIME type, base64 bytes, optional explicit rights | Private document metadata and opaque document identifier |
| `GET /v1/cases/{case_id}/documents` | Bearer header | `{ "documents": [...] }`, without server file paths |
| `GET /v1/documents/{document_id}/download` | Bearer header | Scoped attachment download, subject to raw display rights |
| `GET /v1/cases/{case_id}/documents/{document_id}` | Bearer header | Equivalent download with an additional explicit case check |
| `GET /v1/jobs` | Optional `case_id` query | `{ "jobs": [...] }`, scoped to this tenant; lease tokens excluded |
| `GET /v1/jobs/{job_id}` | Bearer header | Scoped job state |
| `GET /v1/cases/{case_id}/audit` | Bearer header | `{ "events": [...] }`, with event type, identifier, detail and time |

The API accepts a maximum 8 MB request body. Document bytes have a separate 5 MB cap. These are conservative local proof limits, not a streaming large-file upload service. The lists are suitable for the local proof; pagination should be introduced before a large shared deployment.

Errors use an HTTP status and a JSON `detail`: 401 for absent/invalid authentication, 403 for an authenticated rights/scope violation, 404 when an object is absent from the caller's scope, 409 for immutable identifier conflicts, 413 for size limits, and 422 for invalid inputs. Guessed identifiers belonging to a different tenant return 404 without exposing the other tenant's case.

## A complete HTTP workflow

### 1. Capture the buyer case

Use `examples/case.json` for a fuller synthetic example. This minimal request creates a case but deliberately leaves many checks unassessed:

```json
{
  "case_id": "buyer-case-001",
  "property_id": "resolved-parcel-001",
  "as_of": "2026-11-21T12:00:00Z",
  "assessment_mode": "public_screen",
  "property": {
    "label": "Example house",
    "jurisdiction": "ACT",
    "property_type": "house",
    "identity_confirmed": false
  },
  "finance": {},
  "scenarios": [],
  "requirements": []
}
```

POST this directly to `/v1/cases`. The API assigns `owner_tenant_id` from the bearer key. A conflicting client-supplied owner is rejected. Repeating identical case content returns the same version. Changing content creates a new version and preserves every previous version. Supply `?expected_version=1` when editing a version that the client previously read; a concurrent edit then produces 409. Changing `property_id` requires a new case.

`as_of` is explicit and includes a timezone. Unknown financial inputs stay absent or null; do not enter zero to represent an unknown cost. A historical assessment must not silently use later private evidence. The HTTP observation route stamps `received_at` with the actual server receipt time; set the next case version's `as_of` after receipt when that input should be considered.

### 2. Collect public source records

POST to `/v1/cases/buyer-case-001/collect`:

```json
{
  "source_id": "CONFIGURED_SOURCE_ID",
  "max_records": 1000,
  "max_bytes": 20000000,
  "bounds": null
}
```

The configured source registry controls endpoints and adapter behaviour. A caller cannot insert an arbitrary URL in this request. A successful download is a captured source response, not a finding that the property is clear. The pipeline must establish parcel identity, licence permissions, spatial coverage, completeness and supported mappings before creating an assessed observation. Collection errors and partial results stay visible.

### 3. Submit reviewed private evidence

POST a supported observation envelope directly to the case observation route. See `BUILD_CONTRACT.md` and `ENGINE_CONTRACT.md` for the envelope and supported payload kinds. Four explicit boolean rights are required: `process`, `display_raw`, `display_derived`, and `retain_raw`.

The HTTP route always creates private case evidence. Requests for `visibility_scope: "public"` are rejected. Only trusted local ingestion may call `Store.add_observation(..., trusted_public=True)` to publish reusable parcel observations. Even that method rejects private owner/case fields and evidence labelled as an inspection, buyer input or private document. Trusted ingestion must not derive a shared observation from private buyer evidence.

An observation identifier is immutable. An identical retry is idempotent, including the original server receipt timestamp. Changed evidence needs a new identifier and explicit supersession information understood by the engine. The HTTP route never silently overwrites prior evidence.

### 4. Upload inspection or other documents

POST to `/v1/cases/buyer-case-001/documents`:

```json
{
  "filename": "building-inspection.txt",
  "media_type": "text/plain",
  "content_base64": "SW5zcGVjdGlvbiBub3Rlcy4=",
  "rights": {
    "process": true,
    "display_raw": true,
    "display_derived": true,
    "retain_raw": true
  }
}
```

The optional rights object defaults to true for each permission for a buyer's own uploaded document. Set restrictions explicitly when the buyer's licence requires them. Retention permission is required to accept bytes. Allowed MIME types are PDF, plain text, CSV, JSON, PNG, JPEG, WebP and TIFF. A MIME type is a claimed input format; this service does not parse or certify the file contents. Archives, HTML and executable files are not accepted through this route.

The response contains `document_id`, `snapshot_id`, byte hash, byte count, private tenant/case scope, and `extraction_status: "NOT_ASSESSED"`. The opaque identifier incorporates tenant and case identity, so the same file uploaded in two cases does not receive the same document identifier. Server-generated paths prevent a filename from choosing a filesystem destination.

Uploaded content is pending evidence. It does not create confirmed observations or change any rules, findings or scores. A reviewer must create a supported private observation with an appropriate source citation after interpreting the document. Any future AI extraction should write candidate data to a review queue and should remain outside the deterministic evaluation path.

Downloads verify tenant/case scope, current raw display rights and the stored byte hash. The API returns an attachment with `application/octet-stream` and `nosniff`. The HTML report escapes every untrusted string; document text cannot become HTML or executable instructions.

### 5. Evaluate and review

POST an empty body to `/v1/cases/buyer-case-001/assessments`. The service reads the current case version and observation set in one SQLite transaction, passes those values to `evaluate_case`, and stores the result together with the pinned input references. A concurrent case edit cannot change the captured inputs for that assessment. Required checks come from the engine's configured catalogue; callers cannot omit checks by passing an alternate manifest in the assessment request.

New assessments include `purchase_decision`, `purchase_rule_version` and `decision_evidence`. The decision includes the headline, next action, material issues, unresolved checks and contextual notes. Each item records its date, references and the evidence that could change the outcome. `GET /v1/cases/{case_id}/buyer-context?version={version}&assessment_id={assessment_id}` returns the saved source context for that decision. Older assessments retain their original contents. Reassessing through the dashboard or POST route creates a decision under the current rules.

An identical deterministic result reuses its assessment identifier. A changed result cannot replace content under an existing identifier. JSON and HTML read the same stored output. Evidence gaps, supported findings and opportunities remain separate. The HTML report does not describe review priority as loss probability or property growth.

POST a review to `/v1/assessments/ASSESSMENT_ID/reviews`:

```json
{
  "action": "waived",
  "note": "The buyer has acknowledged this unresolved gap and requested specialist advice.",
  "finding_id": "FINDING_ID_IF_APPLICABLE"
}
```

Allowed actions are `acknowledged`, `waived`, `investigate`, and `resolution_submitted`. A review is a new record. It never changes the original finding priority, closes an evidence gap, marks an unassessed check as assessed, or edits the original report. New validated evidence and a new assessment are needed to change the decision output.

## Rights and replay

| Permission | Enforced effect |
|---|---|
| `process` | The engine must not use the payload when permission is absent; replay also checks current processing rights |
| `display_raw` | Raw observation payloads and other non-provenance fields are removed from API reads; document download is denied |
| `display_derived` | Assessment JSON/HTML is denied if a captured input lacks derived display permission |
| `retain_raw` | Observation payload is removed on capture and marked `METADATA_ONLY`; document upload is rejected if retention is not permitted |

`Store.set_source_policy(tenant_id, source_id, policy)` lets a trusted operator restrict these permissions for future reads and evaluation. A restriction applies to existing captured evidence and reports. Setting a permission to true in a policy does not grant a permission absent from the evidence's original rights.

The collection pipeline applies current restrictions before calling an adapter, including retention restrictions that stop new raw capture. When derived display is not permitted, the public collection result withholds record counts, completeness counts and source error text; even a count from a parcel-specific hazard query could disclose a restricted result. Current policy revocation also hides previously stored source-health content and job results.

The first implementation conservatively denies the whole derived report when any captured observation lacks derived display rights. It does not attempt a partial report whose narrative may still disclose restricted inputs. This can block a report even when an affected observation would have been rejected by a rule; the ingestion mapping should keep rights-pending evidence as explicit capture metadata rather than promoting it into a usable observation.

Permission policy changes are not an automated retention deletion service. Restricted stored bytes remain an operator responsibility under the applicable retention schedule. Do not claim a raw archive has been erased merely because the API no longer displays it.

`Store.replay_inputs(tenant_id, assessment_id)` returns the original case version, exact original observation set and stored result. It validates the case, observation and assessment content hashes and checks current rights. Missing, altered or rights-changed inputs cause an explicit error. New case versions and newly ingested observations are never substituted during replay. This is **decision replay over captured observations**; it does not re-fetch historical APIs, recreate an upstream service, or guarantee identical software dependencies after an uncontrolled upgrade. Keep the engine version, rules and dependency lock with the assessment release.

## Storage and worker interfaces

`Store(path)` initialises the local schema. Tables cover versioned cases and current pointers, public/private observations, source snapshot metadata, private document metadata, immutable assessments, reviews, source health, source policies, durable jobs, audit events and migration version. Canonical JSON uses sorted keys and rejects non-finite numbers. Writes use transactions; every private lookup includes server-derived tenant identity, and case-level operations also verify case scope.

Common trusted application calls:

```python
store.save_case(tenant_id, case, expected_version=None)
store.get_case(tenant_id, case_id, version=None)
store.add_observation(tenant_id, case_id, observation, trusted_public=False)
store.list_observations(tenant_id, case_id, redact=True)

case, observations = store.assessment_inputs(tenant_id, case_id)
result = evaluate_case(case, observations)
store.save_assessment(
    tenant_id, case_id, result,
    observations=observations, case_version=case["case_version"],
)
visible_result = store.get_assessment(tenant_id, result["assessment_id"])
html = render_assessment(visible_result)

pinned_case, pinned_observations, stored_result = store.replay_inputs(
    tenant_id, result["assessment_id"]
)
```

`render_assessment(result) -> str` returns a self-contained HTML document. It is a presentation function, not an authorisation boundary. Call the permission-enforcing Store method before rendering through the API or CLI.

Snapshot metadata example:

```python
store.add_snapshot(tenant_id, case_id, {
    "snapshot_id": "snapshot-unique-capture-id",
    "source_id": "configured-source-id",
    "retrieved_at": "2026-11-21T12:00:00Z",
    "status": "SUCCESS",
    "raw_files": ["/private/runtime/snapshots/capture.json"],
    "rights": {
        "process": True, "display_raw": False,
        "display_derived": True, "retain_raw": True,
    },
    "completeness": {"complete": True},
})
```

Snapshot identifiers refer to immutable metadata. A later capture with changed metadata needs a distinct capture identifier, even if some upstream bytes are unchanged. `get_snapshot(..., require_raw=True)` performs a scoped raw display permission check. There is deliberately no unrestricted HTTP endpoint serving arbitrary raw snapshot filesystem paths.

The worker lifecycle is:

```python
job = store.enqueue_job(tenant_id, case_id, "collect", payload, idempotency_key, max_attempts=3)
leased = store.claim_job(worker_id, tenant_id=tenant_id, lease_seconds=60)
store.complete_job(tenant_id, leased["job_id"], leased["lease_token"], safe_result_metadata)
# On a retryable failure:
store.fail_job(tenant_id, leased["job_id"], leased["lease_token"], error_summary, retry_delay_seconds=5)
```

`claim_job` uses one write transaction so two workers cannot claim the same live lease. A worker crash leaves a durable lease; an expired lease can be reclaimed up to `max_attempts`. An expired final attempt becomes `FAILED`. Completion requires the current, unexpired lease token. An old worker cannot complete a job after another worker reclaimed it. An idempotency key is tenant-scoped and must always identify the same case, kind and payload.

Only trusted worker code uses `claim_job`; it is not an HTTP endpoint. The optional tenant filter allows a shared trusted worker to drain several tenants' jobs. HTTP job reads remain tenant-scoped and omit lease secrets. Store safe result metadata, not raw licensed records or server paths, in externally readable job results.

## Verification

Run:

```bash
python -m pytest tests/test_storage_security.py tests/test_api_security.py
```

The tests cover tenant/case isolation despite a shared property identifier, trusted-only public publication, scoped raw and derived rights, current policy revocation, immutable evidence and cases, precise pinned replay, concurrent edits, non-mutating waivers, server receipt times, idempotent ingestion, document scope and inert content, HTML escaping, credential redaction, request limits, durable recovery, bounded retries and competing worker claims.

These are executable application controls. SQLite does not provide independent row-level security against a person who can directly open the database file; protect the local account and data directory. A production implementation should add independent infrastructure controls and test them explicitly.
