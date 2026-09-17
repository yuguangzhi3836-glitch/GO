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
- `HK_STAGING_DEPLOY` — capability is **INSTALLED**. Since 2026-09-17 the
  **authenticated DEPLOY Request is the authorisation**: there is no switch to
  open, no plan to prepare and no approval record to write. The Request is the
  five common fields, and Command Center derives the plan and a one-time
  authorisation from facts it already holds (the candidate admission record, its
  own root-owned live baseline, the sealed TEST_PR of that candidate, and the
  CANARY and preflight Tasks its own Bridge published and signed). See the DEPLOY
  section below for the exact sequence. Do not offer to prepare a plan, a gate
  declaration or an approval record: none of them is a Boss input, and none of
  them is even expressible.
- `HK_STAGING_CANARY` — **SUPPORTED / REQUESTABLE** since Command Center channel
  revision `1.6.0-canary-channel`. A CANARY Request carries the five common fields
  only: Command Center reads the candidate image, that candidate's sealed package
  and the expected current image from its own root-owned canary authority file, so
  a Request cannot name an image. Running it is read-only and isolated, it needs no
  plan, and it is **not** gated by the deployment authorisation — the canary is the
  evidence a deployment plan must cite, so it has to be obtainable before a plan
  can exist. It runs even while deployments are suspended. A canary older than 30 minutes cannot be used by a plan,
  so run it per candidate, close to the deployment.
- ROLLBACK — do not invent a Boss Request schema. The underlying Control Plane may
  have action runbooks, but that does not by itself expose a Boss Request action.

Do not use the archived 2026-09-11 Bridge 1.2.0 / VERIFY-only snapshot under
`command-center/` as the current capability inventory.

## Natural-language intent

Treat requests such as these as `HK_STAGING_VERIFY`:

- "Check whether HK-STAGING is healthy."
- "Check the Hong Kong staging environment."
- "Verify the current HK-STAGING state."

Treat requests such as these as `HK_STAGING_CANARY`:

- "Run a canary for the current candidate."
- "Canary the candidate on Hong Kong."

Treat requests such as these as `HK_STAGING_TEST_PR`:

- "Test PR 123 on HK."
- "Have Hong Kong test PR #123."
- "Run the isolated HK PR test for 123."

Treat requests such as these as the deployment sequence below:

- "Deploy the current candidate to Hong Kong staging."
- "Deploy this version to HK-STAGING."
- "Put the current version on Hong Kong."

Treating that intent means issuing **three** bounded Requests in order — CANARY,
then VERIFY, then DEPLOY — not one. They are described in the DEPLOY section.

TEST_PR means source-bound isolated validation. It does **not** mean deploy.
Command Center resolves the mutable PR number to one immutable 40-character GO
commit SHA; HK fetches only that SHA and uses the fixed isolated builder/test
profile. Evidence explicitly keeps `application_health_proven=false` and
`deployment_performed=false`.

If the boss asks to deploy, the Request is the authorisation: run the sequence in
the DEPLOY section, prepare nothing by hand, and do not ask for a switch to be
opened — there is none. If Command Center answers with
`deployment_authorization_mode_unsupported`, deployments are suspended on that host:
report it and stop. Re-enabling them is an operator's decision on the host, never a
Boss input. Do not create a guessed deployment Request, formal Task, signature, or
executor command, and do not invent CANARY or ROLLBACK Request formats.

Never write a deployment plan, and never declare a release gate. A plan is
derived by Command Center, and the four product-release declarations
(`three_end_ux`, `six_vertical_closed_loop`, `sealed_node`, `final_release`) are
**gone** from the deploy contract as of 2026-09-17: they are upstream product
acceptance verdicts, and Command Center validates deployability rather than
re-adjudicating product choices.

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

## DEPLOY Request JSON

```json
{
  "schema_version": "1",
  "request_id": "boss-deploy-request-EXAMPLE",
  "action_id": "HK_STAGING_DEPLOY",
  "environment": "HK-STAGING-01",
  "requested_at": "2026-09-17T00:00:00Z"
}
```

Five fields: that is the whole Request. There is **no `plan_id`**, and no image,
package, service, path, environment file, command, approval, signature or
executor option. A Request that still carries a `plan_id` is refused as a wrong
field set rather than read around it.

**This Request is itself the Human Approval.** Its author, as reported by GitHub,
is the approver; the platform's `created_at` is the approval time; and the digest
of its canonical content is what the approval is bound to, so the approved content
cannot be changed afterwards. That is why the deployment sequence has to be run in
this order:

```text
1. CANARY   for this candidate                (valid 30 minutes from completion)
2. VERIFY   the live host, as the preflight   (valid  5 minutes from completion)
3. DEPLOY   this Request                      (must be opened after 1 and 2)
```

Command Center refuses a DEPLOY Request whose approval is older than the canary
or the preflight, and it refuses one older than 15 minutes. A canary older than 30
minutes, or a preflight older than 5 minutes, is refused too. So the three
Requests belong to one short window, not to a plan you prepare in advance: the
canary and preflight are read-only, and only the third one deploys anything.

Between step 2 and step 3 nothing needs to be written, prepared or approved by
anyone. If a step is refused, report the machine-readable reason it came back
with and stop; do not retry a step blindly, do not re-use a consumed plan (a retry
needs a fresh canary), and do not construct a plan or an approval by hand.

`ROLLBACK` still has no Boss Request schema. Do not invent one.

## Hard boundary

Boss GPT may propose a Request PR. Boss GPT does not possess or control the
Command Center signing key and must never attempt to create a Signed Task.
Only current live state, applicable Human Approval, the fresh Signed Task,
installed runtime, durable records, and Signed Evidence can authorize or prove
an operation.
