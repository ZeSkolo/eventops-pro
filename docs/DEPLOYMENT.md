# Deployment guide

This repository does not create cloud services or configure billing. A static hosting service alone cannot execute this API.

1. Provision a Python/container host you control, with a persistent local data volume. Review its pricing separately.
2. Use a fresh EVENTOPS_DATA_DIR; NEVER seed the demo on a public host.
3. Set EVENTOPS_BASE_URL to the exact HTTPS origin, EVENTOPS_ALLOWED_HOSTS to the hostname(s), and EVENTOPS_SECURE_COOKIES=1.
4. Create the first organizer using scripts/manage.py create-organizer. Do not place passwords in the command line, .env, source code, or GitHub secrets unless a deliberately designed secret-management flow requires it.
5. Place a TLS reverse proxy in front of one API worker. Configure a maximum request size around 11 MB, short request timeouts, and trusted proxy settings. Do not expose the data folder or mount it into a web server’s document root.
6. Verify login, CSRF boundaries, uploads, every role, PDF download and QR verification at the actual public URL.
7. Schedule backups of the database AND uploads, then test restoring them. Use SQLite’s backup API while online instead of copying only the live .sqlite3 file during writes.
8. Document participant privacy/retention/consent, monitor disk usage and errors, and add malware scanning if uploads are untrusted.

The provided compose.yaml binds to 127.0.0.1 for local development. Do not make it Internet-facing without the above changes. A Docker image build is supplied; it is not evidence of a tested cloud deployment.

## Certificates and fonts

The Docker image installs DejaVu Sans for common Unicode names. On other hosts install /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf or adapt the font path. The PDF falls back to Helvetica where the font is absent; that fallback does not support every script. For broader languages, supply an appropriate font and validate shaping/layout.

## Backups

With the app stopped, copy the full data directory. For an online backup, use sqlite3.Connection.backup into a new file and copy uploads consistently. Do not publish backups to GitHub or include them in source ZIPs.
