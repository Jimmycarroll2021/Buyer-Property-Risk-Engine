# Build contract

Runnable local-first Python 3.12 application. Package `riskengine` under `src/`.
Runtime: FastAPI, SQLite (stdlib sqlite3), Shapely, pyproj, httpx, openpyxl.
No LLM is called during deterministic assessment. Decimal arithmetic for finance.

## Shared module boundaries

- `riskengine.engine.evaluate_case(case: dict, observations: list[dict], checks: list[dict] | None = None) -> dict`
- `riskengine.engine.canonical_hash(value) -> str`
- `riskengine.finance` and `riskengine.spatial` are owned by engine implementer.
- `riskengine.ingestion.load_registry(path=None) -> list[dict]`
- `riskengine.ingestion.collect(source: dict, output_dir: str|Path, *, bounds: dict|None=None, max_records: int=1000, max_bytes: int=20000000) -> dict`
  Return source_id, snapshot_id, status, retrieved_at, raw_files, records, completeness, coverage, errors, schema. No database side effects; never call a user-supplied URL outside the configured source record.
- `riskengine.storage.Store(path)` owns persisted sources/snapshots/cases/observations/assessments/jobs/reviews/audit. JSON values stored canonically; every private read scoped by tenant and case.
- `riskengine.api.create_app(data_dir=None, api_keys=None)` returns FastAPI app. `api_keys` maps bearer secret to tenant ID; required for private routes. No anonymous fallback.
- Root owns CLI, web UI, setup, config compilation, live orchestration/evidence mapping, docs/drawings, examples and integration.

## Case input

```json
{
  "case_id": "case-demo", "property_id": "synthetic-house-1", "owner_tenant_id": "demo",
  "as_of": "2026-11-21T00:00:00Z", "assessment_mode": "public_screen",
  "property": {"label": "Synthetic demonstration house", "jurisdiction": "ACT", "property_type": "house", "identity_confirmed": true},
  "finance": {
    "principal": "720000", "annual_rate_decimal": "0.06", "term_months": 360,
    "income_monthly": "11000", "living_monthly": "4800", "other_debt_monthly": "0",
    "property_costs_monthly": "900", "cash_after_settlement": "45000", "protected_reserve": "15000",
    "purchase_price": "900000", "loan_funds": "720000", "cash_allocated": "215000",
    "acquisition_costs": "25000", "immediate_works": "10000"
  },
  "scenarios": [{"scenario_id":"combined_12m", "duration_months":12, "rate_delta_bps":200, "income_factor":"0.70", "property_cost_factor":"1.0", "required_review":true}],
  "requirements": [{"requirement_id":"reserve", "essential":false, "description":"Review protected reserve under stress"}]
}
```

Unknown financial inputs remain null/missing. Never infer unknown costs as zero. Property and scenario dictionaries may include further documented validated fields. Scope all private data to server-derived tenant identity.

## Observation envelope

```json
{
 "observation_id":"obs-1", "check_id":"S005", "property_id":"synthetic-house-1",
 "source_id":"synthetic-flood", "snapshot_id":"sha256:...",
 "published_at":"2026-01-01T00:00:00Z", "effective_from":"2026-01-01T00:00:00Z",
 "evidence_basis":"official_record", "confidence":"High", "visibility_scope":"public",
 "owner_tenant_id":null, "case_scope_id":null,
 "rights":{"process":true,"display_raw":true,"display_derived":true,"retain_raw":true},
 "quality":{"retrieval_status":"SUCCESS","coverage_status":"COVERED","complete":true,"current":true,"identity_match":true},
 "payload":{"kind":"spatial","subject_geometry":{},"hazard_geometry":{},"crs":"EPSG:7855","positional_uncertainty_m":0}
}
```

Engine implementer documents exact supported payload kinds. Missing prerequisites -> NOT_ASSESSED with reason, substantive priority null, critical gap priority3. Supersession explicit. Conflicts cannot silently select newest. Public records cannot carry private evidence-derived facts. Process and display rights are separate; metadata-only evidence cannot claim full replay.

## Assessment output minimum

assessment_id (stable hash), case_id, property_id, as_of, engine_version, rule_version, input_hash,
status, findings, gaps, opportunities, domains, coverage, financial_scenarios, limitations,
input_snapshot_ids and check_results. Preserve assessed finding priority and gap priority separately.
Coverage denominator comes from check manifest, not observed rows. Opportunities never subtract risk.
Exclude wall-clock generation times from deterministic core/hash. Preserve exact sorted serialisation.

## Registry

`config/sources.json` contains `sources` list of canonical source contracts. Root creates from supplied catalogues. Each record:
source_id, title, adapter, endpoint, jurisdiction, category, access_status, licence_status,
enabled (false except explicitly selected), refresh_policy, source_aliases, source_claims, parameters.
Adapters: arcgis, socrata, rba_csv, crime_xlsx, generic_json, file_download, sdmx_csv, gtfs_zip, discovery, manual.
Unsupported/inaccessible source -> clear status, never pretend it returned complete evidence.

## Ownership

Engine agent: engine.py, finance.py, spatial.py; tests/test_engine*.py, test_finance*.py, test_spatial*.py; docs/ENGINE_CONTRACT.md.
Ingestion agent: ingestion.py, adapters/; tests/test_ingestion*.py; docs/INGESTION.md.
Storage/API agent: storage.py, api.py, auth.py, reporting.py; tests/test_api*.py/test_storage*.py; docs/API.md.
Root: everything else. Notify others before interface changes. Use sqlite3 rather than introducing unneeded database dependencies. SQLite is the tested local backend; future PostgreSQL/PostGIS is a documented scale path, not falsely claimed tested implementation.
