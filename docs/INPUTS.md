# Inputs, ingestion and analytical promotion

## 1. What must exist before a meaningful result

The minimum decision inputs are **property identity, a purchase case, an explicit assessment date and evidence with provenance**. A property address alone supports a preliminary public screen. It cannot establish building condition, legal compatibility, insurance availability or buyer affordability.

Unknown values stay unknown. The source inventory describes where inputs can come from; it is not permission to invent them or assume a live national feed exists. `COMPLETE_INPUT_REGISTER.md` lists every registered source and all 65 required checks. `config/sources.json` is the machine-readable source contract; `config/checks.json` is the denominator and processing specification.

## 2. Input families

| Input family | Required raw evidence | Acquisition routes | Transformation and use |
|---|---|---|---|
| Property identity | Address, aliases, unit, parcel/block identifiers, geometry, validity dates, ownership form | G-NAF bulk, ACT addresses/blocks/building footprints, title/survey documents | Reconcile address–unit–parcel–building; preserve unresolved matches and retired parcels |
| Flood and drainage | Model coverage, mapped mechanism/scenario, polygon/depth grid, vintage, parcel/footprint, floor levels, drainage inspection | ACT/other state mapping, local council studies, reviewed survey/inspection | Coverage-first intersection; separate boundary ambiguity, depth and floor clearance; never infer all-mechanism safety |
| Bushfire | Prone-area designation, coverage/vintage, vegetation/terrain context, site assessment and construction evidence | State/territory fire/planning layers, qualified site/building reports | Distinguish mapped designation from assessed site vulnerability and compliance |
| Ground and contamination | Geology/soil/slope, contamination registers, site history, geotechnical/contamination reports | Geoscience/state/council registers, specialist reports | Candidate constraints require property attribution and review; an empty incomplete register is not proof of clean soil |
| Legal and planning | Title/lease, easements, access rights, zoning, overlays, permitted use, approval documents | Land/title services, ACT planning, council permits, conveyancer documents | Check intended use and essential conditions against reviewed current restrictions |
| Building condition | Structure, pests, moisture, roof, asbestos, repair quotes, scope/exclusions | Buyer-authorised inspection PDFs/images and structured specialist reviews | Store original; review extracted claim and scope; distinguish observed defect from unknown cost |
| Insurance | Address-specific quotation, covered/excluded mechanisms, premium, excess, rebuild sum and conditions | Buyer/insurer/broker-supplied evidence | Evaluate actual quoted cover against requirements; no inference from a hazard map alone |
| Shared property | Owners corporation records, building defects, reserves, budgets, levies, litigation | Buyer-authorised records and review | Material liabilities and funding gaps remain separate from house-only facts |
| Nearby development | Canonical project/application ID, location, use, approved/proposed quantities, dated milestones, actual impact evidence | ACT/council DA systems, planning documents, construction evidence | Deduplicate activities; distinguish proposal/approval/construction/completion; measured shadow/noise needs a suitable model |
| Infrastructure | Route/station/access location, approved scope, funding, procurement, construction, opening date, delivery changes | Transport agencies, budgets, infrastructure/project publications, GTFS | Supported accessibility benefit and construction nuisance; delivery dependencies visible; no automatic percentage uplift |
| Supply and land release | Net dwelling additions, removals, tenure/type, market geography, time window, pipeline stages, completions, existing stock | Planning/land-release agencies, ABS approvals/completions, project data | Count unique projects; exclude cancelled/completed from future stock; no arbitrary probability weights or scarcity claim from low listings |
| Demand and employment | Geography/boundary editions, population, households, employment, observation periods | ABS datasets/APIs, official forecasts | Comparable area/time context; demographic forecasts do not directly predict an individual home's price |
| Sales/rental market | Verified settled comparables, property attributes, transaction dates, listings, rents, vacancy, days on market, licence | Jurisdictional sales data where available; licensed providers; reviewed comparables | Comparable-set quality and market context; automatic valuation/causal price models require separate calibration |
| Crime | Offence definition, recorded count, period, geography/boundary edition, suitable denominator, revision metadata | ACT Policing workbook and other jurisdictional official releases | Separate offences/infringements; use comparable definitions; area context is not a dwelling-level victimisation probability |
| Amenity/access | Schools/eligibility, public transport timetables/service, walk access, road safety, noise/air readings, canopy, energy ratings | Education, transport, council, environment agencies, property evidence | Proximity is distinct from eligibility, usable frequency or measured nuisance |
| Macro/finance | Published rates/inflation context; actual loan offer/rate/term; buyer budget, settlement funds, costs, reserve, scenario horizons | RBA/ABS; buyer/lender documents and declared inputs | Macro context does not replace the buyer's mortgage rate; compute cash and debt from explicit assumptions |
| Quality/governance | Publication/effective/receipt times, provenance, complete query scope, schema/units, licence/retention, reviewer | Every capture and review | Eligibility gates, source health, audit, deterministic replay and explicit missingness |

