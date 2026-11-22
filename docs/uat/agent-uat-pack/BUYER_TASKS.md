# Weekend buyer worksheet · five agent tasks

Give each agent **one household file** from the table. Each file includes the household's financial position, a sequence of changes to try, questions to answer as the buyer and a return form. Use fresh conversations so each agent encounters the decision unaided. The ZIP contains the five participant files. Send the chosen file to each agent individually.

| Household | Inspection | Decision to explore | Standalone task |
|---|---|---|---|
| Mira and Dan | Ngunnawal | Keeping a cash buffer when the funding plan changes | [Give this brief](01-ngunnawal.md) |
| Sam and Asha | Weston | What a lower price buys in disability protection | [Give this brief](02-weston.md) |
| Lee and Owen | Kambah | Where to stop bidding with urgent repairs due | [Give this brief](03-kambah.md) |
| Jules | Belconnen | Surviving an income gap and a forced sale | [Give this brief](04-belconnen.md) |
| Ruth and Mo | Braddon | What to do while an engineer's finding is outstanding | [Give this brief](05-braddon.md) |

[Download the five participant briefs](BUYER_BRIEFS.zip)

## Dispatch

1. Assign one persona and its file to each browser-capable agent. Ask the agent to act as that buyer, carry out every run, quote visible values and return its own decision. Allow about 10–15 minutes per household. Keep other briefs and evaluator material out of its context.
2. Use the [local sample preview](http://127.0.0.1:8147/weekend). Each browser needs network access to the sample instance. In a remote agent's browser, localhost resolves on the remote execution host. Supply an already-authorised, reachable sample preview or use a browser on the preview machine. A page heading without a populated picker and working results is insufficient.
3. Give each agent a fresh tab at the base URL. Tabs can test fictional edits concurrently. **Test this offer** calculates a preview. **Save assessment** writes a version to the sample workspace and its shared history. Limit these five tasks to preview and close each agent's tab when finished. A fresh browser profile alone does not isolate saved server records.
4. If you separately commission save/replay testing, use a dedicated disposable sample workspace with its own database for each writer. Begin at the base URL, save the original once, retain that exact link, edit and test, then save the next version within that worksheet. Reopen the original link and use **Replay saved version**. Record each version and visible replay message. On a conflicting or uncertain save, inspect the writer's own links/history before another attempt. Preserve existing worksheets and leave shared data in place.

## Reading the returns

Look for a traceable chain from the entered numbers to a labelled worksheet result to the household's decision. Record a calculation discrepancy, a misunderstood label, and a browser/access blocker separately if they arise. A completed run includes the original offer, each assigned variation and a buyer explanation of what would change the decision. Give credit for judgement supported by the visible figures, including a decision to walk away at a price the worksheet allows. A simulated buyer can expose unclear wording. Direct feedback from households would be a separate usability study.
