# Curated repository regression

On 22 November 2026 the publication executor ran the complete suite in the authoritative checkout after preparing the tracked candidate:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp runtime/repository-publication/pytest-temp
```

Result: **349 passed, 1 warning in 28.29 seconds**, exit code 0. The warning is Starlette's existing deprecation warning about its httpx test client. No assertion was removed or skipped. The legacy Jardine replay test now reads three exact public JSON fixtures under `tests/fixtures/jardine_public_replay`, making the suite independent of the excluded local runtime pack.

Engine, configuration, examples and frontend bytes were preserved from the accepted local source; publication changes add documentation, curated historical UAT artifacts, ignore rules, exact-byte Git attributes and the portable replay test fixture path. The root `file_manifest.json` identifies the published file bytes, excluding the manifest itself.

This executor result establishes the pre-push regression check. A separate verifier must inspect the exact commit and exercise a fresh clone, including the weekend buyer workflow. Historical UAT reports retain their original candidate identity and do not imply a production deployment.
