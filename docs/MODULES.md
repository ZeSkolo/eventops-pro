# Seven modules

## 1. Registration system
POST /api/events/{event}/register reserves a seat atomically or queues a waitlisted participant. Preferences are event-scoped. Cancellation is refused after check-in. A cancellation promotes a queued participant without exceeding capacity. GET /registrations and /export.csv require event ownership.

## 2. Attendance tracker
GET /ticket.png is a personal QR ticket for confirmed participants. POST /checkin accepts the ticket token or eventops:-prefixed QR contents and records the organizer, method and time. Duplicate check-in returns the original check-in instead of creating another attendance entry. Camera BarcodeDetector is optional; manual token entry is the portable fallback.

## 3. Feedback collection
POST /feedback requires attendance and accepts a validated 1–5 rating and optional comment. One response is allowed per participant/event. Organizer reports show count, average, distribution and comments without account identifiers. No machine-learning sentiment model is claimed.

## 4. Resource sharing
Organizers add HTTPS links or upload PDF/TXT/PNG/JPEG/WEBP. Access to event resources requires confirmed membership (or ownership); files are delivered as attachments after authorization. Files are private disk storage, not a public upload URL. External links are not mirrored, crawled, or fetched server-side.

## 5. Task scheduler
Organizers assign to themselves or confirmed participants. Tasks have priority, due time, status, and dependencies. Participants see only their own assignments. Server-side transition rules block premature completion and invalid reopening of prerequisites. All due dates include an explicit timezone.

## 6. Participant dashboard
Combines registration state, agenda, announcements, ticket QR, personal task counts, attendance, feedback and certificate milestones. Organizer dashboard adds event-wide metrics and recent audit activity. Announcements are in-app, not SMS/email/push notifications.

## 7. Certificate generator
Individual/batch issuance validates attendance and optional feedback, then persists one certificate per user/event. A real PDF includes an unguessable verification QR link. The public verifier reveals minimal certificate fields. Revocation prevents new downloads and marks the public record invalid. Issuance is explicit, not automatic email delivery.

Open /openapi.json for the generated endpoint schemas. Dynamic application access is enforced by the backend—not merely by hiding frontend buttons.
