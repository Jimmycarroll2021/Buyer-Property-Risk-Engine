# Property Risk Engine — complete architecture

## 1. Core idea

**An assessment is a reproducible decision about a specific property purchase, for a specific buyer, at a specific date, using a named set of evidence.** The property alone is not the decision unit. A structurally sound house can be unaffordable to one buyer; a well-funded buyer can still face title restrictions, flood exposure or an uninsurable structure.

The system therefore produces four connected outputs: supported property concerns; buyer-specific financial resilience; conditional opportunities; and the unresolved evidence needed to finish the decision. It keeps these separate. A proposed railway does not cancel an observed building defect. Uncertain evidence does not reduce a potentially serious issue to a small number.

The full drawings are in `Property_Risk_Architecture.pdf`. The first follows evidence end to end; the second shows running software and its deployment boundary; the third shows data relationships, versions and access controls. Their editable Graphviz `.dot` and scalable `.svg` sources are included.

## 2. Purchase-case boundary

A case holds property identity, the buyer's proposed purchase and loan, household cash-flow assumptions, reserve requirements, intended use, essential conditions and an explicit `as_of` time. An assessment combines one case version with one evidence set and one versioned check manifest.

The key identity relationships are address → unit/tenancy where relevant → parcel → building/footprint. These are not interchangeable. An address point can identify a service location without locating the dwelling footprint. A parcel may contain multiple dwellings or an apartment building. A parcel-level flood overlap does not automatically establish water above a particular finished floor. The first release requires confirmed property/parcel identity in the case or reviewed observations; it does not claim a complete automatic nationwide entity resolver.

Source families can contribute multiple complementary observations. Conversely, multiple portals or copied records may refer to one underlying source. Catalogue aliases are retained and exact known ArcGIS layer aliases are grouped. Project activity rows are grouped by a stable project ID before counting competing stock; activity counts are not dwelling counts.

## 3. System flow

### Stage A — source contract and input receipt

Every source has an ID, publisher/title, endpoint or manual acquisition path, adapter, scope, expected format, version/cadence claims, access conditions and separate process/retain/display rights. Source metadata is itself versioned configuration. A source URL is not accepted from a public API caller; the caller selects a registry ID and bounded query fields.

Public inputs include property geometry, planning, hazards, infrastructure, area statistics and economic series. Private inputs include budget/loan assumptions, inspections, legal documents, insurance quotations and buyer priorities. Reference reports supply questions and context. A generic risk-library rating is not an observation about the selected house.

### Stage B — bounded acquisition

An adapter retrieves source bytes, records request scope, checks transport/service errors and preserves the raw bytes when retention is permitted. ArcGIS object IDs/counts are reconciled with returned features. Socrata rows require stable IDs and count reconciliation. Files are parsed according to their actual format rather than a catalogue's guessed API type. The ACT crime asset is an XLSX workbook; it is not a normal Socrata row table.

Each operation has byte and record bounds. Hitting a cap produces `PARTIAL`, not `COMPLETE`. HTTP 200 with an ArcGIS error is a failure. Duplicate or changing pages become a consistency issue. Rate limits and inaccessible credentials remain visible. Long retry delays are deferred rather than ignored. No fetch failure establishes the absence of a hazard or planned project.

### Stage C — immutable capture

Raw files are named by SHA-256 of their contents. A stable snapshot definition identifies the source contract/query, content hashes and parse result. Capture receipts record the separate retrieval time. Identical source bytes and scope can reuse the same snapshot while retaining distinct receipt events.

The local database stores case versions, evidence envelopes, snapshots, assessment outputs, source policies, jobs, reviews and audit events. Large original files remain in scoped runtime directories. The package never serves the runtime directory as static web content.

### Stage D — normalisation and evidence eligibility

Normalisation turns raw records into typed claims: spatial extent, reviewed inspection, legal restriction, insurance terms, project milestones, opportunity, measured context or common-property document position. Every claim has a subject, source/snapshot, relevant dates, units, quality assertions and access scope.

