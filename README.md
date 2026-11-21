# Property Risk Engine

**A runnable local application that turns captured property evidence and a buyer's financial assumptions into repeatable findings, explicit gaps and review actions.**

The browser dashboard combines versioned property assessments with a buyer brief for ACT addresses. The demonstration house is synthetic. The separate Kingston example uses a real public address and illustrative buyer finances.

## Repository and weekend buyer worksheet

This repository is the current source for the buyer engine, three household storms, bid pricing and weekend worksheet. See [setup and the authoritative checkout](docs/REPOSITORY_HANDOVER.md). Start the sample preview with `.\scripts\start-offer-preview.ps1 -Port 8142` and open http://127.0.0.1:8142/weekend.

The five fictional household tasks are [Ngunnawal](docs/uat/agent-uat-pack/01-ngunnawal.md), [Weston](docs/uat/agent-uat-pack/02-weston.md), [Kambah](docs/uat/agent-uat-pack/03-kambah.md), [Belconnen](docs/uat/agent-uat-pack/04-belconnen.md) and [Braddon](docs/uat/agent-uat-pack/05-braddon.md). Give an agent its brief inline when attachments are unavailable. [Dispatch instructions](docs/uat/agent-uat-pack/BUYER_TASKS.md), [historical UAT results](docs/uat/weekend-uat/REPORT.md) and [publication checks](docs/uat/publication/REGRESSION.md) are retained with the source.

### Build a pre-offer brief

