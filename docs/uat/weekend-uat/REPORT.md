# Five first-home buyers, 21–22 November 2026

**All five simulated buyer journeys passed.** Initial offers produced one green, one amber, two red and one unresolved decision. Chrome displayed the independently calculated results for all five original offers and all five revisions. The 464 comparisons covered repriced deposits, costs and LMI, mortgage payments, cash balances, income-loss runway, exit proceeds, bid limits, replay and version history. All amounts below are Australian dollars.

[Open the local worksheet](http://127.0.0.1:8142/weekend) · [Detailed comparisons](comparisons.json) · [Browser receipts](browser-receipts.json)

## What changed each decision

V covers property and cash vetoes. A combines interest, insurance and repair shocks. B removes the largest income and checks protection. C models a forced sale after 24 months. A grid qualifies both green and amber offers. A passing grid maximum leaves prices above the range untested.

| Household and initial offer | V / A / B / C | Buyer decision and next action | Highest qualifying grid offer |
|---|---|---|---|
| [Mira and Dan, Ngunnawal](ngunnawal-townhouse.png), $700,000 | Green / Green / Green / Green | **Green.** They retain $120,000 at settlement and have $220,877 net sale equity in the modelled exit. Keep the home on the shortlist and confirm costs and cover. | $1,100,000, top of the tested range |
| [Sam and Asha, Weston](weston-family.png), $760,000 | Green / Green / Amber / Green | **Amber.** Their $405,000 TPD cover falls $15,000 below the $420,000 threshold. At $740,000, required cover drops to $404,000 with the same deposit. | $950,000, top of the tested range |
| [Lee and Owen, Kambah](kambah-repairs.png), $620,000 | Red / Red / Green / Amber | **Red.** The $38,000 urgent bill leaves $4,000. One lean month costs $6,423.77. Obtain a works quote and reprice. | $580,000. The next $585,000 bid fails. |
| [Jules, Belconnen](belconnen-single.png), $600,000 | Green / Green / Red / Red | **Red.** $20,000 covers 3.18 months of a $6,286.14 shortfall against an assumed six-month income loss. Sale proceeds fall $40,473.40 short of clearing debt after sale costs. Compare a smaller loan and a larger cash buffer. | Every bid from $400,000 to $690,000 fails. |
| [Ruth and Mo, Braddon](braddon-downsizers.png), $640,000 | Unresolved / Green / Green / Green | **Unresolved.** They retain $101,500 but lack structural clearance. An engineer's finding controls the decision. | Unknown across $520,000–$820,000. |

## Revised worksheets

For each household the buyer changed all three editable money amounts, tested the offer, saved a second version, reopened the first version and exported it again. Its entire stored JSON matched the first export. Exact replay matched the saved hash for all five originals. The printable reports identified version 1 or 2 correctly across all ten saves.

| Household | Revised offer / cash before settlement / first-year works | What the buyer saw |
|---|---|---|
| Mira and Dan | $740,000 / $310,000 / $40,000 | **Red.** Their fixed deposit and repriced acquisition costs leave an $11,000 shortfall at settlement. |
| Sam and Asha | $740,000 / $342,000 / $6,500 | **Green.** Their existing death and TPD cover clear the revised $404,000 threshold. |
| Lee and Owen | $550,000 / $210,000 / $48,000 | **Amber.** The urgent works still cost $38,000. Settlement cash rises to $83,750 and the exit remains amber. With these revised assumptions $720,000 qualifies and $725,000 fails. |
| Jules | $450,000 / $160,000 / $9,000 | **Amber.** Sale equity is negative $31,230.05, but cash through the sale leaves $142,269.50. The higher cash buffer covers the modelled income interruption. The grid limit is $610,000 and $615,000 fails. |
| Ruth and Mo | $635,000 / $411,000 / $7,000 | **Unresolved.** The $112,625 settlement balance cannot resolve the structural evidence. Holding the original finances constant, leaving structural clearance blank returned unresolved, confirming clearance returned green, and confirming a serious defect returned red. |

Clearing Ngunnawal’s first-year works estimate returned **unresolved**. On a 390-pixel-wide mobile viewport the document width was 390 pixels. Chrome recorded zero uncaught page errors. [Mobile screen](mobile.png). Raw API captures remain local and are excluded from this repository.

## Verification and limits

The independent calculator discounted the scheduled payment stream to solve for the mortgage payment, stepped the mortgage balance forward to month 24, recomputed the cash paths and enumerated every price in each declared grid. Comparisons allow one cent on displayed money amounts. The full regression suite passed **349 tests**. Its single warning concerns Starlette's deprecated httpx test client. [Independent arithmetic](oracle.py) · [Historical regression summary](regression-summary.json)

All 15 integrated file hashes matched manifest SHA-256 `18d21601446fa512a2c7b6fff8ecda1f79add1767fac5bf677aff8a526dbff59`. The 176-file project snapshot, including public legacy-replay fixtures, matched the workspace before and after UAT. The five journeys used an isolated sample database. Separately, the buyer dashboard on port 8142 opened the worksheet, listed all five households and returned Ngunnawal's green result. [Candidate binding](frozen-binding.json) · [Final hash comparison](manifest-post.json) · [Local preview check](final-preview-smoke.json)

These are fictional household and property inputs. The exercise verifies model behaviour and browser workflows. Real-household usability, lender approval, insurance eligibility, market valuations and future outcomes remain unmeasured.


## Repository copy

This report records the earlier local UAT candidate. Original candidate hashes remain in the accompanying manifests. The publication commit additionally relocates the public legacy replay fixtures, adds handover and UAT documentation, and tightens ignore rules. New repository regression evidence is recorded in [the publication checks](../publication/REGRESSION.md). Raw request captures, server logs, databases and local API keys are excluded.
