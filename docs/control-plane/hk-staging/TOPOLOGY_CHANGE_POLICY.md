# HK-STAGING topology change policy

## Purpose

HK-STAGING deployment topology is versioned. The currently proven topology is `HK_STAGING_BUSINESS_TOPOLOGY` version `1`, described in `DEPLOYMENT_TOPOLOGY_V1.json`.

Version 1 currently consists of one shared business image instantiated as eight business service roles, while `redis` and `caddy` remain protected non-target services. The number eight is a property of the current proven topology, not a permanent architectural invariant for GO.

This document is descriptive policy and is not Execution Authority.

## Normal deployment rule

A normal `HK_STAGING_DEPLOY` may proceed only when the candidate release is compatible with the currently approved/proven topology.

For topology version 1 this means, at minimum:

- the business service set remains exactly the approved eight roles;
- no caller supplies or expands the service list;
- all eight business roles continue to use the approved single-business-image release model;
- `redis` and `caddy` remain protected non-targets;
- no new business image family, protected infrastructure component, network/volume dependency, or service role is silently introduced;
- the existing migration and Production prohibitions remain unchanged unless separately reviewed under their own authority.

If a release requires a different topology, normal DEPLOY must fail closed with `TOPOLOGY_CHANGE_REQUIRED` (or an equivalent HOLD) rather than inferring, creating, deleting, or modifying runtime services automatically.

## What counts as a topology change

Examples include:

- adding, removing, renaming, splitting, or merging a business service role;
- changing the intended replica model when that changes deployment/runtime semantics;
- introducing a second or additional business image family;
- introducing a new scheduler, worker, gateway, queue, proxy, cache, or other runtime component;
- changing `redis` or `caddy` from protected non-target status;
- changing runtime networks, persistent volumes, ports, or inter-service dependencies in a way that affects the deployment contract;
- moving from the current single-image/multi-role release model to a multi-image release model.

A new Python module or business capability does not by itself require a topology version change if it runs entirely inside an existing approved service role and does not alter the deployment/runtime contract.

## Topology upgrade lifecycle

A topology change is a separate reviewed engineering change, not a hidden side effect of a normal product deployment.

The required lifecycle is:

1. Start from the current intended GitHub baseline and create a short-lived branch.
2. Open a Pull Request classified as `TOPOLOGY` under `docs/governance/CHANGE_CONTROL_POLICY.md`.
3. Define a new machine-readable topology version rather than overwriting the meaning of the old version.
4. Update all affected source/configuration and contracts together, including as applicable Compose, builder/release manifest, Executor allowlists, CANARY/DEPLOY/VERIFY/ROLLBACK behavior, durable deployment records, and Evidence bindings.
5. Run isolated/offline tests proving that the new topology cannot expand beyond its declared allowlist and that protected non-targets remain protected.
6. Perform a separately authorized first formal HK-STAGING E2E for the new topology, including post-deploy VERIFY and rollback eligibility/proof where required.
7. Only after that E2E succeeds may the new topology be recorded as the current approved/proven topology for normal deployments.

A topology Pull Request, its merge, or a documentation update does not itself authorize runtime mutation.

## Release-candidate binding

Future release-candidate metadata should bind the candidate to a topology identity/version in addition to its source and image identities. A candidate requiring a topology version different from the currently approved/proven version must not be routed through ordinary DEPLOY.

The intended release identity is therefore conceptually:

`source identity + built image identity/identities + topology identity/version + runtime/schema requirements`

The current implementation has not yet generalized the installed Executor to dynamically load topology contracts. The installed Executor still enforces the fixed eight-service scope. This policy preserves that current safety boundary while giving future topology versions an explicit upgrade path.

## Protected services

For topology version 1:

- `redis` is a protected non-target;
- `caddy` is a protected non-target.

A future proposal to mutate, replace, remove, or absorb either component is a topology/infrastructure change and requires separate review and proof. Normal product deployment must not mutate them.

## Authority boundary

Current live state, explicit Human Approval where required, fresh Signed Task, installed runtime bytes/artifacts, durable records, and Signed Evidence remain authoritative. GitHub source, contracts, Pull Requests, documentation, and AI memory do not by themselves grant runtime authority.