## 3. Government API versus downloadable file versus private input

Not every official dataset is an API table. The implemented adapters support the following distinctions:

| Adapter | Input contract | What it can establish |
|---|---|---|
| `arcgis` | Exact numbered FeatureServer/MapServer layer, stable object IDs, fields, geometry and coordinate metadata | Reconciled bounded feature capture; not independent model coverage |
| `socrata` | A row-table `/resource/xxxx-xxxx.json` endpoint, stable row IDs and count | Reconciled table capture; not a workbook or portal page |
| `rba_csv` | Actual RBA statistics CSV, series ID, units and source dates | Parsed published series observations; null release cells remain null |
| `crime_xlsx` | Verified XLSX asset or discoverable catalogue attachment | Area/category/quarter observations with source definitions and offence/infringement separation |
| `sdmx_csv` | A configured CSV data request with series/dimension/time metadata | Parsed statistical dimensions; this is not an automatic discovery implementation for every SDMX endpoint |
| `gtfs_zip` | Authorised GTFS ZIP and declared authentication scheme | Bounded standard transit tables; routing/door-to-door travel modelling remains separate |
| `generic_json` | Configured JSON endpoint with expected shape | Captured structured data; not automatic semantic interpretation |
| `file_download` | Verified downloadable content or authorised local file | Original file capture; unsupported formats do not pretend to become typed observations |
| `discovery` | Catalogue/portal/HTML/XML reference | `REFERENCE_ONLY`, useful source metadata and acquisition guidance |
| `manual` | Buyer/specialist/licensed evidence | Explicit acquisition requirement; never a fake zero-row success |

`load_registry()` resolves the supplied machine-readable catalogue or an administrator-selected `RISK_SOURCES_PATH`. Calls from the API accept a source ID, not an arbitrary URL or local file path. Local file imports are configured by the trusted operator in a source contract.

## 4. Source contract example

```json
{
  "source_id": "example-reviewed-layer",
  "title": "Reviewed official layer",
  "adapter": "arcgis",
  "endpoint": "https://OFFICIAL-HOST/arcgis/rest/services/LAYER/FeatureServer/0",
  "enabled": false,
  "licence_status": "REVIEW_REQUIRED",
  "rights": {"process": false, "retain_raw": false, "display_raw": false, "display_derived": false},
  "parameters": {"page_size": 200, "expected_fields": ["OBJECTID"]},
  "limits": {"max_records": 1000, "max_bytes": 20000000}
}
```

This is a shape example, not a valid endpoint. Rights are independent booleans. Only activate them after recording the relevant source terms and attribution. An adapter can collect an explicitly selected disabled source once rights permit; `enabled` is intended scheduling state, not a licence override. HTTP clients cannot alter source endpoints or credentials. Authentication values are environment references, never literal secrets in the catalogue.

ACT crime has a reviewed source-specific CC BY 4.0 declaration at the primary metadata URL. The release records that permission and attribution. Its workbook ends at 2025 Q2. Historical observations are useful, but they are not evidence of current 2026 crime rates. Source licensing and currentness are separate decisions.

RBA's copyright notice specifies special conditions for cash-rate/financial data; do not assume every statistical file is covered by a generic website licence. ACTmapi also directs users to dataset metadata and attribution terms. A portal's availability does not automatically settle downstream retention or redistribution rights.

Primary references: https://www.data.act.gov.au/api/views/2egm-dieb.json ; https://www.rba.gov.au/copyright/index.html ; https://www.actmapi.act.gov.au/terms-and-conditions .

## 5. Buyer finance input dictionary

| Field | Meaning and unit |
|---|---|
| `principal` | Initial debt to amortise, AUD string |
| `annual_rate_decimal` | Borrower's annual interest rate as a decimal; `"0.06"` means 6% |
| `term_months` | Remaining repayment term as a positive integer |
| `income_monthly` | Declared take-home cash income per month, AUD |
| `living_monthly` | Declared living expenditure per month, AUD |
| `other_debt_monthly` | Other required monthly debt payments, AUD; zero only if confirmed |
| `property_costs_monthly` | Declared recurring ownership costs excluding the modelled mortgage, AUD |
| `cash_after_settlement` | Cash remaining after settlement allocations, AUD |
| `protected_reserve` | Amount the buyer intends to preserve, AUD; not assumed zero |
| `purchase_price` | Proposed price, AUD |
| `loan_funds` | Loan funds actually allocated to settlement, AUD |
| `cash_allocated` | Cash allocated to price/acquisition/works, excluding the post-settlement cash above |
| `acquisition_costs` | Reviewed total acquisition costs, including applicable duty/fees as supplied |
| `immediate_works` | Cash needed for known immediate works at acquisition |
| `funding_confirmed` | Whether the submitter has verified the declared funding availability; not an automated lender approval |
| `rate_schedule` | Explicit `{start_month, annual_rate_decimal}` resets |
| `gross_rent_monthly`, `vacancy_fraction`, `management_fraction` | Explicit gross monthly rent and decimal vacancy/management deductions; supply all three when rental income is modelled |
| `exit` | Explicit sale month/price, selling costs and personal-tax basis; no assumed appreciation |
| `received_at` | Optional financial-evidence receipt time for a historical case; attach supporting evidence where verification is needed |

