# EventOps Pro

**Seven event-management projects, built as one connected full-stack workspace.**

Registration → QR check-in → feedback → shared resources → team delivery → participant progress → verified certificates.

Created for Ahwan Adhikary. This is an advanced, runnable reference application—not a claim of enterprise certification or a managed production service.

## What is implemented

| Module | Working capabilities |
| --- | --- |
| Event registration | Event creation, confirmed seats, transactional capacity checks, FIFO waitlist promotion, registration preferences, cancellation safeguards |
| Attendance tracker | Personal QR ticket, authorized manual/token check-in, camera scanning where supported, duplicate detection, CSV export |
| Feedback collection | Attendance-gated 1–5 ratings, one response per participant, de-identified comment reports, rating distributions |
| Resource sharing | HTTPS links, permission-protected file uploads/downloads, file-signature checks, 10 MB limit |
| Task scheduler | Event-scoped assignments, priorities, deadlines, three-stage board, dependencies, overdue counts, permission checks |
| Participant dashboard | Personal registration status, schedule, announcements, QR ticket, assigned tasks, attendance/feedback/certificate milestones |
| Certificate generator | Attendance/feedback eligibility, individual and batch issuance, actual PDF downloads, QR verification, revocation, idempotent issuance |

### Shared foundation

- Python **FastAPI** API with generated OpenAPI documentation.
- Responsive HTML/CSS/JavaScript frontend; no JavaScript build toolchain needed.
- SQLite relational database, foreign keys, WAL mode, unique constraints, and atomic write transactions.
- PBKDF2 password hashing, hashed session tokens, HTTP-only cookies, CSRF validation, strict origin/host checks, login throttling, and event-owner authorization.
- Audit trail, CSV formula escaping, explicit timezone handling, content-security policy, and protected download routes.
- Fictional demo data, automated backend tests, Docker configuration, and manually triggered CI.

## Quick start — local demo

Requires **Python 3.11+** and internet access to install dependencies. Tested on Python 3.13.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts/manage.py seed-demo
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**. Use that hostname consistently: the origin protection defaults to localhost, not a mix of localhost and 127.0.0.1. `GET /api/health` is public. The generated API schema is at `/openapi.json` (no external-CDN documentation UI).

| Demo account | Email | Password |
| --- | --- | --- |
| Organizer | organizer@eventops.test | DemoEventOps!2026 |
| Participant | participant@eventops.test | DemoEventOps!2026 |

These are intentionally public **local demo credentials**, not real user credentials. All seeded names, statistics, attendance, tasks, and feedback are fictional. Sam and Riley are additional fictional participants. Seeding refuses to overwrite a nonempty database.

### Try the complete workflow

1. Sign in as the participant. Open **Discover events** and register for the workshop, or view the seeded summit ticket.
2. Copy the personal ticket token. Sign out and sign in as the organizer.
3. Select the same event. Open **Attendance**, paste the token, and check in.
4. As the participant, submit **Feedback**, access **Resources**, and update an assigned **Task**.
5. As the organizer, choose **Issue eligible certificates** in **Certificates**.
6. As the participant, download the real PDF. Its QR opens a public verification page.
7. As the organizer, revoke a certificate. Its verification page will show revoked, and future PDF downloads will be blocked.

You can run separate organizer/participant browser profiles or an incognito window for concurrent sessions. Only browser cookies—not localStorage—hold session credentials.

## Fresh workspace (no demo accounts)

```bash
python scripts/manage.py init-db
python scripts/manage.py create-organizer --name "Your Name" --email "you@example.com"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The organizer password is requested securely in the terminal. Participants create their own accounts in the UI. Signup cannot grant organizer privileges. Use a **new data directory** if you previously seeded the demo:

```bash
export EVENTOPS_DATA_DIR=/absolute/path/to/eventops-production-data
python scripts/manage.py create-organizer --name "Your Name" --email "you@example.com"
```

Windows users can set environment variables with `$env:EVENTOPS_DATA_DIR = "C:\path\to\data"`.

## Tests

```bash
python -m pytest -q
```

Tests create a temporary database, exercise real HTTP routes, and do not touch your working database. Coverage includes capacity/waitlist behavior, check-in idempotency, session/CSRF/origin security, event-owner boundaries, uploads, dependencies, feedback, PDF generation, certificate verification/revocation, CSV escaping, throttling, and draft visibility.

See `docs/TESTING.md` for UI checks and `docs/SECURITY.md` for security boundaries.

## Docker

```bash
docker compose build
docker compose run --rm eventops python scripts/manage.py seed-demo
docker compose up
```

Open http://localhost:8000. The named volume stores the database and uploads. `docker compose down` preserves it; do not use `down -v` unless you deliberately want to delete that data. Container startup does not seed demo accounts automatically.

## Configuration

| Variable | Local default | Purpose |
| --- | --- | --- |
| EVENTOPS_DATA_DIR | .data/ | Database and uploads; never mounted as public static files |
| EVENTOPS_BASE_URL | http://localhost:8000 | Exact allowed write origin and certificate verification URL |
| EVENTOPS_ALLOWED_HOSTS | localhost,127.0.0.1 | Comma-separated trusted hostnames |
| EVENTOPS_SECURE_COOKIES | 0 | Set to 1 behind HTTPS; adds secure cookies and HSTS |

A demo-seeded database is **rejected** in secure-cookie mode. For deployment use a fresh database, HTTPS termination, a persistent volume, backups, and explicit host/origin configuration. Read `docs/DEPLOYMENT.md` first.

**This dynamic application cannot be deployed as a static Firebase Hosting upload alone.** It needs a running Python backend. No cloud deployment, billing account, email delivery, or external paid service is set up by this repository.

## Repository structure

```text
app/main.py               API, authorization, transactions, schema, PDF/QR generation
web/                      Frontend, responsive styles, logo
scripts/manage.py         Fresh database, organizer creation, safe demo seed
scripts/smoke_browser.cjs  Browser workflow tests (requires Playwright and Chromium)
tests/test_workflows.py   Backend integration/security tests
docs/                     Architecture, modules, deployment, security, testing
requirements*.txt         Tested direct dependency versions
Dockerfile, compose.yaml  Container setup with persistent data volume
.github/workflows/        Manually triggered / pull-request test workflow
```

## Explicit limits

This release does **not** include payment processing, SMTP/email distribution, email verification/password reset, MFA, offline scanning, live video sessions, multi-tenant organizations, malware scanning, task editing/deletion, or high-volume infrastructure. Announcements and certificate availability are delivered **inside the app**; PDFs are downloaded rather than emailed. Camera QR scanning depends on browser support and has a token-entry fallback.

SQLite is appropriate for a small single-instance deployment and demos. For multiple API replicas, migrate to PostgreSQL and use shared file/object storage and centralized rate limiting. The audit table is operational, not cryptographically tamper-proof. Public certificate verification deliberately reveals a name and event title to anyone holding the unguessable link.

## Ownership and data

No CV, personal photos, real participants, private keys, or API tokens are included. Existing GitHub repositories and the live portfolio are not modified. Review your own privacy notice, participant consent, retention policy, and legal requirements before collecting real information.
