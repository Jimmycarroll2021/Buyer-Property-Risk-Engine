# Five-persona external retest and search-price explanation repair

Jimmy supplied a retest of all five fictional persona briefs on the 8145 preview, identified as `weekend-buyer/3`. These are sequential trials by one tester, not five independent participants. This report paraphrases the supplied feedback; it adds no raw screenshots or measured usability scores. The tester reported the same decisions as before and confirmed that the revised works total, Amber explanation with the specific disability gap, sale-cash reconciliation and search endpoint wording helped.

| Persona | Reported sequence | Remaining observation |
|---|---|---|
| Ngunnawal | Green / Unresolved / Red | At the entered AUD 740,000 offer, the bid-search detail named AUD 600,000 as a tested offer. Its role as a separate grid offer was unclear. |
| Weston | Amber / Green / Green | The specific disability-cover shortfall and Amber explanation helped. |
| Kambah | Red / Amber / Red / Amber | The total including urgent works and the urgent subset helped. The AUD 580,000 qualifying offer and AUD 585,000 next higher failure remain distinct offers. |
| Belconnen | Red / Red / Amber | Cash before sale, cash after sale and negative equity were easier to reconcile; the negative-equity shortfall is already funded in cash after sale. |
| Braddon | Unresolved / Unresolved / Green / Red | The tester reported AUD 520,000 grid wording alongside an entered AUD 640,000. The supplied summary does not establish which structural-answer state displayed it. |

The tester also reported that the first three copied briefs still said “Other” first-year works. Direct inspection found all five canonical Markdown briefs and their ZIP already used total first-year works and matched each other before this repair. Stale local copies with the older label remain at `runtime/agent-uat-pack/01-ngunnawal.md` and `runtime/agent-uat-pack/03-kambah.md`; these prior runtime artifacts were left intact. The supplied report does not establish the precise origin of every copied brief. The canonical pack now points to the new 8147 preview and its ZIP was rebuilt from its five Markdown briefs. The audit receipt is `runtime/grid-copy-evidence/brief-audit.json`.

The repair changes explanation copy only. A new `weekend-buyer/4` capture version preserves stored result text and exact replay for versions 1, 2 and 3. Numeric rules, storm thresholds, grid search and bid policy are unchanged. Each new stored binding explanation distinguishes the entered offer from the bid search and names the actual source role:

- When no grid offer qualifies, Ngunnawal identifies AUD 600,000 as the lowest grid offer, alongside the entered AUD 740,000; it does not call that grid offer the next higher offer.
- When a maximum qualifies, Kambah identifies AUD 585,000 as the next higher grid offer above the highest qualifying grid offer, separately from the entered offer.
- When evidence is unknown, Braddon's binding explanation uses the actual first unresolved offer, AUD 820,000. The solver's separate AUD 520,000 final grid candidate did not supply that explanation and is no longer misidentified as its source.
- A known failed structural check applies at every price and short-circuits the search. Its explanation invents no grid-price evaluation and says that a price change cannot clear the property check.

Executor validation: the full suite passed **359 tests**, with one existing Starlette/httpx deprecation warning, in 26.43 seconds. Command: `.venv/Scripts/python.exe -m pytest --basetemp runtime/grid-copy-tests`. Focused regressions cover the entered/search-offer distinction, correct no-qualifier/next-higher/unknown/all-price roles, and exact historical results for versions 1–3. Version 3 snapshots were recorded before editing, including all five originals, revised Ngunnawal, and Braddon Yes/No states. Independent browser/exact-candidate verification remains a separate requirement; no new external participant trial, commit or push is claimed here.

Preview: http://127.0.0.1:8147/weekend. The source/web/config/examples snapshot is `runtime/grid-copy-candidate`, with an isolated sample database. The 8145 preview remains unchanged. Candidate identity and executor receipts are saved under `runtime/grid-copy-evidence`.
