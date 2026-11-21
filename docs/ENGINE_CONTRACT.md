# Deterministic assessment engine: implemented contract

## What this build does

The engine turns pinned, scoped evidence and explicit buyer assumptions into **action priorities, evidence gaps, conditional cash scenarios and separate opportunities**. It does not estimate a single probability of a bad purchase, predict prices or hide missing evidence in an average.

The implementation is `src/riskengine/engine.py`, `finance.py` and `spatial.py`. The public function is:

```python
from riskengine.engine import evaluate_case
result = evaluate_case(case, observations)  # reads the installed 65-check manifest
```

There is no network call, wall-clock reading, LLM execution or storage mutation in this calculation. The engine reads the versioned check manifest. Case data and evidence do not execute instructions or code. Source acquisition, authentication, storage and report rendering are separate modules.

`checks=` is a trusted server/test manifest override. It is not an end-user mechanism for removing required checks. A case `skip_checks`, waiver or review decision does not change the coverage denominator.

## Outputs and decision meaning

| Field | Meaning |
|---|---|
| `assessment_id`, `input_hash`, `manifest_hash` | Stable content identities for the calculation, complete pinned input set and check manifest. |
| `engine_version`, `rule_version`, `runtime_versions` | Application and calculation versions, including Python, GEOS, Shapely, PROJ and PyProj. A different dependency version is a different replay context. |
| `status` | `COMPLETE` only when every required applicable check is fully assessed. Completeness is not a recommendation to buy. |
| `priority` | Maximum supported finding priority; never a weighted average. `null` when there are no supported findings. |
| `gap_priority` | Maximum priority of missing or unresolved evidence. Kept separate from known adverse findings. |
| `findings` | Evidence-supported observations or conditional calculations, with rule, method, confidence and provenance. |
| `gaps` | Missing, conflicting, stale, incomplete, unlicensed or inapplicable-to-the-rule evidence. Missing evidence is not a zero-risk finding. |
| `opportunities` | Conditional, evidenced benefits. Their priorities are null and they do not reduce adverse priorities. |
| `coverage.full_due_diligence` | All required checks, including private evidence, regardless of public-screen mode. |
| `coverage.public_screen` | The separately reported required public subset. |
| `check_results` | Every manifest check, including ones with no observation at all. |
| `financial_scenarios` | Repayments, baseline budget, settlement, reserve, each separate stress path and optional exit calculation. |
| `excluded_observations` | Stable exclusion reasons; identifiers are redacted for cross-property/private-scope mismatches. |
| `replay_level` | Whether the supplied evidence permits pinned-input replay or only metadata replay. This does not itself prove upstream raw files exist. |

Priorities are ordinal actions: **0** no flag within the assessed scope; **1** context/monitoring; **2** decision-relevant cost or constraint; **3** material investigation or required stress failure; **4** a verified conflict with a named essential buyer condition, or confirmed settlement funding failure. No 0–4 number is a probability. Confidence uses a separate High/Medium/Low scale. Duplicate or correlated observations do not increase it.

Coverage counts required, applicable checks that are assessed **and** have no unresolved sub-gaps. A known defect with an unknown repair cost remains a supported priority-3 finding while the related check is incomplete. A partially evidenced flood check can likewise retain a positive-overlap finding while another required mechanism remains unknown. A zero denominator produces `percentage: null` with a reason, never 100%.

Only an explicit manifest `applicable_when` rule and a known property attribute can establish `NOT_APPLICABLE`. Missing property attributes remain unknown. Example: a manifest can restrict a strata check to declared `ownership_form` values `strata` and `unit_title`; it must not infer standalone title merely from the dwelling looking like a house.

## Case contract

Start from `examples/new_case_template.json` or the fully synthetic `examples/case.json`.

Required: non-empty `case_id`, `property_id` and an ISO `as_of` date/timestamp. Timestamps require a timezone; a date means midnight UTC. `property` and `finance` are objects. Finance requires `owner_tenant_id`. Requirements and scenarios use unique non-empty IDs.