The engine requires identity, coverage, completeness, currency, date eligibility and process/derived-display rights before using an observation. Required context is not guessed. A source's advertised overall bounding rectangle does not establish that its flood model covers every property inside it. A complete response for one query does not establish complete knowledge of every flood mechanism or all future development.

Unreviewed text extraction remains unreviewed. A document upload captures bytes and metadata, not authoritative assertions. Source assertions that enable automatic hazard promotion must name a reviewer, review date, coverage basis, publication date, confirmed identity/currentness and explicit positional uncertainty. The query must cover the parcel plus its uncertainty buffer, and an attribute filter cannot silently remove relevant hazards.

For generic inputs, the engine accepts reviewed structured observations through the same envelope. The v0.1 end-to-end automatic mapping is deliberately limited to declared hazard-source mappings. A broad source catalogue does not imply every source has a tested property-specific transformation.

### Stage E — deterministic assessment

`evaluate_case(case, observations, checks)` performs no network calls, model calls, database writes or implicit current-time reads. It evaluates a fixed required-check manifest, not merely the records that happened to arrive. It checks source conflicts and explicit supersession before interpreting evidence.

Numerical calculations use explicit units and financial Decimal arithmetic. Spatial operations use Shapely/pyproj with declared coordinate systems, metre units for distances and areas, and explicit uncertainty. The rule engine evaluates structured claims, financial scenarios and missingness independently.

### Stage F — immutable result and review

An assessment includes the case/property/date, engine/rule/manifest versions, input hash, check results, findings, opportunities, financial schedules, gaps, coverage and source references. An assessment ID is derived from the complete canonical result. The store pins the input case version and observation hashes, and refuses conflicting rewrites of an immutable ID.

The report and dashboard explain the result. Review actions such as acknowledge, investigate, waive or resolution submitted are separate records. Waiving a concern does not rewrite the source evidence, turn an incomplete check into a complete one, or create a new factual finding. Resolution requires new reviewed evidence and a new assessment.

## 4. Components and responsibilities

| Component | Implementation | Responsibility |
|---|---|---|
| Browser dashboard | `web/` HTML/CSS/JavaScript | Authenticated case editing, evidence receipt, collection, findings, scenarios and drawings |
| API | `api.py`, FastAPI | Validate requests, derive tenant identity, call the store/pipeline, enforce output access |
| CLI | `cli.py` | Local setup, imports, demo, collection, jobs, reports and replay |
| Source adapters | `ingestion.py`, `adapters/` | Bounded, source-specific HTTP/file capture and deterministic parsing |
| Pipeline coordinator | `pipeline.py` | Select trusted contracts, capture snapshots, apply reviewed mappings, pin assessments |
| Spatial evaluator | `spatial.py` | Coverage-first polygon relations, projected units, uncertainty and vertical-datum checks |
| Finance evaluator | `finance.py` | Mortgage schedules, baseline budget, day-one funding, reserves and duration-bounded stress |
| Evidence rule engine | `engine.py` | Eligibility, required checks, findings, gaps, opportunities, coverage and canonical hashes |
| Durable store | `storage.py`, SQLite | Tenant/case-scoped versions, immutable inputs/results, jobs, source policies and audits |
| Report renderer | `reporting.py` | Escaped standalone HTML from the permission-checked structured result |
| Configuration | `config/` | Source contracts, source claims, rules, signal definitions and acceptance specifications |

The local service is a small modular application rather than a fleet of services. This keeps the first measurable experiment understandable and deployable without extra infrastructure. Modules have explicit boundaries so storage and workers can be replaced after equivalent behaviour is verified.

## 5. Scoring model

The output is not a weighted average of unrelated risks. Its numeric value is an **action priority**, with a separate priority for evidence gaps:

| Value | Meaning |
|---|---|
| 0 | No concern identified within the assessed, explicitly covered scope |
| 1 | Context or minor issue to understand |
| 2 | Material consideration or non-essential incompatibility to review |
| 3 | Material unresolved concern, required stressed-reserve breach, or critical missing evidence |
| 4 | Confirmed incompatibility with an explicitly essential requirement, or a confirmed settlement funding shortfall |

