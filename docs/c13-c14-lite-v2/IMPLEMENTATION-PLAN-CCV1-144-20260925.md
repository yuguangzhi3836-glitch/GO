# CCV1-144 — CC / HK witness layer for C13/C14 Lite V2

> **Correction, added by CCV1-144A (2026-09-25, later the same day). Not a rewrite of
> this round's record — an annotation on it.**
>
> Two claims in this document about artifact bytes are **wrong**, and were disproved by
> a controlled experiment:
>
> 1. "the storage endpoint rejects the credential in every configuration" — it rejects
>    the *`Authorization` header*, not the credential. Python's `urlopen` follows the
>    302 and forwards `Authorization` to Azure Blob Storage, which then tries to read
>    it as an Azure credential and answers `401 InvalidAuthenticationInfo`.
> 2. "`ARTIFACT_BYTES_VERIFIED` is unavailable to CC and HK" — the correct
>    two-step download (ask for the redirect without following it, then fetch the
>    pre-signed URL with no `Authorization` header) **succeeds**, and the recomputed
>    sha256 equals GitHub's `artifact.digest` byte for byte.
>
> So the byte level is *achievable*; the table below records what was true of the code
> as it stood in this round, not a platform limit. `lite_artifact_fetch` (CCV1-144A)
> implements the correct fetch and `test_lw_artifact_fetch` contains a counter-test
> that reproduces this round's 401 if the naive single-step fetch ever returns.
>
> What *is* still true, and is the real blocker: neither host holds a credential whose
> repository selection includes `yuguangzhi3836-glitch/GO`, so neither can read even
> the run metadata. That is a **grant** problem, not a transport or code problem, and
> it is tracked in `IMPLEMENTATION-PLAN-CCV1-144A-20260925.md`.

