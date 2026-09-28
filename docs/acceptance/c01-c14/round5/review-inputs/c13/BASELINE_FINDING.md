# R5-AUTH-01 baseline finding

Confirmed isolated HTTP control gap: a real GO_READ_ONLY administrator session with only admin:read reaches the content approval service. Approving a deliberately nonexistent snapshot returns 409 CONTENT_SNAPSHOT_NOT_FOUND instead of the required permission-first 403. Anonymous returns401, consumer403, supplier403. Approval row counts remain unchanged for every request.

Evidence: BASELINE_HTTP.xml (3 passed/1 failed), OBSERVED_*.json, reproducible probe_hotel_approve_permission.py and BASELINE_SOURCE_HASHES.json. Accounts use random synthetic passwords, real login JWT/database sessions and admin MFA; no principal/dependency overrides. The test mounts the real hosted_direct_booking router and follows current_principal→authenticate→admin_principal→service. It does not run full-main middleware or exercise any real environment. Auth/session fixture writes are expected; no hotel snapshot or approval business record is written. This proves permission-gate penetration, not an executed unauthorized approval against an existing business object.

Expected fix: reject missing approve permission before object lookup, independently check current actor authority in the service, and require server-held scope-bound hotel authorization for the snapshot. The supplied approver_role string or evidence URL alone cannot establish this authority. Freeze new source before independent revalidation. Baseline failures remain retained rather than rewritten as historical PASS.

ACCEPTANCE_MATRIX.json maps ten probe groups to frozen v1.1 requirements and retains their original required cases; it does not alter 305/1009 or treat these probes as a replacement denominator. Candidate remains null/NOT_ASSESSED until new source is fixed and reviewed.
