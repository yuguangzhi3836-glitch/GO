# Boss GPT request channel for HK-STAGING

This guide tells a zero-context Boss ChatGPT/Codex session how to submit an
HK-STAGING request to GO Command Center. It is descriptive only and is **not**
Execution Authority.

## Current V1 status

Boss Request Bridge V1 is installed on Command Center in publish-disabled mode
pending the first controlled live E2E. Request discovery and validation are
available; formal Task publishing is not yet enabled.

The only Boss Request action currently supported is:

- `HK_STAGING_VERIFY` for environment `HK-STAGING-01`.

The underlying Control Plane has already proven VERIFY, CANARY, DEPLOY, and
ROLLBACK, but Boss Request V1 has **not** opened CANARY, DEPLOY, or ROLLBACK.
Do not invent request formats for those actions.

## Natural-language intent

Treat requests such as these as `HK_STAGING_VERIFY`:

- "Check whether HK-STAGING is healthy."
- "Check the Hong Kong staging environment."
- "Verify the current HK-STAGING state."

If the boss asks to deploy, rollback, or run a canary, report that the current
Boss Request V1 does not support that action. Do not create a guessed Request,
formal Task, signature, or executor command.

## Request flow

1. Read `docs/control-plane/hk-staging/README.md`, this guide, the operations
   guide, and the current baseline.
2. Use repository `chenzhenxi1-sudo/go-control-tasks`.
3. Create a new branch from current `main`.
4. Add exactly one new JSON file directly under `requests/`.
5. Commit that file.
6. Open a Pull Request targeting `main`.
7. **Do not merge the PR.** Command Center ingests the immutable PR head.
8. Stop and wait for Command Center processing.
9. Command Center validates the untrusted Request, derives a fresh formal Task,
   signs it with the existing Command Center signer, and publishes it only when
   the local policy gate permits.
10. HK Agent executes the signed Task and writes Signed Evidence. Use Signed
    Evidence, not the Request PR, as the execution result.

A Request PR is an untrusted proposal. It is not a formal Task and it is not
Execution Authority.

## Request PR rules

For V1, the PR must:

- target `main`;
- contain exactly one added `requests/*.json` file and no other changes;
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
Bridge.

## Request JSON V1

Bridge V1 uses the following request fields:

- `schema_version`
- `request_id`
- `action_id`
- `environment`
- `requested_at`

Use a fresh unique `request_id` for every request. Generate `requested_at` from
the current time in UTC using ISO 8601. The installed Bridge enforces freshness;
do not reuse an old Request or timestamp.

Example only — replace the two placeholder values and do not reuse this
example as a live request:

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

## Hard boundary

Boss GPT may propose a Request PR. Boss GPT does not possess or control the
Command Center signing key and must never attempt to create a Signed Task.
Only the current live state, applicable Human Approval, the fresh Signed Task,
installed runtime, durable records, and Signed Evidence can authorize or prove
an operation.
