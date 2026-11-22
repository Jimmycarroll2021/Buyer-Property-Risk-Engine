# First-three feedback repair candidate

Candidate preview: http://127.0.0.1:8143/weekend. This sample uses a separate frozen web/config/example root and disposable database under `runtime/feedback-candidate`; the prior 8142 preview was not restarted. New participant briefs and their ZIP point to 8143. Old historical UAT receipts remain unchanged.

The new capture is `weekend-buyer/2`. It requires total first-year works to include urgent works and gives field guidance for an impossible subset. Storm mathematics (`three-storms/1.0`), numeric fixtures, solver eligibility and `storm-bid-grid/1` policy remain unchanged. Existing v1 captures still replay their exact original result text and object shape. Five complete original v1 results were compared to the pre-change `HEAD` implementation and their hashes are pinned in `tests/fixtures/weekend_v1_hashes.json`.

Executor evidence, 22 November 2026:

- Full test suite: **354 passed, 1 existing Starlette/httpx deprecation warning, 31.31 seconds**. Command: `.\.venv\Scripts\python.exe -m pytest --basetemp runtime/feedback-tests`.
- Browser: **14 recorded runs passed**, covering Ngunnawal, Weston and Kambah original/edit sequences; Belconnen and Braddon sibling picker paths; Braddon conditional evidence clearance; save, exact replay and print; mobile width; total/subset invalid input; inline unknown works; Amber eligibility and tested endpoint; named grid-price binding reason; specific disability gap/action.
- Delayed real response: old result hidden, loading names the current household/offer, picker disabled until completion. An injected input event during a pending request invalidates the response. A synthetic 503 produces a visible error with no stale result, followed by successful recovery. This establishes defensive behavior; it does not establish the cause of the tester's one picker failure.
- Reproduce browser check with local installed Playwright: `$env:PLAYWRIGHT_MODULE='C:/Users/Jimmy/.codex/skills/gstack/browse/node_modules/playwright-core'; node scripts/weekend_feedback_browser.cjs`. Use a disposable sample database because this writes one fictional assessment. Override `UAT_URL` and `UAT_OUTPUT` when needed.
- Browser receipts, screenshots and per-check summary are in `runtime/feedback-browser`; the runnable script is tracked. Brief ZIP was checked against the exact five current Markdown byte streams.

This is executor evidence, pending independent exact-candidate verification and coordinator acceptance. No commit, push or production release was performed. Belconnen and Braddon external trials remain unreported; simulated sibling regression coverage does not replace their feedback.
