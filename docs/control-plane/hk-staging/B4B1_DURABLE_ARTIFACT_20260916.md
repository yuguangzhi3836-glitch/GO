# B4-B1 — Durable candidate artifact and the artifact-identity re-contract

Round: 2026-09-16. Repository-side only. Nothing was installed, nothing was
deployed, and no host was contacted.

```
EPHEMERAL_ARTIFACT_BUG            CONFIRMED
CURRENT_FE0D2C_ARTIFACT_AVAILABLE NO
NEW_VERIFY_EXECUTED               NO
NEW_TEST_PR_EXECUTED              NO
LIVE_FIX_INSTALLED                NO
DEPLOY_READY                      UNKNOWN   (unchanged; 9 gates still UNKNOWN)
```

## 1. What was actually wrong

`hk_agent/test_pr.py` V2 built an image, inspected it for `built_image_id`, ran its
isolated checks, and removed the image in its `finally` block:

```
finally:
    docker image rm --force go-hk-test-pr:<commit>
```

So `sha256:fe0d2c36…` — the value the signed TEST_PR Evidence reports — is a
**build identity**, not a deliverable. Every TEST_PR gate passed and no copy of
those bytes existed anywhere. Two separate claims had been collapsed into one:

```
BUILD_IDENTITY_PROVEN        the artifact came from that source and was tested
ARTIFACT_DURABILITY_PROVEN   the built bytes still exist and can be delivered
```

The first was checked. The second was never asked, and the first was read as the
second. That is the defect.

**`fe0d2c…` is not recoverable.** A rebuild from the same source produces a
different image ID (Docker is not bit-reproducible), so a future deployable
artifact has to come from a new TEST_PR after this is installed. Nothing here
rewrites the historical Evidence; the signed result stays exactly as published.

## 2. The two options, and why the local sealed store was chosen

| | A — fixed private registry | B — fixed local sealed artifact store |
|---|---|---|
| TOUCHED_COMPONENTS | TEST_PR builder, registry client, DEPLOY, CANARY, plan, readiness | TEST_PR builder, artifact store, DEPLOY, CANARY, plan, readiness |
| NEW_SECRET_REQUIRED | **yes** — a registry credential on the HK host | no |
| NEW_EXTERNAL_SERVICE | **yes** — a registry | no |
| NEW_NETWORK_DEPENDENCY | **yes** — push at test time, pull at deploy time | no |
| TASK_SCHEMA_CHANGE | yes (`candidate_repo_digest` must be re-specified) | yes (replaced by the package content address) |
| EXECUTOR_CHANGE | yes (pull, and the digest rule) | yes (resolve + `docker load`) |
| CANARY_CHANGE | yes | yes |
| RECOVERY_BEHAVIOR | the artifact survives host loss; recovery needs the registry and credentials | the artifact is on the host; recovery needs the host's disk |
| ARTIFACT_DURABILITY | survives host loss | survives process death, not disk loss |
| BOSS_AUTONOMY | requires a credential the Boss must never handle | no credential, no human |
| FAIL_CLOSED_STRENGTH | digest ∈ `RepoDigests` and a real pull | content address + archive config digest + loaded `.Id` equality |
| INSTALL_COMPLEXITY | registry provisioning, credentials, egress | one directory, created 0700 and owned by the agent account |

Both options re-contract the frozen Hong Kong deploy contract, because the current
contract demands a registry digest whose suffix equals the image ID — a condition
no real candidate satisfies (§6/§7 of the round brief). Only A additionally needs a
new secret, a new external service and a new network path from the Hong Kong host,
and A would put a credential in the Boss's path or in an operator's hands.

**Chosen: B.** It is the closure of capability that already exists in this
repository — `packaging/canonical-runtime/package.py` already does `docker save`,
an archive-member manifest, `runtime-package.sha256` and a verified `docker load`
restore. B adds no daemon, no timer, no signer, no authority, no gate, no workflow,
no secret and no service.

## 3. What was built

### 3.1 The store (contract `go.sealed-artifact.v1`)