Property-dependent findings require `property.identity_confirmed: true`. An explicit `ambiguous: true` blocks them. If `unit_required: true`, `unit_id` is required. Observation property identifiers must match exactly; the engine never transfers a document merely because two units share coordinates. The case confirmation is labelled as a case assertion. Authoritative ownership and building attribution remain separate manifest checks.

Each buyer requirement contains `requirement_id` and an explicit boolean `essential`; include a readable description. A rule cannot manufacture an essential condition by naming an absent requirement. Scenario and financial results are conditional on supplied values. For historical assessments, include `finance.received_at` and dated supporting documents; a later received date blocks the finance calculation. Without it the report explicitly identifies finances as supplied assumptions, not verified historical knowledge.

## Observation eligibility before any rule

Use `examples/reviewed_observation_template.json`. Each observation has:

```json
{
  "observation_id": "immutable-id",
  "check_id": "S005",
  "property_id": "selected-property-id",
  "source_id": "configured-source-id",
  "snapshot_id": "sha256:retained-source-version",
  "published_at": "2026-01-01T00:00:00Z",
  "effective_from": "2026-01-01T00:00:00Z",
  "evidence_basis": "official_record",
  "confidence": "High",
  "visibility_scope": "public",
  "owner_tenant_id": null,
  "case_scope_id": null,
  "rights": {"process": true, "display_raw": false, "display_derived": true, "retain_raw": true},
  "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED", "complete": true, "current": true, "identity_match": true},
  "payload": {"kind": "spatial"}
}
```

`quality` and `rights` are explicit upstream validations, not a claim that a successful HTTP request proves completeness. A connector or reviewer must establish their truth from the source contract. Missing flags fail closed. Optional `schema_valid` or `units_valid` false also blocks evidence. `current` is source-specific: a current statutory map may be old; age alone does not invalidate it.

Public records require `published_at <= as_of` and cannot carry tenant/case ownership or a private upload evidence basis. Private records require matching `owner_tenant_id`, `case_scope_id` and `received_at <= as_of`; if they also have a publication date, the later knowledge date governs. Missing publication/receipt dates do not support a faithful as-of conclusion. Expired rights, future facts and observations no longer effective are excluded. Announced future projects may be included when their public evidence was already known; later approval or geometry is excluded.

Processing, displaying derived results, displaying raw material and retaining raw material are different permissions. Raw-display permission is not required for a derived finding. This reporting engine withholds evidence when processing or derived display is disallowed. `retain_raw: false` allows an authorised derived calculation but changes the replay claim. The service/storage layer additionally enforces current rights on reads; historic permission is not permission to disclose a result forever.

The engine rejects two different records with the same observation ID. An explicit `supersedes: ["old-observation-id"]` can replace an eligible record from the same source. Cross-source replacement additionally requires `supersession_reviewed: true`. Cycles are rejected. A later timestamp alone does not win a conflict. Conflicting values for the same claim remain unresolved. Multiple independently identified projects, mechanisms, scopes or causal factors are not automatically treated as contradictory.

## Supported payloads

### Spatial extent: `kind: "spatial"`

Required: `subject_geometry`, `hazard_geometry`, `crs`, and `positional_uncertainty_m`. Geometries are GeoJSON Polygon/MultiPolygon objects. The hazard may be an explicit empty GeometryCollection **only** when independent source coverage is complete and covered. Subject polygons cannot be replaced with a point/centroid.

Optional: `hazard_crs`, `metric_crs`, `coverage_geometry`, `coverage_crs`, `subject_scope` (`parcel` or `dwelling_footprint`), `mechanism`, `factor_id`. If the subject CRS is not projected in metres, an explicit appropriate `metric_crs` is required. Coordinates transform with longitude/easting first. A supplied coverage polygon must cover the full subject. Invalid polygons are rejected, not silently repaired.