Document all known ownership costs: council rates, water/service charges, insurance, maintenance, applicable land tax, strata/body corporate charges, management and vacancy where relevant. Avoid double-counting a cost across fields. A cash account used for settlement cannot also remain wholly available as reserve.

The default stress fixture uses income × 0.70, interest +200 basis points (2 percentage points), and separate 6/12-month durations. Those are transparent example assumptions, not forecasts or universal lending standards.

## 6. Observation envelope

Every structured observation names `observation_id`, `check_id`, `property_id`, `source_id`, `snapshot_id`, source/receipt dates, visibility scope, evidence basis, confidence, rights, quality and a typed `payload`. Private observations additionally resolve to an authenticated tenant and case. The API controls their actual receipt timestamp.

Quality flags are not magical proof: they are assertions backed by the captured source/review. Source review needs a named reviewer and evidence basis. Check meaning is defined by the versioned manifest, so a generic text summary cannot bypass a specialised spatial or financial calculation.

Supported payloads and exact requirements are in `ENGINE_CONTRACT.md`. A `context` payload carries a precise measure, unit, definition and comparable threshold basis if a threshold is used. A crime rate additionally requires count, denominator, period, geography/boundary edition and comparable offence definition. A `project` needs a stable canonical ID; its milestone evidence is separate from quantity and impact evidence.

## 7. Automatic hazard promotion

The integrated `collect_case` path supports named ACT flood and bushfire mappings after all prerequisites are supplied. Add a reviewed `source_assertions` record to the case:

```json
{
  "source_assertions": {
    "act_flood_extent": {
      "reviewed": true,
      "reviewer": "NAMED-REVIEWER",
      "reviewed_at": "2026-11-21T00:00:00Z",
      "coverage_status": "COVERED",
      "coverage_basis": "REFERENCE-TO-MODEL-COVERAGE-EVIDENCE",
      "published_at": "REPLACE-WITH-VERIFIED-SOURCE-DATE",
      "identity_match": true,
      "current": true,
      "positional_uncertainty_m": 1,
      "confidence": "Medium"
    }
  }
}
```

The example uncertainty is illustrative and must be replaced with a justified value. The case must also contain a valid parcel polygon and projected metre CRS. Collection must be complete for the relevant unfiltered mechanism/query scope; all geometries must be valid. The pipeline preserves a private case-scoped observation because the mapping depends on that case's review. It does not publish a buyer's reviewed facts to a shared public cache.

The result reports exact promotion gaps such as coverage review required, unknown publication date, missing uncertainty, invalid geometry, filtered mechanism, insufficient query buffer or incomplete capture. Adding more source endpoints cannot close these gaps by itself.

## 8. Ingestion outputs and end-to-end sequence

1. Select a registered source and explicit query bound.
2. Check retention permission, credentials and endpoint safety.
3. Capture bounded bytes and preserve raw hashes/receipt metadata.
4. Parse the actual format and reconcile expected versus returned records.
5. Store immutable snapshot metadata under the tenant/case.
6. Apply a supported deterministic mapping or request reviewed normalisation.
7. Gate evidence by identity, mechanism coverage, units, currentness, dates, conflicts and rights.
8. Evaluate every required check, including absent inputs.
9. Persist the fixed input references and structured result.
10. Explain concerns, opportunities, cash scenarios and missing evidence with source references.

Status and counts returned to the UI respect derived-display rights. Raw bytes do not appear in collection responses. A new evidence date or scenario creates a new assessment rather than changing an old one.

## 9. What the uploaded additions contribute

The coverage-first spatial states, duration-bounded protected reserve, separate settlement sufficiency, public/private split and exact amortisation fixtures are incorporated directly in executable code/tests. The source workbooks contribute endpoint discovery, schemas and gaps; their claims remain separately marked until verified. The broad risk library and infrastructure capacity report contribute review questions and delivery/cost context. Their generic ratings, sector forecasts and illustrative impacts are not transplanted into a property's score.

Low-value or misleading additions would be uncalibrated percentage uplift per railway, fixed completion-probability weights, a single suburb crime rank without a denominator, treating approvals as completed homes, or a weighted score that rewards missing evidence. The design deliberately has no such shortcuts.
