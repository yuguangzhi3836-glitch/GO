# DEPTH48 admin-pagination business runtime update

The user requested updating the currently deployed DEPTH48 runtime with the
pagination and exact-order repair. This package starts from canonical main
286e294d92df4b7d1c0073116a8e628734abec6c and carries the exact application tree
cdf7a9beb45e749273fa816c745b6c1e1319a2d2 tested in PR62.
The application Dockerfile, dependencies and 8-service Compose are retained.
Only the admin operations route and shared admin renderer change.

Contents: complete source/runtime archive, Docker-loadable business image,
source fingerprints, image inspect/dependency snapshot, boot smoke result,
image-save/load restoration proof and SHA256/ZIP readback. Build success is not
deployment success. Current HK runtime pointer is unchanged until signed live
verification provides the new image/host/schema/time binding.

This is a replacement business image for the current 8 roles. It is not the
superseded DEPTH46 parent or R3 runtime. No migration or topology change is
required. Keep the actual current DEPTH48 image and fresh durable previous-state
record before any cutover. Do not restore old R3/DEPTH46 values over live state.
No automatic rollback, database reset, media deletion or Production operation.

Deployment handling: the user has expressed the intended update. Follow current
HK_STAGING_DEPLOY_RUNBOOK.md: exact-source acceptance, live drift preflight,
signed CANARY, fresh signed DEPLOY, pre-mutation durable record, fixed eight
services, signed DEPLOY evidence, then a separate signed VERIFY. Signing and
executor parameters belong to the existing Command Center. This package is not
a signed Task and contains no substitute shell deployment command.

Current repository evidence says the Boss deployment request capability is
installed but disabled and has no approved deployment-plan directory
(PR51_DEPLOY_CAPABILITY_CLOSEOUT_20260913.md). This session has no callable
Command Center signed deployment path. Therefore prepare/build is allowed;
actual cutover remains pending usable existing-channel evidence. Do not enable
or alter that channel as part of this business fix.