- Task: `CCV1-144-C13-C14-LITE-V2-CONTROL-WITNESS-INTEGRATION`
- Branch: `cc/ccv1-144-cc-hk-witness-20260925`, **stacked on** `cc/c13-c14-lite-v2-github-backend-20260925`
  (PR #248). The stack is deliberate: this layer consumes PR #248's contracts, and #248's own scope is
  left untouched. This PR's diff is only the witness layer.
- Inputs, as defined by the task: PR #247 (design / fact baseline, not merged, not evidence) and
  PR #248 (GitHub execution backend). A synthetic lifecycle is never a real C13/C14 PASS.

## What was added

```text
control-plane/c13-c14-witness/
  lw_paths.py      one place that puts the backend's contracts on the import path
  lw_artifact.py   two-level artifact verification (metadata / bytes)
  lw_verifier.py   CC ReviewVerifier
  lw_witness.py    CC witness key, witness record, first-seen ledger
  lw_hk.py         HK lightweight AcceptanceWitness
  lw_publisher.py  controlled publisher (the only component that may touch a ledger task)
  lw_aggregate.py  FinalAcceptanceAggregator + FINAL_ROOT + human gate
  lw_schemas.py    generates schemas/*.json from the enforced field tuples
  lw_fixtures.py   synthetic fixtures, reusing the backend's fixtures
  test_lw_*.py     71 tests, including the 16 required tamper/boundary cases
  schemas/         cc_witness_v1, hk_witness_v1, first_seen_ledger_v1, final_acceptance_v1
```

## Boundaries that are enforced in code, not in prose

| Boundary | How |
|---|---|
| No parallel scheduler | the layer defines no cell/task registry or state machine; the publisher's only surface is `evidence_entry` / `gate_record` / `plan` |
| 14-Cell ledger stays authoritative | the publisher's output is re-validated by the repository's own `ci/round2/validate_ledger.py` |
| reviewer cannot write | the publisher returns the Issue comment payload `posted: false`; the reviewer holds no Issue scope |
| no cross-cell / no stale / no historical rewrite | `check_safety` refuses wrong cell, wrong task, wrong candidate, wrong ledger reference, replaced task, duplicate-identical (idempotent), conflicting duplicate, older-over-newer |
| CC/HK run nothing heavy | no AI, Docker, PostgreSQL or candidate execution; `lw_hk.HK_REFUSALS` records the refusals explicitly |
| nothing can deploy | `authorizes_any_action = false` everywhere, `auto_deploy = false`, and `ACCEPTED` must carry `gate = READY_FOR_HUMAN_AUTHORIZATION` |
| keys are separate and never leak | dedicated Ed25519 per role, distinct purposes; the private half is never returned, printed or serialised; only `key_id` + public PEM + purpose are recorded |

## The artifact-level finding, measured read-only from CC and HK

Inside a workflow run, using that run's own `GITHUB_TOKEN`, the artifact **metadata** level works: the
final PR #248 PoC run resolved its artifact by name, matched the GitHub-computed `digest`, and failed
**only** on the ZIP download.

From the two servers, with the credentials that are actually installed today:

```text
CC  /etc/go-command-center/keys/github-requests-reader.token
    GET /actions/artifacts/{id}       -> 404
    GET /actions/artifacts/{id}/zip   -> 404
    GET /actions/runs/{id}            -> 404

HK  /etc/go-hk-agent/keys/  has no GitHub API token at all
    (github-go-source-reader is an SSH clone key, not an API credential)
```

⇒ `ARTIFACT_METADATA_VERIFIED` and `ARTIFACT_BYTES_VERIFIED` are **both unavailable to CC and HK today**.
The 404 is GitHub's response for "not found or not permitted", so the precise cause is not distinguishable
from here: it is either a missing Actions-read scope on that token, or a token for a different surface.

The honest consequences, recorded rather than papered over:

1. `ARTIFACT_METADATA_VERIFIED = NO (from CC/HK)` — this is a **credentialing gap**, not a code gap.
2. `ARTIFACT_BYTES_VERIFIED = NO` — the storage endpoint rejects the credential in every configuration
   tested so far (inside the run with `GITHUB_TOKEN`, and from this workstation with the account token).
   It is classified `ARTIFACT_BYTES_UNAVAILABLE`, never faked.
3. No new heavy infrastructure is proposed for this. The task explicitly forbids reintroducing HSM / KMS /
   WIF / ECS / a third-party service / a registration authority, and none is needed: the fix is a scope
   on an existing credential, or an explicit Owner decision to accept the boundary.

## Keys and installation

```text
CC_WITNESS_KEY_INSTALLED = NO
HK_WITNESS_KEY_INSTALLED = NO
```

No key was generated, copied or installed on any host. The signing path is fully exercised with
deterministic ephemeral test keys, and `WitnessKey.from_private_pem` exists for the day an authorised
key is installed. Nothing is written to CC or HK: `CC_TOUCHED = read-only probe`,
`HK_TOUCHED = read-only probe`, `LIVE_TOUCHED = NO`.

## Why the Issue writeback is "wired" but not "posting"

The ledger half is fully implemented and re-validated by the repository validator. The Issue half is
deliberately reduced to a prepared payload: giving the reviewer workflow `issues: write` would undo the
separation the task asks for. The payload carries exactly the nine fields the task lists
(`cell_id`, `task_id`, `candidate_sha`, `github_run_id`, `ai_execution_id`, `verdict`, `ROOT`,
`artifact`, `review timestamp`).

## Acceptance

```text
14_CELL_LEDGER_PRESERVED            = YES
ISSUE_WRITEBACK_WIRED               = YES (ledger) / PREPARED (issue comment, not posted)
C14_BACKEND / C13_BACKEND           = READY (PR #248)
CC_REVIEW_VERIFIER                  = READY
CC_WITNESS_LEDGER                   = READY
FINAL_ACCEPTANCE_AGGREGATOR         = READY
HK_ACCEPTANCE_WITNESS               = READY (code only, not installed)
FINAL_ROOT_RECOMPUTABLE             = YES
HUMAN_GATE_ENFORCED                 = YES
AUTO_DEPLOY                         = NO
ARTIFACT_METADATA_VERIFIED (CC/HK)  = NO  (credentialing gap, see above)
ARTIFACT_BYTES_VERIFIED             = NO  (storage endpoint refuses this credential; classified, never faked)
CC_WITNESS_KEY_INSTALLED            = NO
HK_WITNESS_KEY_INSTALLED            = NO
```

Verdict for the round: `IMPLEMENTED_NOT_INSTALLED`, with one credentialing gap
(`ARTIFACT_METADATA_VERIFIED` from CC/HK) that blocks a real CC/HK witness until it is resolved.
