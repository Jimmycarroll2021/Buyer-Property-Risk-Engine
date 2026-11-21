# Repository handover

The authoritative checkout is `C:/Users/Jimmy/Projects/property_risk_engine`, connected to https://github.com/Jimmycarroll2021/Buyer-Property-Risk-Engine on `main`. Work and commit here. `C:/Users/Jimmy/Documents/Risk Engine` is an older workspace and is not the source for this publication. The GitHub repository was public and empty before the initial import; no hosted history was replaced.

## Setup and run

Use Python 3.12 or 3.13. From a fresh clone:

```powershell
git clone https://github.com/Jimmycarroll2021/Buyer-Property-Risk-Engine.git
cd Buyer-Property-Risk-Engine
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pytest
.\scripts\start-offer-preview.ps1 -Port 8142
```

Open http://127.0.0.1:8142/weekend for the five fictional buyer journeys. For a private workspace use `start-windows.cmd`; this creates local private runtime state. Do not enter personal finances or documents into a shared sample preview. `.env` values are optional local configuration; source defaults resolve paths from the checkout. The existing local `.env` remains private and is not committed.

## Buyer tasks and verification

Give each participant only their own brief, or copy that brief inline if their agent cannot access a file. [All five tasks and dispatch guidance](uat/agent-uat-pack/BUYER_TASKS.md) links to [Ngunnawal](uat/agent-uat-pack/01-ngunnawal.md), [Weston](uat/agent-uat-pack/02-weston.md), [Kambah](uat/agent-uat-pack/03-kambah.md), [Belconnen](uat/agent-uat-pack/04-belconnen.md) and [Braddon](uat/agent-uat-pack/05-braddon.md). Keep [the moderator scoring key](uat/agent-uat-pack/SCORING_KEY.md) out of participant context.

[Historical browser UAT](uat/weekend-uat/REPORT.md) records five buyer journeys and 464 comparisons. [Model checks](uat/weekend-model-review/final_numeric_receipt.json) and [grid checks](uat/weekend-model-review/final_grid_receipt.json) retain their original source hashes. These are historical evidence, not claims of production deployment. [Publication regression](uat/publication/REGRESSION.md) records checks against the curated Git candidate. A separate verifier must bind the pushed commit and run independent checks.

## Preserved locally and excluded from Git

The complete original runtime workspace remains on this computer. `.env`, API keys, virtual environments, caches, SQLite databases and journals, raw request captures, server logs and private buyer documents are excluded. Only explicitly public replay fixture JSON is copied into tests; sample household inputs and screenshot receipts are fictional. No production deployment occurred.

The optional local Jardine seeding script still requires its original official source capture pack in `runtime/buyer-preview/jardine-3-9-kingston`; that raw capture pack is not distributed. The five weekend buyer examples work from tracked fixtures without it.