```
write side   control-plane/boss-test-pr-live-integration-v1/hk-staging/hk_agent/artifact_store.py
read side    hk-staging/source/executor/runtime/artifact_runtime.py
store        /var/lib/go-hk-artifacts/objects/<package_sha256>.tar
             go-hk-agent:go-hk-agent 0700 (directory) / 0600 (object)
```

The package is the raw `docker save` output; its own SHA256 **is** its identity, so
the content address is checkable by reading the file. Three independent checks
guard the image before it is allowed back into Docker:

1. the file's SHA256 equals the address it was stored under,
2. the archive's config blob hashes to the image ID (the bytes *are* that image),
3. `docker load` then reports `.Id == image_id`.

Everything a caller could use to widen this is fixed in the module: store root,
object directory, filename, Docker argv, tag, modes, size bound. The only inputs
are a validated 64-hex content address and an image ID that must match. Symlinked
objects, symlinked or group-writable stores, absent, empty, over-sized, tampered
and colliding objects are all refused rather than repaired.

### 3.2 TEST_PR Builder V3

`executor_version = "test-pr-v3"`. The seal happens **after every gate has
passed** and before the temporary tag is removed, so an image that failed a gate
never reaches the store, and an image that passed can no longer disappear with the
process. The Evidence carries `artifact_durability: "PROVEN"` and the
`artifact_package` block; the agent refuses to build that Evidence unless the
package names the image the build produced.

A new closed failure stage exists for the gap: `artifact_durability` →
`ARTIFACT_DURABILITY_FAILED` / `ARTIFACT_DURABILITY_REJECT`. It is deliberately
*not* `evidence_build` or `evidence_publish`, because reading it as either is what
hid the defect.

### 3.3 The artifact identity re-contract

The false rule is gone everywhere it existed:

```
before   candidate.repo_digest: <name>@sha256:<x>,  x must end with image_id[7:]
after    candidate.image_id:    sha256:<build identity>
         candidate.package_sha256: <64 hex>   (delivery identity, sealed package)
```

`candidate_repo_digest` no longer exists in the plan, the Task parameters, the Hong
Kong agent, either executor or the projection. A registry manifest digest is not an
image config ID, and a host-built candidate has none at all.

### 3.4 The projection still reads history

Six historical CANARY/DEPLOY Tasks in the real control bus are signed under the old
parameter name. The projection names that shape explicitly as `SUPERSEDED`:
exact, closed, never a wildcard. They stay readable and keep their Evidence, which
a policy hold would have silently erased. A shape that is neither the current one
nor that named one is still held.

### 3.5 Admission separates the two claims

`artifact_package` is a new optional field of `RELEASE_CANDIDATE_V1`:

```
{"durability": "PROVEN" | "NOT_PROVEN", "package_sha256": <64 hex> | null}
```

Admission reports `artifact_durability` and `deployability` separately from the
verdict, and refuses a candidate that claims a package the signed TEST_PR result
does not report, or that claims a package for a different image. The canonical
candidate records the truth:

```
admission      ACCEPT          (its identity is complete and unchanged)
durability     NOT_PROVEN      (test-pr-v2 deleted the image; the bytes are gone)
deployable     false           reason: candidate_artifact_package_not_proven
```

`PACKAGE_BINDING` in the readiness evaluator now requires `durability == PROVEN`
and `package_sha256` equal to what the plan approves — the gate where the ephemeral
artifact used to pass unnoticed.

## 4. Tests

| suite | local (Windows) | note |
|---|---|---|
| `boss-test-pr-live-integration-v1` | 74 run, 4 errors, 2 skipped | the 4 errors are the bash rollback tests, Windows-impossible and identical at HEAD |
| `command-center-candidate-admission-v1` | 79 OK | +11 new |
| `command-center-deploy-readiness-v1` | 63 OK | |
| `command-center-state-v1` | 197 OK | +2 new (SUPERSEDED) |
| `command-center-request-visibility-v1` | 49 OK | |
| `boss-deploy-request-v1` | 41 run, 18 errors | pre-existing `fcntl`/`getuid`/`O_NOFOLLOW`/symlink limits; the contract path itself was driven directly and passes |

The brief's regression list is covered by name:

