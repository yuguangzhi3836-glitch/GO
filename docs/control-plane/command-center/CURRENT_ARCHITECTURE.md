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
| `HK_STAGING_DEPLOY` | CAPABILITY PRESENT, **DISABLED** | PR #57 records the capability installed while `deployment_requests_enabled=false`; no formal deployment plan directory was created at closeout. This is not deployment authorization. |
| CANARY through Boss Request | **OPEN** (channel revision 1.6.0-canary-channel) | A CANARY Request is the five common fields; the candidate image, its sealed package and the expected-current image come from the root-owned `/etc/go-command-center/boss-request-canary-baseline-v1.json`. It needs no plan and no switch, because it mutates no business runtime and is the evidence a plan must cite. ROLLBACK is still not requestable. |
| ROLLBACK through Boss Request | NOT CLAIMED OPEN | Underlying formal rollback path exists; do not invent a Boss Request surface. |

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
