# Architecture

EventOps is a modular monolith: one frontend and one FastAPI process connect seven related workflows, instead of duplicating accounts and data across seven isolated apps.

```text
Browser (semantic HTML + CSS + JavaScript)
       | same-origin JSON API; HttpOnly session + CSRF
FastAPI routes / authorization / validation
       | parameterized SQL; BEGIN IMMEDIATE on writes
SQLite (WAL + foreign keys + unique constraints)
       | private upload folder, generated QR/PDF streams
Local persistent storage
```

## Key invariants

- A seat is counted only when registration status is confirmed. Registration transactions serialize the capacity check and insert, preventing a check-then-insert race.
- Cancelling a confirmed, un-attended registration promotes the oldest waitlisted registration in the same transaction. Ties are broken deterministically by registration ID.
- One participant has at most one registration, feedback response, attendance entry, and certificate per event (where applicable), enforced by database constraints.
- Every organizer-only route verifies the actual event owner; role alone does not confer access to other organizers’ events.
- Members may access resources and their own assigned tasks only after confirmed registration. Task transitions are checked server-side.
- Dependencies point only from newly created tasks to existing tasks in the same event, so no cycles can be created by supported endpoints. Reopening a prerequisite is blocked while a completed dependent remains.
- Certificate issuance requires confirmed attendance and optionally feedback. It is idempotent; revocation blocks future downloads and changes public verification.

## Storage and migrations

Schema v1 is created idempotently at startup; schema_version records the baseline. There are no later migrations in this release. Future incompatible schema changes must use explicit, versioned migrations and a database backup—not just alter this CREATE TABLE script.

Uploads are identified by random internal filenames. Original path components are never used. StaticFiles mounts only web/, never the data folder. Sessions store a token hash, not a reusable cookie value.

## Scaling

Use one API process for this reference deployment. SQLite transactions and WAL support overlapping requests within that instance. Do not share SQLite across container replicas or an NFS mount. PostgreSQL, object storage, distributed session/abuse controls, and a job queue are future upgrades, not implemented features.
