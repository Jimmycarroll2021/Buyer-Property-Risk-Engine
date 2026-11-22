# Five-trial explanation repair candidate

Preview: http://127.0.0.1:8145/weekend. The frozen source/web/config/examples root is `runtime/final-feedback-candidate`, with its own sample database. Existing previews were preserved. These are internal checks following the [last two external reports](2026-11-22-last-two.md), not new participant results.

New captures use `weekend-buyer/3`. The recorded assumptions now explain V1 Yes/No/Unknown consequences, known finances alongside missing property evidence, the declared 15%/10% resale stress and cash after sale already funding negative equity. The screen and printable report show cash immediately before sale and an explicit “Search stopped at AUD …; higher offers untested” endpoint heading. Financial formulas, thresholds, storm rule version and bid-policy math are unchanged. Both v1 and v2 historical studies remain supported, with five complete pre-change result hashes pinned for each version.

Executor checks on 22 November 2026:

- Full suite: **357 passed**, one existing Starlette/httpx deprecation warning, 31.49 seconds. Command: `.\.venv\Scripts\python.exe -m pytest --basetemp runtime/final-feedback-tests`.
- Browser: **18 recorded runs passed**, covering all five household journeys, Belconnen resale/revised-cash reconciliation, Braddon Unknown/No/Yes and revised known cash, endpoint headings, property hints, save/exact replay/print, mobile width, delayed responses, stale-response rejection and 503 recovery. Command: set `PLAYWRIGHT_MODULE=C:/Users/Jimmy/.codex/skills/gstack/browse/node_modules/playwright-core`, then `node scripts/weekend_feedback_browser.cjs`. Receipts and screenshots: `runtime/final-feedback-browser`.
- The browser run saved one fictional Braddon worksheet in the isolated candidate database. No shared prior-preview worksheets were touched. The independent verifier owns further candidate database writes after executor handoff.
- The initial scoped run found a new test's literal decimal-format expectation differed from the model's existing eight-place formatting. The assertion now compares decimal value; no product formatting or threshold changed. The subsequent full suite passed.
- Updated participant briefs use the new preview URL; their ZIP contains the five corresponding Markdown files. Historical UAT receipts remain intact.

Runtime candidate manifests and verification handoff are in `runtime/final-feedback-evidence`. Executor results are pending independent exact-candidate verification and coordinator acceptance. No commit, push or release was performed at this checkpoint. Picker/expand-control friction remains reported but not causally diagnosed. No post-repair external trial or sourced resale prediction is claimed.