Exact rule conditions are in `ENGINE_CONTRACT.md`. These are transparent workflow policies, not calibrated event probabilities. The domain/headline known-concern priority is the maximum supported finding, not an average that can hide a major issue. Gaps have `substantive_priority: null` plus their own review priority. Confidence (High/Medium/Low) describes the evidence basis and is not multiplied into severity.

Coverage uses the fixed denominator of required applicable checks. A check with a supported defect but missing repair-cost evidence can still be incomplete. Formal `NOT_APPLICABLE` exclusions are controlled by the trusted manifest, not a buyer's skip switch. The default broad manifest is conservative and includes all 65 requirements; property-specific exclusions must be formally specified and tested before deployment. Full due diligence and public-screen coverage are reported separately.

Opportunities contain supporting evidence, timing, dependencies and uncertainty. They never subtract from concern priority and contain no invented price-uplift percentage. Project announcement, approval, funding, contract, construction and completion are independent dated milestones, not assumed steps in a guaranteed delivery sequence.

## 6. Financial mechanics

The engine separates three questions: can the buyer settle; what is the ongoing monthly balance; and can the buyer sustain the specified stress for its duration without crossing a protected reserve?

For a principal-and-interest loan, monthly payment is `P × r / (1 − (1+r)^−n)`, where `r` is the annual decimal rate divided by 12. Zero-interest loans use `P/n`. Remaining balance uses the amortisation schedule, not the starting principal. Decimal arithmetic is retained internally and money is rounded for output. The model states its monthly compounding convention; a lender's actual daily-accrual/rounding contract may differ.

Settlement compares the confirmed allocated loan and cash against price, acquisition costs and immediate works. Ongoing budgets use declared income, living costs, debt repayments, property costs and separately specified rental assumptions. Unknown taxes, fees, repairs or rental costs are not automatically zero. Duty, concessions and personal tax calculations require jurisdiction/date-specific verified inputs; there is no undocumented tax-rate lookup.

A scenario specifies duration, interest shock, income factor and ownership-cost factor. The schedule recalculates the loan payment when the rate resets, tracks monthly cash, and reports minimum cash and the first breach of protected reserve. It does not equate negative monthly cash flow with immediate insolvency. An optional exit calculation uses remaining debt, specified sale price, selling costs and explicit tax basis; its sale price is an input scenario, not a valuation.

## 7. Spatial mechanics

The order is identity → known mechanism coverage → valid geometry/CRS → complete source/query scope → positional precision → polygon relationship. Relevant outcomes are positive area overlap, boundary ambiguity/touch, covered non-overlap, outside coverage and not assessed. Empty geometries are accepted only where a complete, correctly scoped source query and independent coverage evidence support absence in that mapped mechanism.

Longitude/latitude degrees are never treated as metres. `always_xy` fixes axis order for declared transformations. A projected metre CRS is required for area/distance decisions; the example uses EPSG:7855. Source and working CRS are retained. A mapped flood polygon does not establish numerical depth, floor clearance, flood frequency beyond the source definition, vulnerability or loss. Vertical comparisons require a compatible stated height datum and uncertainty. Geometry is not silently simplified to squeeze under a response cap.

## 8. Time, conflicts and replay

Public evidence is constrained by its publication/knowledge time. Private evidence also requires receipt into the case by `as_of`. Event/effective dates are separate: a project may be publicly announced now for construction later. Future benefit milestones can be represented with explicit conditions; future current-condition claims cannot enter an older assessment.

Conflicting claims remain unresolved unless an explicit supersession resolves them. Newest retrieval is not automatically the correct legal or physical version. Canonical sorting handles unordered observations and other set-like fields while preserving coordinate and schedule order. Case, observations, required checks, rule version and engine version enter the decision hash.

Replay loads the original case version and exact evidence references in a read transaction, verifies hashes and checks current permissions. It fails if inputs are missing, changed or no longer permitted. It does not run a fresh network query and call the result historical. Reproducibility requires retaining the corresponding code/dependencies/configuration; future source changes do not alter a saved assessment.