| requirement | test |
|---|---|
| successful TEST_PR cannot claim a deployable artifact if publication failed | `test_evidence_refuses_a_build_identity_with_no_durable_artifact` |
| ephemeral image removed after TEST_PR cannot satisfy PACKAGE_BINDING | `test_the_canonical_candidate_reports_that_its_artifact_is_not_proven`, `test_a_candidate_that_says_nothing_about_durability_is_not_deployable` |
| durable publication only after all TEST_PR gates PASS | `test_a_build_whose_isolated_checks_fail_is_never_sealed`, `test_a_build_whose_profile_check_fails_is_never_sealed` |
| source identity must remain exact | `test_the_store_contract_is_pinned_not_guessed`, existing admission source tests |
| artifact tamper → FAIL | `test_a_tampered_package_is_refused`, `test_a_tampered_package_never_reaches_docker` |
| artifact identity mismatch → FAIL | `test_a_package_that_is_not_the_candidate_is_refused_at_load`, `test_a_load_that_yields_another_image_is_refused` |
| wrong source bound to a valid artifact → FAIL | `test_a_package_proven_for_another_image_is_refused` |
| no caller-controlled path / registry / image / argv | `test_a_caller_cannot_name_a_path_or_a_file`, `test_a_caller_cannot_choose_the_image_reference_shape`, `test_a_caller_cannot_supply_a_docker_argv_or_a_tag`, `test_the_executor_never_accepts_a_caller_supplied_path` |
| package SHA mismatch → FAIL | `test_a_tampered_package_is_refused` |
| loaded image ID mismatch → FAIL | `test_a_load_that_yields_another_image_is_refused` |
| symlink / path escape / oversized → FAIL | `test_a_symlinked_object_is_never_followed`, `test_a_symlinked_store_is_refused`, `test_a_caller_cannot_name_a_path_or_a_file`, `test_an_oversized_package_is_refused` |
| the two shipping halves cannot drift | `CrossSideContractTests` |

## 5. What is NOT done

```
LIVE_FIX_INSTALLED            NO   — nothing was installed anywhere
FRESH_VERIFY_EXECUTED         NO
NEW_TEST_PR_EXECUTED          NO
DURABLE_ARTIFACT_EXISTS       NO   — one can only come from a post-install TEST_PR
PACKAGE_BINDING               BLOCKED (the candidate has no proven package)
```

### The install this will need (prepared, not executed)

```
files        /opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py          (new)
             /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py                (V3)
             /opt/go-hk-agent-rebuilt/hk_agent/transport.py              (durability rule)
             /opt/go-hk-agent-rebuilt/hk_agent/deployment_actions.py     (package parameter)
             /usr/local/libexec/go-hk-deployctl                          (pins + flag)
             /usr/local/libexec/go-hk-deployctl-runtime/artifact_runtime.py   (new)
             /usr/local/libexec/go-hk-deployctl-runtime/{deploy,canary}_runtime.py
directory    /var/lib/go-hk-artifacts/{,objects}   go-hk-agent:go-hk-agent 0700
restart      none for the agent (oneshot per timer tick); the executor is invoked per
             Task, so no long-lived process carries the old code
rollback     restore the four agent files and the four executor files from the backup,
             and remove the two new files; the store directory is deliberately OUTSIDE
             the install/rollback unit, because what it holds is immutable artifact
             evidence and deleting it would destroy the only copy of a built candidate
```

### The other B4 blockers are untouched

```
B4_PACKAGE_BINDING   the mechanism now exists; the artifact can only be created by a
                     post-install TEST_PR
B4_RELEASE_GATES     OPEN — no exact-bound PASS exists for this candidate's tree
B4_CANARY_BASELINE   OPEN and newly recorded: hk-staging/source/executor/runtime/
                     canary_runtime.py still pins HEAD='0114_ext_truth_incident_hard'
                     while the candidate declares migration_head 0133_flight_change_plan.
                     Channelising CANARY needs BOTH the Request path AND that
                     0114 → 0133 baseline move; doing only the first is not CANARY READY.
B4_AUTONOMY          OPEN, unchanged: registering the plan, flipping the switch and
                     writing the switch provenance still require an operator on the
                     Command Center host
```

