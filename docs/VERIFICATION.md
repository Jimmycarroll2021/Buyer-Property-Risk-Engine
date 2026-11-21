# Verification record — Property Risk Engine v0.1.0

**Executed on 21 November 2026. This is a tested local implementation and an explicit record of its limits.**

## Executed checks

| Check | Observed result | Evidence |
|---|---|---|
| Full automated Python suite | **166 passed**, 0 failures; one Starlette TestClient/httpx deprecation warning | `tests/`, `test_summary.json` |
| Complete deterministic result replay | **Exact match** between saved result and replay of pinned case/evidence | `replay_check.json` |
| Required-check denominator | All **65** checks emitted; the synthetic case completes **14/65** and leaves **51** unresolved | `examples/output/demo-assessment.json` |
| Concern versus missingness | Synthetic case: known priority **3**, gap priority **3**, one separate opportunity | Same example result |
| Financial reference payment | $720,000 at 6% over 360 months → **$4,316.76/month** | `test_finance.py`, engine contract |
| Stressed payment | Same principal/term at 8% → **$5,283.10/month** | Same finance tests |
| Remaining principal | After 36 payments at 6% → **$691,805.30** | Same finance tests |
| Duration-bounded reserve | 6-month closing cash **$25,301.37**, no breach; 12-month closing cash **$5,602.74**, first $15,000 reserve breach in **month 10** | Synthetic result and finance tests |
| Tenant/case and permission boundaries | Bearer fail-closed, same-property case isolation, raw/derived restrictions and revocation, document access | `test_api_security.py`, `test_storage_security.py` |
| Ingestion reliability | Count reconciliation, bounds, duplicate pages, service errors, file types, dates, source rights, proxies and idempotence | `test_ingestion.py` |
| Spatial correctness | Covered non-overlap, positive area overlap, boundary ambiguity, unknown/outside coverage, CRS/units and vertical datum | `test_spatial.py`, `test_engine.py` |
| Storage/jobs | Immutable inputs/results, pinned replay after edits, lease recovery, retry bounds and stale-worker rejection | Storage and pipeline tests |
| Full dashboard functional flow | Actual JavaScript executed in JSDOM against a live local FastAPI server: connect, 65 checks, 83 source labels, 9 observations, finance SVG, case-save, assessment and report actions pass | `ui_check.json` |
| JavaScript and shell syntax | `node --check web/app.js` and `bash -n scripts/setup.sh` passed | Build execution |
| Source catalogue regeneration | Compiled configuration regenerated from the bundled catalogue with equivalent JSON, preserving reviewed activation and aliases | Build execution; `scripts/compile_inputs.py` |
| Fresh archive extraction | Initialised and ran the demo from a directory containing spaces; API/static assets worked and the assessment ID/replay matched the packaged example, using already installed pinned Linux dependencies | `release_check.json` |
| Input schemas | Draft 2020-12 validation and 12 normalised example fixtures passed | Schema-generation verification |
| Architecture drawings | Three Graphviz drawings rendered to SVG, PNG and PDF; every PNG inspected; combined PDF has three pages | Included drawing sources and rendered files |

The dashboard test is a functional DOM test, **not a completed full-browser visual test**. Chromium launch was attempted, but the execution environment denied the browser's process-singleton socket. No full-browser rendering, pixel/layout verification or mobile layout pass is claimed. The optional full-browser script is included for execution on a compatible machine.

## Live government input proof

The ACT crime collector freshly retrieved publisher catalogue metadata and the redirected workbook. It parsed and reconciled the requested Kingston scope:

- **874 observations**: 644 recorded-offence rows and 230 infringement-activity rows.
- **19 categories**, **46 quarters**, from **2014 Q1 through 2025 Q2**.
- Workbook size: **536,366 bytes**.
- Workbook SHA-256: `0302bade00e4158f7cad1413412c167eea9d6b13b6a4eaf02ed7dac40af011df`.
- Collection: `SUCCESS`; requested-scope completeness: `COMPLETE`.
- Property/mechanism coverage: **`NOT_ESTABLISHED`**.
- Exact source publication date for faithful historical availability: **not established**.

`live_collection_check.json` retains the successful fresh capture proof and earlier failed network/redirect attempts. `offline_collection_check.json` separately records an offline import. The older file was not relabelled as a fresh download. The freshly retrieved bytes match the included licensed workbook.

Primary source: https://www.data.act.gov.au/api/views/2egm-dieb.json . It identifies CC BY 4.0 and ACT Policing attribution. The data still ends at June 2025; a November 2026 download does not make it a current crime rating.

## Acceptance specifications

The original PR-AT-001–019 behaviours are mapped to executable test groups in `ENGINE_CONTRACT.md`. They cover identity ambiguity, empty/failed/unsupported coverage, denominators, public/private scope, precision, dates, contradictions, project deduplication, non-compensation, dependence, amortisation, duration stress, rental/exit arithmetic, access, rights, unreviewed extraction, job recovery and deterministic replay.

**PR-AT-020 is not claimed passed.** It requires real buyer cases, independent professional review and measured decision usefulness. Passing deterministic fixtures establishes implementation behaviour; it does not establish predictive calibration or buyer benefit.

## Implemented scope versus later work

The complete register classifies the 65 checks as **14 numerical**, **35 reviewed structured**, **12 context**, and **4 unavailable native analyses**. Numerical does not imply automatically collected inputs. Reviewed structured means a human supplies a reviewed claim; the application has not independently conducted an inspection or interpreted title law.

Only `act_crime_statistics` is activated in the released default registry. The 83 retained labels include aliases, discovery references and access-dependent inputs. The other contracts are not presented as complete live services. Automatic hazard promotion requires reviewed coverage, identity, currency, dates, positional uncertainty, complete source geometry and appropriate rights.

The following are supplied or designed but **not execution-verified here**: Windows/PowerShell launch, macOS launch, Docker, PostgreSQL/PostGIS migration, cloud deployment, managed identity, national parcel matching, automatic OCR/document extraction, full hazard loss models, valuation/price uplift, production security review, backup/restore drill and real buyer outcome validation.

## Reproducibility context

The proof ran with Python **3.12.14**, Shapely **2.1.2**, GEOS **3.13.1**, pyproj **3.7.2** and PROJ **9.5.1**. Financial arithmetic is Decimal-based. The structured result binds runtime versions, case, evidence, as-of time, required checks and engine/rule versions. A different runtime is a different replay context even when displayed values happen to agree.

The API and CLI use `runtime/riskengine.sqlite3`. Private credentials, actual runtime databases and ephemeral screenshots are excluded from the distributed archive. The example result and report contain synthetic property/buyer values only; the included crime workbook is the separately attributed public source asset.