## 9. Privacy and security boundary

Public observations carry no buyer tenant or case fields. Private observations always carry both. The API derives the tenant from a bearer credential, rather than accepting an owner field as authority. Two cases assessing the same property cannot read each other's inspections or finances. Reports, evidence listings, documents, source-health metadata, reviews and job access are scoped independently.

Processing, raw display, derived display and retention are separate rights. Collection does not capture source bytes without retention permission. Source policies can restrict previously captured material; a historical report cannot bypass a later display restriction. Original private documents are opaque files, with size/type limits, safe names, content hashes and attachment downloads. No uploaded document instructions are executed.

Local API keys are generated randomly and kept out of the distributable package. The default listener is 127.0.0.1. The OS account and CLI operator are trusted. Database/files are not encrypted by this application; use appropriate host encryption and access controls. The event audit is application-level and is not a tamper-proof ledger against a local administrator.

## 10. Durable operations

Source contracts specify intended refresh review; a source's release cadence is not a promise that its publisher is up to date. The app exposes source health, counts, completeness and explicit promotion gaps subject to rights. Jobs carry idempotency keys, lease ownership, attempt limits and backoff. A restarted worker can recover expired work, while a stale worker cannot overwrite a reclaimed lease.

This release supplies `worker --max-jobs N` for a bounded invocation; it does not install an unattended cron service or Windows Scheduled Task. Source scheduling, alert delivery and a production scheduler are not silently enabled. No email or external message is sent by the engine.

## 11. Scaling architecture and material gates

After the local experiment demonstrates value, move the store to PostgreSQL/PostGIS, large evidence to private object storage, tenant authentication to a managed identity provider and jobs to a durable queue/scheduler. Preserve the same evidence contracts, exact financial fixtures and replay checks. Add database-enforced tenant policies, migrations, backups, restore drills, retention/deletion workflows, encryption/key management, security monitoring, API rate limits and a network egress policy before exposing a multi-user service.

PostGIS is appropriate for indexed spatial joins and larger shared public datasets; it is not necessary to prove a single-case deterministic calculation. Object storage and managed identity are deployment concerns rather than reasons to make the first result dependent on a cloud subscription. Docker configuration is supplied as packaging, but Docker execution was not available in the build environment.

Additional analytical models need separate evidence and acceptance gates: independently validated address/parcel reconciliation; terrain/hydrology; depth/floor loss; measured shadow/privacy impact; travel routing; comparable-sale adjustments; supply absorption; hazard/insurance loss calibration; and causal infrastructure-price effects. Machine learning can be added after these targets and validation datasets exist. Its predicted uncertainty must remain explicit, and it cannot quietly replace the deterministic core.

## 12. Where frontier AI fits

AI can research sources, draft adapters, create tests, propose schemas, review changes and explain a fixed result. The deployed assessment core makes no model call. If document extraction or narrative generation is added later, store its model/version, input hash and extracted claims separately; require review before promoting claims into deterministic evidence. The explanation layer must cite the frozen result and must not invent new values, scores or sources.

This division gives AI productive engineering work while preserving a testable decision path: the same approved evidence and versions produce the same structured result.

## Technical references

- FastAPI official testing/security documentation: https://fastapi.tiangolo.com/tutorial/testing/ and https://fastapi.tiangolo.com/reference/security/
- Shapely official geometric predicates and manual: https://shapely.readthedocs.io/en/stable/manual.html
- pyproj official Transformer documentation: https://pyproj4.github.io/pyproj/stable/api/transformer.html
- SQLite transaction documentation: https://www.sqlite.org/lang_transaction.html
- ACT source-specific crime metadata/licence: https://www.data.act.gov.au/api/views/2egm-dieb.json
- RBA copyright and specific financial-data conditions: https://www.rba.gov.au/copyright/index.html

The primary documentation informed component choices; executed behaviour is evidenced separately in `VERIFICATION.md` and the test suite.
