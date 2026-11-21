#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m riskengine init
.venv/bin/python -m riskengine demo
printf '%s\n' 'Sample report: runtime/demo-report.html' 'Opening the dashboard in your browser.'
exec .venv/bin/python -m riskengine serve --desktop