Relations are `POSITIVE_OVERLAP`, `BOUNDARY_TOUCH`, `NO_OVERLAP`, `BOUNDARY_UNCERTAIN`, or `OUTSIDE_COVERAGE`. Boundary touch never becomes a clear result. Overlap must retain positive area after the mapped hazard boundary is eroded by the declared combined positional uncertainty. Separation inside that uncertainty is unresolved. The uncertainty input must cover relevant subject and source positional errors; the engine cannot discover those errors from a polygon.

FL01/FI01 positive overlap gives priority 3. A reviewed, referenced consequence resolution can reduce the action to 1 using `resolution_reviewed`, `resolution_source_ref`, `consequence_resolved`; the designation remains recorded. Covered non-overlap is 0 for that mechanism and version. It does not establish flood depth, an annual probability, insurance availability or whole-building safety.

A manifest may declare `required_mechanisms: ["riverine", "overland_flow"]`. A missing mechanism keeps the check incomplete even when another mechanism has a supported positive finding. This production scope configuration must come from the jurisdiction source inventory; the engine does not invent missing maps.

`kind: "vertical_clearance"` accepts floor/flood heights, matching `floor_datum`, `flood_datum` and `unit: "m"`. It subtracts comparable supplied heights. Missing/mismatched vertical datums are unresolved; this build does not transform them.

### Reviewed physical/legal evidence

All these kinds require `reviewed: true`; `extraction_reviewed: false` blocks assessment. A boolean is an explicit reviewer attestation in this prototype, not a cryptographic professional signature. Source snapshot and case scope are still required. Arbitrary document text is never treated as an instruction.

| Kind | Required decision fields | Behaviour |
|---|---|---|
| `inspection` | Boolean `material_defect`; `scope_complete: true` needed for a no-material-defect conclusion. | Material defect 3; named essential conflict 4; minor issue 1; no flag within complete reviewed scope 0. Missing repair cost creates a separate gap. |
| `document` | `scope_complete: true`; explicit liability/no-liability state. | Known positive `liability_amount` 2; `material_liability_unresolved` 3; named essential conflict 4; `no_material_liability` 0. |
| `restriction` | Boolean `conflict`, reviewed scope and requirement link where applicable. | Named essential conflict 4; unresolved material legal question 3; nonessential constraint 2; complete reviewed compatible scope 0. |
| `insurance` | Boolean `conflict`, quoted/reviewed scope, `material_exclusion` where present. | Named essential cover conflict 4; material exclusion 3; nonessential constraint 2; complete reviewed acceptable scope 0. No hazard proxy is called an insurance refusal. |
| `reviewed_fact` | `statement`, boolean `issue_present`, reviewer attestation and scope. | Explicit structured professional/manual fact. `material`, `minor`, `conflict` and named requirement produce deterministic priorities. Output is labelled `modelled: false`. |

`conflict: true` and a matching essential `requirement_id` are both required for a buyer-specific priority 4. A numeric `repair_cost` is emitted only with `cost_known: true` and `cost_source_ref`; otherwise it is withheld with a gap. Raw text or model-extracted estimates cannot invent that cost.

### Projects, supply and opportunities

`kind: "project"` requires a canonical `project_id`. Several records for the same project merge independently evidenced milestones and count quantity once. Milestones contain `kind`, `date` and optional `published_at` inherited from their observation. Actual approvals, funding, construction or completion after `as_of` are not counted as known milestones. Planned/revised completion may be future. An approval does not imply funding or commencement.

For SP01 supply, provide integer `net_dwellings` and `scope_comparable: true`; the latter attests the declared area, dwelling type, period and competing segment were reconciled upstream. Signed net stock changes are permitted. Cancelled and completed projects remain in provenance but are excluded from future pipeline totals. `declared_net_dwellings_threshold` can produce priority 2; ordinary documented non-zero context is 1. No completion probability, price impact or weighted supply forecast is fabricated.

Project `impacts` require `supported: true`. A documented potential material impact is DV01 priority 2, or 3 if it relates to a named essential requirement. DV02 measurements require `measured_value`, `threshold`, `unit`, `method` and optional `threshold_direction` (`above`/`below`). An evidenced threshold breach is 2; an essential conditional future conflict 3; an already current essential conflict 4. Missing measurement information produces a gap.

