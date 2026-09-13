# DEPTH41 cross-end journey acceptance

Status: IN PROGRESS; no complete journey PASS is asserted by this source commit.

The application subtree is copied byte-for-byte from DEPTH40 P0.3 canonical source b5732c02dd95092a63def7eaa0d2cf332b1e2996, as retained by parent CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912 (ZIP SHA256 421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a). Compatibility tooling is retained from d49465a56a7768bc4e657858272a597c5d1f05d6. Its old runtime image is NOT a build of this changed application.

Four effective files from DEPTH36R3 (7bd98db21ee950aeb91c12b296b1864b5a758c3f) and DEPTH37R2 (da6897706793fafd73d09cb56013586089733f4d) are restored using their original DELTA bytes. The retention check rejects other source changes unless listed with before/after SHA256 in business-fixes.json.

Fresh isolated CI only: random test credentials, new SQLite, no external application egress, background workers disabled, simulator payments explicitly confirmed in actual browser UI. Native-device, PostgreSQL, and complete frozen Node-gate evidence are separate requirements. Screenshots/network metadata contain synthetic accounts only; credentials/cookies/database/auth request and response bodies are excluded.

Release order remains: three-end real UX/login → six-vertical complete closed loop → sealed Node gate → final release. MERGE=NO. DEPLOYMENT=NO. Production=HOLD. No Hong Kong tasks, installations, environment changes or real bookings/payments are authorized here.
