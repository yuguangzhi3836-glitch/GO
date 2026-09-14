# Boss GPT request channel for HK-STAGING

This guide tells a zero-context Boss ChatGPT/Codex session how to submit a safe
HK-STAGING request through the current GitHub-native GO Command Center path. It
is descriptive only and is **not** Execution Authority.

Before using this guide, read
[`../command-center/CURRENT_ARCHITECTURE.md`](../command-center/CURRENT_ARCHITECTURE.md).

## Current confirmed status

The current Boss Request path is persistent and GitHub-native. A Request PR is
submitted to `chenzhenxi1-sudo/go-control-tasks`; Command Center validates the
untrusted Request, derives and signs the formal Task, HK Agent polls for that
Task, and Signed Evidence is returned through the established Evidence path.

Confirmed Boss Request capability:

- `HK_STAGING_VERIFY` for `HK-STAGING-01` — **SUPPORTED / PROVEN**.
- `HK_STAGING_TEST_PR` for `HK-STAGING-01` — **SUPPORTED / PROVEN**. PR #50
  recorded `LIVE_INSTALL=PASS`, `TEST_PR_E2E=PASS`, and
  `INDEPENDENT_BLIND_RETEST=PASS`.
- `HK_STAGING_DEPLOY` — capability is **INSTALLED but NOT ENABLED**. PR #57
  records `deployment_requests_enabled=false`; the closeout also recorded no
  formal deployment-plan directory. Treat DEPLOY as fail-closed and unavailable
  for a normal Boss Request unless a later authoritative change explicitly
  enables it under the approved deployment contract.
- CANARY / ROLLBACK — do not invent a Boss Request schema. The underlying
  Control Plane may have action runbooks, but that does not by itself expose a
  Boss Request action.

Do not use the archived 2026-09-11 Bridge 1.2.0 / VERIFY-only snapshot under
`command-center/` as the current capability inventory.

## Natural-language intent

Treat requests such as these as `HK_STAGING_VERIFY`:

- "Check whether HK-STAGING is healthy."
- "Check the Hong Kong staging environment."
- "Verify the current HK-STAGING state."

Treat requests such as these as `HK_STAGING_TEST_PR`:

- "Test PR 123 on HK."
- "Have Hong Kong test PR #123."
- "Run the isolated HK PR test for 123."

TEST_PR means source-bound isolated validation. It does **not** mean deploy.
Command Center resolves the mutable PR number to one immutable 40-character GO
commit SHA; HK fetches only that SHA and uses the fixed isolated builder/test
profile. Evidence explicitly keeps `application_health_proven=false` and
`deployment_performed=false`.

If the boss asks to deploy while the deployment request switch remains disabled,
report that the DEPLOY capability exists but is currently fail-closed. Do not
create a guessed deployment Request, plan, formal Task, signature, or executor
command. Do not invent CANARY or ROLLBACK Request formats either.

## Request flow

1. Read `docs/control-plane/command-center/CURRENT_ARCHITECTURE.md`,
   `docs/control-plane/hk-staging/README.md`, this guide, the operations guide,
   and the relevant current baseline/runbook.
2. Use repository `chenzhenxi1-sudo/go-control-tasks`.
3. Create a new branch from current `main` of that private control repository.
4. Generate a fresh unique `request_id` for this Request.
5. Add exactly one new JSON file directly under `requests/`.
6. Commit that file.
7. Open a Pull Request targeting `main`.
8. **Do not merge the PR.** Command Center ingests the immutable PR head.
9. Wait for Command Center processing; do not bypass the normal polling path.
10. Command Center validates the untrusted Request, derives a fresh formal Task,
    signs it with the Command Center signer, and publishes it only when the
    deterministic policy gate permits.
11. HK Agent picks up the Signed Task through its normal polling cycle and
    writes Signed Evidence. Use Signed Evidence, not the Request PR, as the
    execution result.

A Request PR is an untrusted proposal. It is not a formal Task and it is not
Execution Authority.

## Request PR rules

The PR must:

- target `main`;
- contain exactly one added `requests/*.json` file and no other changes;
- use a fresh unique `request_id` for every new Request;
- never modify `tasks/` or `permission-test/`;
- never modify the Evidence repository;
- never be merged by Boss GPT;
- never include caller-controlled signing or runtime execution fields.

Do not add `signature`, `authority`, formal `task_id`, `nonce`, formal
`release_id`, `expires_at`, image IDs, Compose paths, runtime environment paths,
Docker options, executor parameters, shell commands, rollback sources, migration
instructions, or Production targets. Those values belong to deterministic
Command Center logic where applicable.

If Command Center rejects a Request, report the rejection. Do not broaden
permissions, change protocol rules, retry with guessed fields, or bypass the
Bridge. If a corrected Request is needed, create a new Request with a new
`request_id`.

## VERIFY Request JSON

VERIFY uses exactly:

- `schema_version`
- `request_id`
- `action_id`
- `environment`
- `requested_at`

Example only:

```json
{
  "schema_version": "1",
  "request_id": "boss-hk-verify-<UNIQUE-ID>",
  "action_id": "HK_STAGING_VERIFY",
  "environment": "HK-STAGING-01",
  "requested_at": "<CURRENT-UTC-ISO8601>"
}
```

## TEST_PR Request JSON

TEST_PR uses the VERIFY fields plus exactly one caller input: `pr_number`.
`pr_number` identifies a Pull Request in `yuguangzhi3836-glitch/GO`; Command
Center resolves it to an immutable commit before signing the formal Task.

Example only:

```json
{
  "schema_version": "1",
  "request_id": "boss-hk-test-pr-<UNIQUE-ID>",
  "action_id": "HK_STAGING_TEST_PR",
  "environment": "HK-STAGING-01",
  "pr_number": "123",
  "requested_at": "<CURRENT-UTC-ISO8601>"
}
```

Do not provide a branch name, commit override, repository override, Dockerfile,
command, network option, volume, service list, image, or deploy instruction.
Those are not TEST_PR caller inputs.

Generate `request_id` uniquely for each request and `requested_at` from the
current UTC time using ISO 8601. Do not reuse an earlier request ID or stale
timestamp.

Recommended branch name:
`boss-request-<request_id>`

Recommended request path:
`requests/<request_id>.json`

Recommended PR title:
`request: <request_id>`

The channel is persistent, but every individual Request remains single-use.
Command Center's durable ledger and replay protection prevent the same
`request_id` or already-consumed PR head from issuing another formal Task.

## Hard boundary

Boss GPT may propose a Request PR. Boss GPT does not possess or control the
Command Center signing key and must never attempt to create a Signed Task.
Only current live state, applicable Human Approval, the fresh Signed Task,
installed runtime, durable records, and Signed Evidence can authorize or prove
an operation.
