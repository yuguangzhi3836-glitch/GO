# GO change-control policy

This policy defines the repository workflow for planned permanent changes to GO. It applies to humans and AI agents equally, including ChatGPT, Codex, and any future automation acting on this repository.

## Default rule

Every planned permanent change to product behavior, source code, tests, build logic, CI, deployment topology, deployment contracts, Command Center, Agent, Executor, infrastructure configuration, or operational documentation must leave a GitHub review trail.

The default workflow is:

`current main -> short-lived branch -> commits/tests -> Pull Request -> review -> merge`

Direct writes to `main` are prohibited for normal work, including convenience edits, probes, temporary test files, documentation fixes, or AI-generated changes. A Pull Request is a proposal and review boundary; it is never Execution Authority and never by itself authorizes deployment, rollback, migration, Production access, signing, or runtime mutation.

## Change classes

Every Pull Request must identify all applicable change classes:

- `PRODUCT_FEATURE` — new externally or internally observable product capability.
- `PRODUCT_FIX` — correction to existing behavior.
- `BUILD` — builder, dependency, packaging, image, or source-materialization change.
- `TOPOLOGY` — addition/removal/renaming of a runtime service role, image family, protected infrastructure component, or other deployment-topology change.
- `CONTROL_PLANE` — Command Center, Request Bridge, signing/publishing path, HK Agent, Executor, Task/Evidence schema, replay/authority logic.
- `INFRASTRUCTURE` — runtime infrastructure/configuration outside normal application code.
- `MIGRATION` — database/schema/data migration requirement.
- `TEST_ONLY` — isolated tests/acceptance tooling with no product/runtime semantics.
- `DOCUMENTATION` — descriptive documentation only.

If a change belongs to more than one class, list every class. A change must not be disguised as `DOCUMENTATION` or `PRODUCT_FIX` when it changes runtime topology, authority, migration behavior, or deployment semantics.

## Topology changes

HK-STAGING's currently proven business topology is versioned. Normal deployment may target only the currently approved/proven topology and must never accept an arbitrary caller-supplied service list.

Any candidate that adds, removes, renames, splits, or combines runtime service roles; introduces another business image family; changes a protected non-target; or otherwise changes the deployment topology must be classified as `TOPOLOGY` and follow `docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`.

A topology-changing Pull Request must not silently pass through the normal DEPLOY path. Until the new topology is separately reviewed, validated, approved, and formally proven, the correct result is `TOPOLOGY_CHANGE_REQUIRED` / HOLD.

## Runtime and source-of-truth discipline

GitHub is the durable source/review record for planned permanent changes, but GitHub documentation is not Execution Authority. Runtime truth must still be verified from the live environment before an operation.

An emergency runtime action taken to restore service does not automatically become a new software baseline. Any permanent emergency change must be reconciled back into a branch and Pull Request before it is treated as the maintained source for subsequent planned releases.

Do not deploy uncommitted or server-only application changes as a normal release.

## AI-agent self-constraint

AI agents are subject to the same workflow as everyone else:

1. Read the current repository instructions and relevant runbooks/contracts.
2. Start from the current intended base, normally `main`.
3. Create a short-lived branch.
4. Make the smallest coherent change with tests/evidence appropriate to its class.
5. Open a Pull Request describing scope, risk, topology/migration impact, validation, and unresolved gates.
6. Do not merge unless explicitly authorized by the responsible human.
7. Do not treat the Pull Request, chat history, or AI memory as runtime authorization.

No AI agent may write directly to `main` merely because it has permission to do so.

## Historical experiments

Experimental branches and Draft Pull Requests may remain as audit/history. Failed, abandoned, or superseded experiments do not need to be deleted, but they must not be treated as canonical source or deployment authority unless later materialized into a clean reviewed release candidate.

## Authority boundary

Execution Authority remains the combination of current live state, explicit Human Approval where required, fresh Signed Task, installed artifact/runtime bytes, durable records, and Signed Evidence.
