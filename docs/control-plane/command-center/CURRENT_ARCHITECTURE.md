# GO Command Center — current architecture routing

Status date: 2026-09-14
Baseline main at creation: `8ffcde66d36c1bbf849218529ef015f6e81725af`

This document is the repository routing record for the **current Command Center architecture**. It is descriptive project context, not Execution Authority. Live state, Human Approval where required, fresh Signed Tasks, installed artifacts, durable records, and Signed Evidence remain authoritative for execution.

## Current architecture

The primary Command Center interaction path is **GitHub-native**:

```text
Boss / Eason
    -> ChatGPT / GitHub Connector
    -> untrusted Request PR in chenzhenxi1-sudo/go-control-tasks
    -> Command Center Bridge / deterministic policy gate / signer / Tasks Writer
    -> immutable Signed Task in the private tasks repository
    -> HK Agent polling the formal task channel
    -> narrow HK Executor
    -> Signed Evidence
    -> Command Center / ChatGPT verification and reporting
```

GitHub is the control transport, immutable review/audit surface, Task transport, and Evidence transport. ChatGPT is the primary human interaction layer. ChatGPT does **not** hold execution authority and must not directly control shell commands, signing material, Docker parameters, service lists, or executor parameters.

The formal HK Agent timer nominally polls every 60 seconds. Pickup delay within that normal polling window is not by itself a failure and must not be bypassed with direct executor invocation.

## Historical Web Command Center snapshot

`command-center/` is the **2026-09-11 historical / legacy snapshot** collected by PR #39. In particular:

- `command-center/source/web/` is archived Web Command Center source from that date;
- its Flask/Jinja chat/admin UI is **not the current primary Command Center product architecture**;
- `command-center/source/bridge/` is the exact Bridge that was installed at the snapshot time, not the current capability inventory;
- `command-center/config/`, `systemd/`, and `nginx/` are snapshot evidence from that collection time.

Do not start new Command Center product design from `command-center/source/web/` unless a human explicitly asks to revive or maintain the legacy Web surface.

Do not infer current Bridge capabilities from the 2026-09-11 archive.

## Current implementation and capability sources

Use these sources for current Control Plane reasoning:

1. `control-plane/boss-test-pr-live-integration-v1/` — installed TEST_PR integration lineage and contract.
2. `control-plane/boss-deploy-request-v1/` — current DEPLOY request capability source/contract.
3. `docs/control-plane/PR51_DEPLOY_CAPABILITY_CLOSEOUT_20260913.md` — installed DEPLOY capability closeout and its fail-closed state.
4. `docs/control-plane/hk-staging/` — current proven operation/runbook semantics for VERIFY, DEPLOY, ROLLBACK and topology boundaries.
5. `chenzhenxi1-sudo/go-control-tasks` — private GitHub control transport for Request/Task flow; repository contents remain proposals/evidence according to their object type, not blanket execution authority.

When repository documentation and observed live state disagree, stop and verify live state rather than silently promoting a repository snapshot to runtime truth.

## Capability status at this routing baseline

| Capability | Current routing status | Notes |
| --- | --- | --- |
| `HK_STAGING_VERIFY` | PRESENT / live-proven | Persistent Boss Request / Signed Task / Evidence path exists. |
| `HK_STAGING_TEST_PR` | PRESENT / live-proven | PR #50 acceptance records live install, E2E and independent blind retest PASS; caller supplies only the allowed PR number and Command Center resolves/binds immutable source. |
| `HK_STAGING_DEPLOY` | CAPABILITY PRESENT; the authorisation is **per Request** | Since 2026-09-17 there is no deploy switch. The authenticated `HK_STAGING_DEPLOY` Request is the Human Approval: its author, its platform `created_at` and the digest of its canonical content are the authorisation, and Command Center derives a one-time plan and authorisation from it. The deployed configuration declares that mode (`deployment_authorization: "request"`); setting it to anything else suspends deployments and nothing else. |
| Deployment plan | **DERIVED by the Command Center** | Since 2026-09-17 nobody registers a plan. A DEPLOY Request is the five common fields -- no `plan_id` -- and the Command Center derives the plan from facts it already holds (candidate admission, its root-owned live baseline, the candidate's sealed TEST_PR, and the CANARY and preflight Tasks its own Bridge signed), validates it, registers it atomically and reads it back before signing the Task. |
| Product-release declarations | **REMOVED from the deploy contract** | `three_end_ux`, `six_vertical_closed_loop`, `sealed_node` and `final_release` are no longer deploy gates. They are upstream product-acceptance verdicts, no machine process in this repository can produce them, and the live executor never read them. The technical fact `sealed_node` named is established instead by the signed TEST_PR of the exact candidate. Authoritative reason: `docs/project/CC_V1_SCOPE_20260916.md` and Issue #103's Authority Boundary -- CC validates deployability, not product desirability. |
| CANARY through Boss Request | **OPEN / INSTALLED** (channel revision `1.9.0-rollback-channel`; requestable since `1.6.0-canary-channel`) | A CANARY Request is the five common fields; the candidate image, its sealed package and the expected-current image come from the root-owned `/etc/go-command-center/boss-request-canary-baseline-v1.json`. It needs no plan and no switch, because it mutates no business runtime and is the evidence a plan must cite. |
| ROLLBACK through Boss Request | **OPEN / INSTALLED** (channel revision `1.9.0-rollback-channel`, installed 2026-09-17) | A ROLLBACK Request is the five common fields too, and names no deployment, no source Task, no image and no service: the Command Center derives the source from its own ledger -- the newest `HK_STAGING_DEPLOY` it published whose signed Evidence succeeded -- and reads the images to restore from that deployment's own record on the host. It needs no plan, because it undoes a deployment rather than producing one, but it is not read-only and it takes the same authenticated Request a deployment takes. The same source can be rolled back once. |

As of 2026-09-17 the host runs channel revision `1.9.0-rollback-channel`: the v4 action contract is the fixed six-item list (VERIFY / TEST_PR / DEPLOY / ROLLBACK / CANARY / CONTROL_PLANE_HEALTH), compared by whole-list equality, and the channel config declares `deployment_authorization: "request"`. ROLLBACK is therefore requestable, and a ROLLBACK Request is the only thing that undoes a deployment.

A future live capability change must update this routing document or supersede it with a newer current-state record.

## Request / Task / Evidence authority separation

- **Request PR**: untrusted human/AI proposal. Never Execution Authority.
- **Signed Task**: formal bounded execution authority after deterministic validation and applicable human approval.
- **HK Agent / Executor**: execution-side verifier and narrow action runner. The Agent is not an AI product agent.
- **Signed Evidence**: machine-verifiable execution result bound to the Task. It is not interchangeable with logs, chat output, or a Request PR.

A failed, expired, or dispatched Task is never reused. Retries require a fresh Task identity, nonce, timestamps, and signature according to the action-specific runbook.

## AI startup rule for Command Center work

For ChatGPT, Codex, WorkBuddy, DeepSeek, Boss GPT, or another agent working on Command Center:

1. Read this file first.
2. Read `docs/control-plane/command-center/README.md`.
3. Read the relevant current `control-plane/` implementation and HK action runbook.
4. Treat `command-center/` as historical evidence unless the task explicitly concerns the legacy Web snapshot.
5. Verify current `main` and current live state before making runtime or capability claims.

Never reconstruct the current Command Center architecture solely from PR #39, the legacy Web UI, historical chat context, or archived server snapshots.