`deployment_requests_enabled` is still `false` and was not touched.

`PHASE_A_BLOCKER_COUNT_CLARIFIED`: the Phase A report's opening line says "two V1
blockers"; its own body lists four (package/artifact delivery, release gates, CANARY,
autonomy). The Phase A report is left exactly as written; the count above is the
correct one.

`DOC_CONTRACT_DRIFT` is still `YES` and was deliberately not fixed here: PLAN_CONTRACT
§approval still lists a `signature` field that `go_deploy_request.APPROVAL_FIELDS`
and the evaluator both define without one. It is a different drift from the one this
round fixes, and mixing the two would make both harder to review.

## 7. Revision B4-B1.1 — the store's ownership contract across the two uids

The store above had a defect that no test could see, because every test ran as one
account.

```
writer  go-hk-agent   systemd User=go-hk-agent / Group=go-hk-agent
reader  root          the agent invokes the executor as
                      /usr/bin/sudo -n /usr/local/libexec/go-hk-deployctl
```

Both halves compared an object's owner with **the reading process's own effective
uid**.  One operation therefore had two mutually exclusive requirements: a package
written by `go-hk-agent` could never be read by root, and a package root owned could
never have been written by the agent.  The install contract made it worse by
creating the store `root:root 0700`, which the writer would have refused outright.

```
SEALED_ARTIFACT_CROSS_UID_OWNERSHIP = CONFIRMED (before the fix)
```

What the contract says now:

* the trust anchor is the account **name** `go-hk-agent` / `go-hk-agent`, resolved
  from the account database on every check — never a numeric uid, and no fallback to
  the current process, to root, or to the file's own owner; an unresolvable account
  is a refusal (`*_ACCOUNT_UNAVAILABLE`), and a resolved uid of 0 is refused too;
* the writer additionally requires its own effective identity to be that account
  (`SEALED_ARTIFACT_WRITER_IDENTITY`) — sealing is authoring;
* the reader deliberately has no such requirement: root is a privileged **consumer**
  of the evidence, and consuming an artifact does not make root its author.  The
  reader never consults its own identity at all (asserted on its source);
* directory `0700`, object `0600`, ownership `go-hk-agent:go-hk-agent`, no symlinks,
  regular files, size bounded, content SHA256 exact, archive config digest exact,
  loaded `.Id` equal to the candidate;
* `seal()` now re-verifies the final stored object through the same primitive
  `resolve()` uses before it reports the package sealed, and publishes with an atomic
  no-overwrite hard link, so a planted or re-owned object can no longer be reported
  `PROVEN` and refused later at CANARY time.  An existing content address is verified
  for identity and never rewritten.

The install contract changed with it: the store is created as
`go-hk-agent:go-hk-agent 0700`, and an existing store whose owner or mode disagrees
is **not** re-owned — it is `STORE_OWNER_MISMATCH` / `STORE_MODE_MISMATCH`, an
operator review, because that directory is the only copy of every candidate ever
built there.  Install and preflight both read the owner back afterwards.

Pins realigned in the same commit: `go-hk-deployctl`'s `_CANARY_SHA256` and
`_DEPLOY_SHA256` had been computed over a working tree with CRLF line endings, so
they did not match the bytes the repository actually ships and no `_load_*` could
succeed.  Every runtime pin is now taken from the committed bytes and verified by
loading each runtime in an installed layout.

## 6. What a next round needs

1. Install the above on HK-STAGING-01 under a fresh, explicit authorisation, and
   create the store directory **owned by `go-hk-agent`** (not root).
2. Issue one fresh bounded TEST_PR against the canonical candidate's source. V3
   seals the image, and the new Evidence carries a real `package_sha256`.
3. Record that package in `CURRENT_CANDIDATE.json` so durability becomes PROVEN, and
   re-run admission + readiness.
4. Separately: RELEASE_GATES exact-bound evidence, CANARY channelisation (with the
   0114 → 0133 baseline move), and the autonomy blocker. None of them is closed by
   this round, and none of them should be claimed as closed.
