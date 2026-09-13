# DEPTH36R2 support restoration — release HOLD

The DEPTH36 full backend run 34446465299 completed with 1,654 passing,
19 failing and 6 skipped tests. Eighteen failures involved omitted release,
deployment-template or governance support files. Those files are restored
byte-for-byte from the exact root members of the existing parent archive
`GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip`, SHA256
`8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`.
Existing candidate source files are preserved; no older business code is copied.
The candidate package records each recovered member and its SHA256.

The restored `CURRENT_*` and other legacy release records describe their dated
predecessors. Their historical deployment, migration and gate claims are not
DEPTH36 results or current Hong Kong facts. Use the DEPTH36R2 candidate manifest,
release gate and exact CI evidence to assess this candidate. Current AGENTS.md
authority and Hong Kong execution prerequisites continue to apply.

The remaining failure was a test that discarded its mobile bearer credentials
before expecting authenticated-consumer denial. It now checks anonymous 401
and authenticated-consumer 403 separately, including their error reasons.
Application authentication and authorization are unchanged.

Restored deployment workflows and configuration are source support only. This
acceptance does not execute them, deploy to Hong Kong, submit store builds,
perform database migrations or claim provider certification. Real browser,
PostgreSQL, native/device, sealed toolchain and final release gates remain open.
