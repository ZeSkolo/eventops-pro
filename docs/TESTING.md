# Testing

`python -m pytest -q` uses temporary database files and real FastAPI HTTP routes. It never seeds or changes the operator’s data folder.

Backend tests cover password/session handling, CSRF/origin/host checks, role escalation rejection, atomic capacity/waitlists, check-in idempotency, feedback prerequisites, upload access/signatures, task dependencies, PDF issuance/verification/revocation, batch issuance, agenda time boundaries, CSV formula escaping, throttling, private static-data exclusion, and draft visibility.

For browser tests install Node, Playwright and Chromium. Start the app with a freshly seeded local demo at http://localhost:8000, then:

```bash
npm install --no-save playwright
# Ensure the chromium executable is on PATH, or set CHROMIUM_PATH.
node scripts/smoke_browser.cjs
```

The test performs local demo actions; it may create a synthetic participant account and task. Run it on a throwaway demo database, never production. Camera hardware capture is not automated. Token check-in, QR image generation, and PDF download are tested separately.

Review at desktop, 390 px mobile, and 320 px narrow mobile. Check navigation, tables, create-task/event modals, login errors, participant milestones, feedback forms, empty states, reduced motion and dark mode. Browser actions and view states are saved in the local test-results folder; it is ignored by Git.

CI is manually triggered or run for pull requests, not on ordinary pushes. This avoids starting CI jobs automatically just by uploading the repository. CI execution is subject to your GitHub account’s usage limits.