`kind: "opportunity"` additionally requires `benefit`, `benefit_supported: true`, `timing_known: true`, and either `expected_completion` or an evidenced actual completion milestone. Those support flags attest upstream reviewed analysis; this build does not automatically simulate every transport network or predict a new rail project's delivery. `dependencies` remain visible. Observed completion controls actual availability; revised expected completion defers conditional benefit timing. Cancelled projects produce no opportunity. Output includes `price_uplift: null`.

### Crime and other context

CR01 uses `kind: "context"` with `count`, positive `denominator`, `period_start`, `period_end`, `area_id`, `boundary_version`, `definition` and `comparable: true`. A future or invalid count period is rejected. `rate_base` defaults to 1,000. The displayed rate is count/denominator × rate_base. An explicit `declared_rate_threshold` changes context priority 1 to 2 when exceeded. No claim of dwelling-level victimisation probability follows.

Other contextual signals accept a `summary`; optional numeric `measure` requires a `unit` and `definition`. A threshold additionally requires `comparable: true` and `threshold_basis`. Such outputs are labelled context and `modelled: false`. A generic context payload cannot complete a specialised flood, physical-condition or financial rule. Unsupported payload kinds or rule/payload mismatches stay unassessed.

## Finance contract and maths

All amounts should be JSON decimal strings. Calculation uses Decimal precision 40, equal monthly periods and nominal annual interest; intermediate payments/interest are not rounded. Display rounds HALF_UP to cents. This is a reproducible cash model, not a lender's daily-interest ledger.

For principal P, monthly rate r and remaining term n, payment is `P*r/(1-(1+r)**(-n))`; at zero rate it is `P/n`. Monthly balance is previous balance plus interest minus payment. A reset uses the **remaining balance and remaining term**, not the original principal and original term.

| Calculation | Inputs |
|---|---|
| Repayment | `principal`, `annual_rate_decimal`, `term_months`; alternatively `annual_rate` with explicit `rate_unit` (`percent` or `decimal`). |
| Rate resets | `rate_schedule: [{"start_month":25,"annual_rate_decimal":"0.08"}]`. Month 25 means after 24 payments. `fixed_expiry_months` plus decimal `revert_rate` is an alternative. |
| Baseline FN01 | `income_monthly`, `living_monthly`, `other_debt_monthly`, and exactly one of `property_costs_monthly` or `property_costs_annual`, plus valid repayment. |
| Rental case | `intended_use: "investment"` or a supplied rent; requires `gross_rent_monthly`, `vacancy_fraction`, `management_fraction`. Collected rent is gross × (1−vacancy); management applies once to collected rent. |
| Settlement FN04 | `purchase_price`, `acquisition_costs`, `immediate_works`, `loan_funds`, `cash_allocated`, and `funding_confirmed: true` for a conclusive priority. |
| Reserve FN03 | `cash_after_settlement`, `protected_reserve`; optional `minimum_buffer_months` requires all essential monthly outgoings, including mortgage. |
| Cash reconciliation | Optional `total_liquid_cash` must cover both `cash_allocated` and `cash_after_settlement`; double allocation blocks settlement/reserve/stress. |
| Stress FN02 | Unique `scenario_id`, `duration_months`, optional `rate_delta_bps`, `income_factor`, `property_cost_factor`, `rent_factor`, `minimum_monthly_surplus`, `required_review`, `requirement_id`. |
| Exit | `exit` object: `sale_month`, `sale_price`, `selling_costs`, `tax_treatment` (`before_personal_tax` or `explicit_tax`); the latter requires `tax_costs`. |

Monthly cash = prior cash + income + net rent − living − other debt − property costs − mortgage payment. Reserve breach means **any point in the declared scenario** has cash below the protected reserve, including month 0. A short stress may be survivable even if a longer stress is not. Scenarios are independently reported; mutually exclusive alternatives are not added together. A scenario is conditional, not a prediction that rates or income will change.