Open [the local buyer preview](http://127.0.0.1:8131/). Enter an ACT street address, suburb and proposed offer or asking price. The two retained addresses work offline. Select **Compare a second home at the same price** to compare 11/14 Currie Crescent, Kingston with 21/28 Ringrose Crescent, Isaacs. Other matching addresses use the ACT address register when available.

Open **Adjust priorities, holding period and costs** to choose whether to live in the home as it is or extend it, and to change the buyer priority, holding period, alternative price, recurring stress assumptions and one-off levy. Sample household amounts are marked illustrative. Clear the illustrative assumptions to start with just an address and price. Unknown values stay visible. Each saved brief includes the issues to investigate, comparable sale evidence, cash scenarios, area effects and catalogue coverage. A bookmark or JSON download identifies the exact saved assessment.

After project dependencies are installed, start the dedicated sample server from the project directory. Leave the terminal open while using it.

```powershell
.\scripts\start-offer-preview.ps1
```

If port 8131 is busy, run `.\scripts\start-offer-preview.ps1 -Port 8132` and open the address printed in the terminal. The preview uses the dedicated `runtime/buyer-preview` directory. Anyone on this computer can access its sample cases. Use the private desktop launcher below for personal budgets and buyer documents. The full evidence workspace is available from the top navigation. Historical case bookmarks still open their saved workspace case.

## Start here

1. Install **Python 3.12 or 3.13** if it is not already installed.
2. Extract this complete folder to a local directory.
3. On Windows, double-click **`start-windows.cmd`**. On macOS/Linux, run **`bash scripts/setup.sh`**.
4. The launcher opens your private workspace in your browser. You can bookmark the dashboard and its purchase cases within that browser session.
5. Build a brief directly from the address form, or open **Evidence workspace** to select an existing purchase case or expand **Choose another ACT property**. **Open Kingston example** shows 11/14 Currie Crescent with illustrative finances. For your own case, enter a street address and suburb, then choose the matching ACT Government record. Alternatively enter coordinates you have verified. New address searches start with empty buyer amounts.

The **Buyer brief** shows selected development applications and light rail proposals by distance, land use at the address point, reported crime at suburb scale and financial scenarios for the selected case version. The ACT sources have different geographic coverage and dates. Expand **Coverage and measurement** for the limits on planning distances. Use **Edit buyer amounts and loan terms** to save a revised scenario. JSON and HTML assessment downloads contain the pinned engine result. The local source context is presented separately in the dashboard.

Street searches query the [ACT Government address register](https://services1.arcgis.com/E5n4f1VY84i0xSjy/arcgis/rest/services/ACTGOV_ADDRESSES/FeatureServer/0). The Kingston example and the four brief sections work from retained local data. Coordinates are checked against the [ACT Government division boundaries](https://services1.arcgis.com/E5n4f1VY84i0xSjy/arcgis/rest/services/ACTGOV_DIVISIONS/FeatureServer/0). The bundled division extract contains all 121 features returned on 21 November 2026, reprojected to WGS84, copyright Australian Capital Territory. [ACTmapi terms](https://www.actmapi.act.gov.au/terms-and-conditions).

Initial setup downloads the pinned Python dependencies. The synthetic demo runs without any external data credentials. The launcher starts a local server; leave its terminal open and press Ctrl+C to stop. Subsequent runs reuse your private `runtime/` data.

**Open without installing:** `docs/Property_Risk_Architecture.pdf`, `docs/architecture_viewer.html`, and `examples/output/demo-report.html` are standalone deliverables.

### Manual commands

From this folder, using a Python 3.12/3.13 terminal:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m riskengine init
python -m riskengine demo
python -m riskengine serve --desktop
```

Use `python3` in place of `python` if that is how your compatible interpreter is named. Do not run the supplied Linux `.venv` from another computer: the ZIP does not include an environment and setup creates your own.

## What is built

| Capability | Behaviour in this release |
|---|---|
| Case workspace | Property, buyer, price/loan, assumptions, assessment date, requirements and immutable case versions |
| Ingestion | Bounded ArcGIS, Socrata, CSV, XLSX, SDMX CSV, GTFS ZIP, generic JSON and file/discovery adapters; explicit unavailable, partial and access states |
| Source catalogue | 83 canonical catalogue entries derived from 96 supplied rows, with 13 exact layer aliases reconciled; further semantic overlaps are retained explicitly |
| Required scope | 65 signal/check definitions and 20 rule families; every required check appears even when no evidence exists |
| Geometry | Coverage-first checks, correct declared coordinate systems, area overlap, boundary touch, uncertainty and outside-coverage handling |
| Finance | Decimal mortgage amortisation, remaining debt, dated rate resets, baseline cash flow, settlement sufficiency, reserve stress and explicit exit scenarios |
| Rules | Structured inspection/legal/insurance reviews, project milestones, deduplicated supply, supported opportunities and properly defined area context |
| Output | Separate known-concern priority, evidence-gap priority, confidence, coverage, findings, opportunities and evidence links |
| Reproducibility | Immutable input references and hashes; exact replay of the captured case/evidence under the same engine and rule manifest |
| Privacy | Bearer token resolves the tenant; case-scoped private evidence, document capture, output permissions and policy revocation |
| Operations | SQLite persistence, idempotent collection, source health, audit events, durable jobs, leases and bounded retries |

This release **does not contain 65 independently validated predictive models**. It contains 65 explicit assessment obligations: supported numerical checks execute; reviewed structured evidence can be evaluated; other questions remain `NOT_ASSESSED`. It does not predict capital growth or the probability of a flood loss. Live sources require valid access, rights, currentness and property scope. The source inventory is a configuration and review surface, not a claim that 83 complete national feeds are active.

## Architectural drawings and specifications

| File | Purpose |
|---|---|
| `docs/Property_Risk_Architecture.pdf` | Three vector drawings: end-to-end flow, components/deployment, evidence/security relationships |
| `docs/architecture_viewer.html` | Local browser viewer for the same drawings |
| `docs/ARCHITECTURE.md` | First-principles design, data flow, boundaries, determinism, trade-offs and scale path |
| `docs/INPUTS.md` | Input requirements, sources, contracts, acquisition and promotion workflow |
| `docs/COMPLETE_INPUT_REGISTER.md` | Every source and every required signal, with raw inputs and processing specifications |
| `docs/ENGINE_CONTRACT.md` | Executable payload kinds, rule behaviour, finances and spatial contracts |
| `docs/INGESTION.md` | Adapters, supported formats, pagination, caps, rights and collection failure behaviour |
| `docs/API.md` | API/storage contract, auth, documents, reviews, jobs and replay |
| `docs/OPERATIONS.md` | Local setup, source activation, jobs, backup, restore and safe extension |
| `docs/VERIFICATION.md` | Executed checks, actual results and unexecuted deployment/value gates |
| `reference/Original_Architecture.md` | Earlier broader architecture and implementation specification for context |

## Use your own property

Start from `examples/new_case_template.json`, or use **Case inputs → New case template** in the dashboard. Assign an unambiguous `property_id` and `case_id`. Confirm the address, unit and parcel before relying on spatial results. Enter only known amounts. Buyer-entered assertions are labelled as such; they do not prove legal ownership, survey accuracy or lender approval.

```bash
python -m riskengine import-case my-case.json
python -m riskengine import-observations MY-CASE-ID my-observations.json
python -m riskengine assess MY-CASE-ID --advance-as-of --output runtime/my-assessment.json
```

Use `examples/reviewed_observation_template.json` to create structured evidence. Uploads remain private, and importing a document never automatically certifies its claims. `--advance-as-of` explicitly creates a new case knowledge-time version so newly received private evidence can enter the assessment. Leaving the date unchanged preserves the original point-in-time question.

The CLI is an administrator interface. HTTP users cannot publish private uploads as reusable public observations. The desktop launcher opens a single-user browser session. API clients and shared workspaces can continue using bearer authentication.

## Collect inputs

```bash
python -m riskengine sources
python -m riskengine collect demo-house act_crime_statistics --bounds examples/kingston_crime_bounds.json --max-records 1000
```

ACT crime is the initially reviewed CC BY 4.0 source. Its published workbook covers 2014 Q1–2025 Q2; that is historical context, not a current 2026 safety rating. Other source contracts default to blocked retention/analysis rights until source-specific terms are recorded. `POLICY_REVIEW_REQUIRED` is an explicit source readiness result, not an empty dataset. See `docs/INPUTS.md` before activating further sources.

Capture and property assessment are different steps. A collection can be complete for the requested filter while property coverage remains unknown. The automatic integration path promotes only specifically supported hazard mappings with reviewed coverage, publication date, identity, currency, complete geometry and permissions. Other source rows are captured for typed normalisation or human review. A successful download alone cannot produce a favourable finding.

## Reproduce an assessment

```bash
python -m riskengine replay "ASSESSMENT-ID-FROM-THE-REPORT"
python -m pytest
```

`exact_match: true` means the whole stored structured result matches a replay of its original input bundle. Changes to the case, source evidence, rules or permissions cannot be substituted silently. This is decision replay; it does not assert that a government API will return the same data tomorrow.

## What remains outside the verified local build

- Real property completeness: inspections, title/lease interpretation, insurance quotations, survey evidence, household data and source rights require their actual inputs.
- National coverage: source implementations and mappings must be validated jurisdiction by jurisdiction. There is no universal Australian property-risk API.
- Automatic document extraction, valuation, shadow modelling, calibrated completion probabilities and loss modelling are not implemented.
- PostgreSQL/PostGIS, managed identity, cloud storage, distributed scheduling and production tenancy are an explicit later architecture. SQLite/local files are the tested backend.
- Windows and Docker launch files are supplied; execution verification in this build used Linux/Python. Dependency installation needs internet access. Container images are not bundled.
- The twenty original acceptance specifications are traced to executable tests where possible; the buyer usefulness study remains a separate unexecuted value gate.

Do not publish the local server or `runtime/` directory on the internet. The local operating-system account is trusted and can read its files. Production exposure requires the deployment and identity work specified in the architecture.
