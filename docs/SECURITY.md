# Security boundaries

Implemented: PBKDF2-SHA256 (310,000 iterations + random salts), constant-time password comparison, HttpOnly/SameSite session cookies, hashed session storage, 12-hour expiry, CSRF tokens on authenticated writes, exact Origin checks, trusted hosts, forbidden cross-site writes, login/signup throttling, SQL parameterization, database foreign keys, and event-owner checks. Participant signup cannot select a role.

Uploads require organizer ownership, a content-length bounded request, a 10 MB file limit, allowed extensions, basic file-signature checks, randomized paths, and permission-protected attachment downloads. Chunked writes without Content-Length are rejected. This is NOT an antivirus or exhaustive file-format validator. PDF/image files can still contain malicious content: add malware scanning and retention policies before accepting untrusted production uploads.

Client-rendered user strings are HTML-escaped; external resource URLs are HTTPS-only without embedded credentials. No server-side fetching of resource links occurs. A restrictive CSP allows only local scripts/styles. CSV exports prefix spreadsheet formula-leading values.

Throttling is per-process/in-memory and relies on the immediate client address. Behind a proxy, configure a trusted proxy explicitly rather than trusting arbitrary forwarded headers. Multiple workers need centralized limits. There is no CAPTCHA, MFA, account recovery, email verification, or lockout administration.

Demo credentials are intentionally public and must not be used on a public deployment. Secure-cookie mode rejects a demo-seeded database. Fresh organizer passwords are read via getpass; environment files contain configuration, not secrets. Session cookies and ticket tokens must not be logged or shared. Ticket QR tokens can authorize a check-in only when presented to an authenticated event organizer.

Feedback reports omit names/email, but comments may self-identify; they are de-identified, not fully anonymous. Public certificate verification exposes the recipient name, event title, issue date, certificate ID and validity to anyone with the random link. Explain this in participant consent before collecting real data.

Audit records are not append-only outside the application or cryptographically signed. Backups, retention, breach response, external penetration testing, compliance and high-volume load testing remain the operator’s responsibility. Do not describe this release as security-certified or production-hardened.
