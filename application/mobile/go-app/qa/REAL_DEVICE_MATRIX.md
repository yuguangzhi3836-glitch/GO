# Sprint 2B Real Device QA Matrix

Release-blocking matrix. A row is PASS only on a physical device and a Staging backend using PostgreSQL 16 + Redis.

| Area | iPhone current iOS | iPhone previous iOS | Android current | Android previous | Gate |
|---|---|---|---|---|---|
| Fresh install / GO ID login | ☐ | ☐ | ☐ | ☐ | P0 |
| Refresh rotation after app restart | ☐ | ☐ | ☐ | ☐ | P0 |
| Secure storage survives process death | ☐ | ☐ | ☐ | ☐ | P0 |
| Search → prebook → authorize → book → capture | ☐ | ☐ | ☐ | ☐ | P0 |
| Network loss before payment authorization | ☐ | ☐ | ☐ | ☐ | P0 |
| Network loss after supplier book, before capture result | ☐ | ☐ | ☐ | ☐ | P0 |
| App kill during booking / recovery from Trips | ☐ | ☐ | ☐ | ☐ | P0 |
| Cancel → refund status → refund push | ☐ | ☐ | ☐ | ☐ | P0 |
| Change → supplemental payment | ☐ | ☐ | ☐ | ☐ | P0 |
| 365-day PROPERTY_ONLY Stay Credit | ☐ | ☐ | ☐ | ☐ | P0 |
| Push permission allow / deny | ☐ | ☐ | ☐ | ☐ | P0 |
| Booking-confirmed push opens correct order | ☐ | ☐ | ☐ | ☐ | P0 |
| Refund-completed push opens correct order | ☐ | ☐ | ☐ | ☐ | P0 |
| Compensation push opens financial detail | ☐ | ☐ | ☐ | ☐ | P0 |
| Check-in reminder | ☐ | ☐ | ☐ | ☐ | P1 |
| First review invite 2–10h window | ☐ | ☐ | ☐ | ☐ | P0 |
| Next app-open Quick Review if not reviewed | ☐ | ☐ | ☐ | ☐ | P0 |
| Completed review never triggers again | ☐ | ☐ | ☐ | ☐ | P0 |
| Universal/App Link cold start | ☐ | ☐ | ☐ | ☐ | P0 |
| Deep Link warm app | ☐ | ☐ | ☐ | ☐ | P0 |
| Offline banner + no offline financial mutation | ☐ | ☐ | ☐ | ☐ | P0 |
| Push dead-token revocation | ☐ | ☐ | ☐ | ☐ | P1 |

## Failure rules

- Payment/book ambiguity is never retried through a second connector. It enters reconciliation.
- Financial mutations are never replayed from a blind offline queue. The user must regain connectivity and obtain a current quote/consistency check.
- Non-secret device preferences may use local persistence; access/refresh tokens remain only in OS secure storage.
- Any P0 failure blocks TestFlight/Play Internal promotion.