Settlement is separate: required funds = purchase + acquisition + immediate works; allocated funds = loan funds + cash allocated. A confirmed shortfall is priority 4 even when monthly cash flow is positive. Merely estimated funding keeps the result unassessed while the provisional amounts are visible.

Unknown income does not prevent calculating repayment, but it prevents declaring affordability. Buffer months divide cash by **all** essential outgoings. Zero/missing denominators are unassessed. Rental costs cannot be pre-netted and deducted a second time. The exit model repays remaining principal, not the original loan, and reports sale proceeds rather than total investment return.

Unsupported: interest-only, offsets, split loans, daily accrual, negative interest, stress beginning after month zero without a restated starting position, automatic tax calculations, refinancing approval, stamp-duty eligibility, stochastic forecasts and future property values. Invalid terms produce explicit unassessed results. Terms/scenarios are bounded to 1,200 months.

## Synthetic verification and limits

Run:

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests/test_engine.py tests/test_finance.py tests/test_spatial.py -q
```

| Original acceptance family | Implemented executable coverage |
|---|---|
| PR-AT-001 | Ambiguous identity, unit requirement, cross-property and cross-tenant rejection. Does not claim an automated national address-candidate resolver. |
| PR-AT-002 | Covered empty extent versus failed retrieval, outside/unknown coverage and incomplete source. |
| PR-AT-003 | 99 of 100 observed checks still 99%; missing critical check prevents completion. |
| PR-AT-004 | Noncritical gap, missing-row denominator, zero denominator, evidence removal cannot improve coverage. |
| PR-AT-005 | Public and full scope remain distinct; case skip/waiver does not remove private checks. |
| PR-AT-006 | Positive area, boundary touch, uncertainty, separate parcel/footprint, metre projection, vertical datum gate. |
| PR-AT-007 | Public publication/private receipt cutoffs, future project known now, later milestone excluded. |
| PR-AT-008 | No newest-record wins; explicit supersession, cross-source review and cycles. |
| PR-AT-009 | Four milestone records count one 40-dwelling project; cancelled/delivered exclusions and signed changes tested. |
| PR-AT-010 | Priority 3 survives many zero findings and a positive infrastructure opportunity. |
| PR-AT-011 | Repeated correlated records do not increase confidence; delay moves benefit timing. Independent cash paths never add alternative losses. |
| PR-AT-012 | Payment references, zero interest, explicit rate units, unsupported forms, remaining-term reset, missing-income separation. |
| PR-AT-013 | Six versus twelve months, month-10 breach, essential/exploratory priorities and full cash path. |
| PR-AT-014 | Rental deductions once, annual costs monthly, 36-month remaining principal and exit proceeds. |
| PR-AT-015 | Service/storage suite owns tenant access tests; core also rejects mismatched observations. |
| PR-AT-016 | Core rights separation and limited-retention replay; service/storage suite owns current-rights access enforcement. |
| PR-AT-017 | Document instructions do not execute; unreviewed extraction cannot score; invented/unreferenced costs withheld. |
| PR-AT-018 | Service/storage suite owns durable job and pinned snapshot tests. |
| PR-AT-019 | Identical/reordered inputs yield identical complete output; new facts create another result; waivers do not close evidence gaps. |
| PR-AT-020 | **Not a unit test and not claimed passed.** Requires a real buyer decision study, independently reviewed cases and measured decision outcomes. |

Reference checks passed in the executable fixtures: $720,000 over 360 months gives $4,316.76 at 6%, $5,283.10 at 8%, and $2,000 at zero interest. Remaining principal after 36 payments at 6% is $691,805.30. With $45,000 starting cash, $15,000 reserve, $7,700 income and $5,700 other outgoings, the 8% stress ends at $25,301.37 after six months and $5,602.74 after twelve; the first reserve breach is month 10.

The tests validate these synthetic contracts. They do not prove every government API is available, source coverage is adequate for a real parcel, a reviewer attestation is professionally correct, or that a high-completeness report predicts investment returns. Those require jurisdiction onboarding, source validation, expert review and the real-world acceptance programme.
