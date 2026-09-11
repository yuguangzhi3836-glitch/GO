# Boss GPT request channel for HK-STAGING

This guide tells a zero-context Boss ChatGPT/Codex session how to submit a safe
HK-STAGING verification request to GO Command Center. It is descriptive only
and is **not** Execution Authority.

## Current status

Boss Request Bridge `1.2.0` is installed on Command Center with a persistent
VERIFY request channel.

The channel is always available for fresh requests. It does **not** require a
pre-registered request ID, manual arming, or one-shot reconfiguration.

The only Boss Request action currently supported is:

- `HK_STAGING_VERIFY` for environment `HK-STAGING-01`.

The underlying Control Plane has separately proven VERIFY, CANARY, DEPLOY, and
ROLLBACK, but the Boss Request channel currently exposes **VERIFY only**. Do not
invent Request formats for CANARY, DEPLOY, or ROLLBACK.

## Natural-language intent

Treat requests such as these as `HK_STAGING_VERIFY`:

- "Check whether HK-STAGING is healthy."
- "Check the Hong Kong staging environment."
- "Verify the current HK-STAGING state."

If the boss asks to deploy, rollback, or run a canary, report that the current
Boss Request channel does not support that action. Do not create a guessed
Request, formal Task, signature, or executor command.

## Request flow

1. Read `docs/control-plane/hk-staging/README.md`, this guide, the operations
   guide, and the current baseline.
2. Use repository `chenzhenxi1-sudo/go-control-tasks`.
3. Create a new branch from current `main`.
4. Generate a fresh unique `request_id` for this Request.
5. Add exactly one new JSON file directly under `requests/`.
6. Commit that file.
7. Open a Pull Request targeting `main`.
8. **Do not merge the PR.** Command Center ingests the immutable PR head.
9. Stop and wait for Command Center processing.
10. Command Center validates the untrusted Request, derives a fresh formal Task,
    signs it with the existing Command Center signer, and publishes it only when
    the deterministic policy gate permits.
11. HK Agent executes the signed Task and writes Signed Evidence. Use Signed
    Evidence, not the Request PR, as the execution result.

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

## Request JSON

The current Request schema uses exactly these fields:

- `schema_version`
- `request_id`
- `action_id`
- `environment`
- `requested_at`

Generate `request_id` uniquely for each request. Generate `requested_at` from
the current UTC time using ISO 8601. Do not reuse an earlier request ID or stale
timestamp.

Example only — replace the placeholders for every live Request:

```json
{
  "schema_version": "1",
  "request_id": "boss-hk-verify-<UNIQUE-ID>",
  "action_id": "HK_STAGING_VERIFY",
  "environment": "HK-STAGING-01",
  "requested_at": "<CURRENT-UTC-ISO8601>"
}
```

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
Only the current live state, applicable Human Approval, the fresh Signed Task,
installed runtime, durable records, and Signed Evidence can authorize or prove
an operation.
