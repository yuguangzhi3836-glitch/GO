> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# TD-J — one clone workspace per publication: repository fix, and the live install plan (NOT EXECUTED)

> Prepared 2026-09-16. Status: `REPO_FIX_COMMITTED` + `LIVE_INSTALL_PREPARED`.
> **Nothing in this file has been installed or executed on a host.** It exists so a
> human can approve an auditable, reversible change instead of editing live files
> by hand.

## 0. Handoff markers

```text
TD_J_ROOT_CAUSE_CONFIRMED          YES
TD_J_REPRODUCED_BEFORE_FIX         YES
TD_J_REGRESSION_PASS               YES  4 new tests; Linux gate: Ran 33 tests, OK
REPO_FIX_COMMITTED                 YES  cc/v1-finalization-20260914 3819b55a
LIVE_FIX_INSTALLED                 NO
FRESH_VERIFY_EXECUTED              NO
SIGNED_VERIFY_EVIDENCE_AVAILABLE   NO
DEPLOY_READY                       NO
LIVE_INSTALL_PREPARED              YES
LIVE_INSTALL_EXECUTED              NO

RELEASE_CANDIDATE_V1 admission      UNCHANGED (implemented, admitted candidate ACCEPT)
TEST_PR Builder V2                  UNCHANGED (test-pr-v2, TEST_PR_OK, deployment_performed=false)
VERIFY baseline                     UNCHANGED (DEPTH48 / collector 0133 / deployctl b9aea31e)
deployment_requests_enabled         false (unchanged, correct fail-closed posture)
```

## 1. Git identity

```text
repository   yuguangzhi3836-glitch/GO
branch       cc/v1-finalization-20260914          (PR #109)
PR #109      open / Draft / merged=false          unchanged: not merged, not marked ready, base not moved
START_HEAD   c894702be3ee7c1b9100bba1c4bc14acca4c8d90
END_HEAD     3819b55a954290677e8a7e24f8352be369e7e7a2

  control-plane/boss-test-pr-live-integration-v1/hk-staging/hk_agent/transport.py   +24 −10
  control-plane/boss-test-pr-live-integration-v1/tests/test_live_integration.py    +232 −4
  control-plane/boss-test-pr-live-integration-v1/SHA256SUMS                          3 lines
  control-plane/boss-test-pr-live-integration-v1/README.md                         +38 −2
```

No reset, no force-push, no rebase of `main`, no change to the PR base. The GitHub
reality was read before the first edit: PR #109 head was still `c894702be3ee`
(Draft, open, base `8610a4db`, 10/10 checks) — the expected baseline, so no drift
to report.

## 2. The defect, as it happened live — TD-J

On 2026-09-16T05:02:20Z the Command Center signed a fresh VERIFY against the
migrated baseline. The executor passed it: `go-hk-deployctl` returns
`SUCCESS`/`VERIFY_OK` or nothing, so a rejection could never reach
`stage=evidence_publish`. What was recorded instead:

```text
go-boss-request-verify-20260916T050220Z-1e244b2b26e9
  status             FAILED
  kind               EVIDENCE_PUBLISH_FAILED
  stage              evidence_publish
  reason_code        GITHUB_TRANSPORT_REJECT
  execution_attempted false      <- derived from the stage, not from the attempt
```

The cause is in `transport.py`, and it is deterministic:

```text
push_evidence(...)      repo = work/<dirname>; clone(evidence_repo, key, repo)
run_once(...)           for source in select_task_sources(folder, task_id):   # every Task, one pass
clone(repo, key, target)  git clone --depth=1 <repo> <target>
```

`git clone` refuses a destination that already holds a work tree. One pass
routinely claims more than one Task, and `select_task_sources` returns them
sorted, so `go-boss-health-…` is published before `go-boss-request-verify-…`. The
liveness record created `work/evidence` at 05:03:54; the VERIFY record, claimed
seconds later, had nowhere to clone. A failure record still published because the
failure path uses a different workspace (`work/evidence-failure`), which is why the
bus shows a signed failure for a Task whose executor succeeded.

`go-boss-health-…` before `go-boss-request-verify-…` is not luck: `h` < `r`.

## 3. Offline reproduction, before the fix

Reproducer: `tmp/tdj_repro.py <component-root>` — real `run_once` and real
`push_evidence`, with `git`/`clone` replaced by fixtures that carry real
`git clone` destination semantics, and two real task filenames from the 05:02Z
pass. No network, no repository, nothing written to `go-control-evidence`.

```text
task_order                 ["go-boss-health-20260916T050328Z-e869ddd14462.json",
                            "go-boss-request-verify-20260916T050220Z-1e244b2b26e9.json"]
clone_targets_attempted    ["tasks", "evidence", "evidence", "evidence-failure"]   <- the 2nd "evidence" is the collision
verify_executor_verdict    SUCCESS/VERIFY_OK - the VERIFY success record was built and signed
publications_attempted     health SUCCESS  published=true
                           verify SUCCESS  published=false  error=Reject GITHUB_TRANSPORT_REJECT stage=evidence_publish
                           verify FAILED   published=true   (dirname=evidence-failure)
processed                  1
rejected                   1
FIRST_EVIDENCE             PUBLISHED
SECOND_EVIDENCE            NOT_PUBLISHED
GITHUB_TRANSPORT_REJECT    YES
```

That is the live failure reproduced exactly, and it shows the failure is in
publication, not in the executor: the VERIFY success record was built and signed
and then had nowhere to land.

## 4. The fix

One helper, one call site.

```python
def _publish_workspace(work, dirname, data):
    identity = "%s\0%s" % (data.get("task_id", ""), data.get("nonce", ""))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return pathlib.Path(work) / ("%s-%s" % (dirname, digest))
```

`push_evidence` now clones into that workspace instead of `work/<dirname>`. The
identity is hashed, so no Task-supplied string can become a path component.

Deliberately unchanged — and asserted by tests:

```text
Evidence payload            record construction, status/executor_result/gate_results
Evidence signature          same Ed25519 envelope, canonical(signature-stripped)
Evidence signer             cfg["evidence_signing_key"]
Evidence repository/branch  cfg["evidence_repo"], `git push origin HEAD`
Evidence filename           evidence/<task_id>-<nonce>.json   (the durable identity)
Task ordering               select_task_sources sorting
Task signature / nonce      verify() and the ledger, untouched
replay / attempt budget      Ledger, untouched; one attempt per Task
duplicate protection        refuse_overwrite still reads the cloned tree
action allowlist            ALLOWLIST, untouched
environment binding         HK-STAGING-01 check, untouched
Executor contract           deployment_actions / test_pr, untouched
VERIFY / liveness contract  untouched
```

No daemon, timer, signer, authority, approval, gate or workflow was added. This is
a workspace fix, not an architecture change.

## 5. Reproducer after the fix

```text
clone_targets_attempted    ["tasks", "evidence-9d8bb90da97b3b51", "evidence-3f137f9c1405f47a"]
push_targets               ["evidence-9d8bb90da97b3b51", "evidence-3f137f9c1405f47a"]
pushed_files               health  -> go-boss-health-…-MWau2wbKoGY3TFw_0VYNj0LvECFc1fLh.json
                           verify  -> go-boss-request-verify-…-KxDkNoYC0mN8mZCHpIfgX0WeeCO2mjQE.json
processed                  2
rejected                   0
failure_evidence           []
FIRST_EVIDENCE             PUBLISHED
SECOND_EVIDENCE            PUBLISHED
GITHUB_TRANSPORT_REJECT    NO
```

## 6. Tests

Four regressions added to `tests/test_live_integration.py`
(`SamePassPublicationTests`):

```text
test_a_pass_publishes_liveness_then_verify_without_colliding
    the real ordering, three publications in one pass, an executor-level failure
    in the same pass, four distinct workspaces, no GITHUB_TRANSPORT_REJECT
test_more_than_two_records_publish_in_one_pass
    three publications, no failure record, one workspace each
test_the_record_itself_is_unchanged_by_the_workspace_fix
    payload, signature and signer unchanged; no "failure"/"retry_permitted" key
test_a_task_identity_never_becomes_a_path_component
    "../../etc/passwd" cannot escape; distinct identities never share a workspace
```

One existing test was updated, not weakened. `test_a_duplicate_record_is_refused_rather_than_overwritten`
asserted the literal workspace name `evidence-failure` — an internal name that the
fix necessarily changes. It now stages the previously published record into
whatever workspace it is handed (which is what a clone actually does) and still
requires `EVIDENCE_DUPLICATE_REJECT` with the original bytes left intact.

```text
LOCAL (Windows, managed venv)          Ran 33 tests  → 4 errors, 29 pass
   the 4 errors are the install/uninstall rollback tests, Windows-impossible;
   identical 4 at HEAD (Ran 29 tests → same 4), so nothing regressed
LINUX GATE (ubuntu-latest, GitHub)      Ran 33 tests  → OK
   HK agent failure closure (isolated): push 33 OK (6.261s) and pull_request 33 OK (8.771s)
CI for 3819b55a                        12/12 runs success
   (candidate admission, deploy readiness, deploy dry-run, deploy request entry,
    control state, state publication, request visibility, liveness producer,
    liveness request transport, HK agent failure closure; push + pull_request)
   the inlined YAML assertions of both in-path workflows were also run locally
   before pushing: HK failure closure PROVEN, candidate admission E2E PASS
```

## 7. Repository bookkeeping

`SHA256SUMS` (LF, two-space form) and the README's superseded-hash block both
follow the change; `sha256sum -c SHA256SUMS` validates 21/21 in the working tree
and from `git archive` of the commit.

```text
hk-staging/hk_agent/transport.py        6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0
                                     -> 340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8   (30908 -> 32155 bytes)
tests/test_live_integration.py          f59626419ba5d8da2b8430e1e1b3293d197cf19cc8d704a1fe842c982100e2fd
                                     -> d80ea8ce98afdf1cd9bc302d3d611b6e84d56ff07ca79f0f56b853e1730e07d1
README.md                               3de7dedcc5a4d431488de5e38aa04a6f00f8ae447bff2fab92d27968cefc7718
                                     -> fda58f9024938e00aef898ee82e98f191c842f9cb31a7ab93283b0439bb0060e
```

Two bookkeeping facts worth recording rather than silently "fixing":

* The README's previous block claimed the test file's committed value was
  `c4413d17…`; the value actually committed was `f5962641…`. The new block records
  the committed value as `was`, and says so.
* `tests/check_canonical_archive_manifest.sh` needs `perl`, which this Windows
  shell does not have. Its CR-byte check was run as a byte count in Python and the
  manifest was validated after `git archive` extraction, which is what the script
  does; the script itself was not run verbatim locally.

`deliverables/**` and `evidence/**` were not touched. The archived pre-PR50 copy of
`transport.py` under `hk-staging/source/agent/hk_agent/` is not the live file
(live sha matches the component copy, verified by read-only `sha256sum` on the
host) and was left alone.

## 8. Live install plan — NOT EXECUTED

```text
LIVE_FILES_TO_CHANGE (HK-STAGING, 47.239.57.40)
  /opt/go-hk-agent-rebuilt/hk_agent/transport.py
      now   6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0   30908 bytes  root:root 0644
      next  340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8   32155 bytes  root:root 0644

LIVE_FILES_CHANGED_THIS_ROUND     NONE
LIVE_SERVICES_TO_RESTART          NONE
LIVE_FILES_TO_RESTART             NONE
Command Center touched            NO
business runtime touched          NO
deployment_requests_enabled       unchanged (false)
migration / deploy / rollback     NONE
```

The live `transport.py` hash was verified read-only on the host during this round,
and it equals the component copy at START_HEAD — so the delta is exactly one file
and it was measured, not assumed.

Why no restart is needed: `go-hk-agent.timer` starts a **fresh** `--run-once`
process per tick and nothing imports the module from a long-lived process, so a
file replaced by atomic rename is picked up on the next tick. The replacement must
be complete before the rename, and any stale `__pycache__` entry must go, because a
cached `.pyc` could shadow the new source.

Method (same discipline as the Builder V2 install):

```text
1  read live pre-hash and mode           sha256sum /opt/go-hk-agent-rebuilt/hk_agent/transport.py
2  backup first                          /var/backups/HK-CHANGE-<STAMP>-tdj-evidence-workspace/
                                           transport.py.before   (hash re-verified == pre-hash)
                                           state.tsv / installed.tsv
3  stage beside the target               install -m 0644 <staged>/transport.py \
                                           /opt/go-hk-agent-rebuilt/hk_agent/transport.py.tdj-stage
4  verify the staged bytes               sha256sum must equal 340da98f…
                                         python3 -m py_compile with PYTHONPYCACHEPREFIX
                                           outside the agent tree
5  atomic replace                        mv -f transport.py.tdj-stage transport.py
6  drop stale bytecode                   rm -f /opt/go-hk-agent-rebuilt/hk_agent/__pycache__/transport.*.pyc
7  import smoke                          VERSION 0.5.7-rebuilt; _publish_workspace present;
                                         FAILURE_REASON_CODES 13 entries (unchanged)
8  post-install verification             sha256sum == 340da98f…; owner root:root; mode 0644
                                         go-hk-agent.timer still active; next tick Result=success
```

Preflight: the install asserts the live pre-hash is `6f329b2e…` and refuses
otherwise — the same fail-closed rule the shipped scripts use, but written against
the *observed* live state rather than the archived baseline. The shipped
`install/install-hk-agent.sh` is **not** usable here: its hash gates and
`test ! -e` gates describe the host before TEST_PR was installed. And
`install/install-command-center.sh` must never be run (it would roll the CC host
back to a version-3 bridge).

Post-install verification that may not be skipped:

```text
LIVE_FIX_INSTALLED            YES  (sha256 seen on the host)
FRESH_VERIFY_EXECUTED         only on a separate, separately approved Request
```

Rollback — one file, exact commands:

```sh
cp -p /var/backups/HK-CHANGE-<STAMP>-tdj-evidence-workspace/transport.py.before \
      /opt/go-hk-agent-rebuilt/hk_agent/transport.py
sha256sum /opt/go-hk-agent-rebuilt/hk_agent/transport.py     # must be 6f329b2e…
rm -f /opt/go-hk-agent-rebuilt/hk_agent/__pycache__/transport.*.pyc
```

Rollback touches no evidence, no Task, no ledger, no business container, and
nothing on the Command Center host.

Files and services this install must not change: `test_pr.py`, `core.py`,
`deployment_actions.py`, `agent.json`, the builder Dockerfile, the agent ledger,
the evidence repository and branch, the eight business containers plus caddy and
redis, the alembic revision, and the Command Center's bridge config, VERIFY
baseline and timers.

## 9. B3 / B4 after this round

```text
B3  no fresh signed VERIFY Evidence                    STILL OPEN
    root cause                              TD-J, confirmed and reproduced
    repository fix                          IMPLEMENTED / TESTED / COMMITTED (3819b55a)
    live fix                                NOT_INSTALLED
    fresh VERIFY                            NOT_RETRIED
    signed VERIFY evidence                  NOT AVAILABLE
    ⇒ VERIFY still FAIL; the last verified VERIFY remains 2026-09-13T03:43:27Z

B4  no deploy plan bundle                              STILL OPEN
    deployment-plans-v1/ holds only authority.pub + hk-evidence.pub;
    the readiness projection still reports deploy_readiness UNKNOWN for the nine
    gates that need a plan bundle

B5  deployment_requests_enabled=false                  UNCHANGED (correct posture)
```

Retrying VERIFY without installing the fix would very likely reproduce TD-J: the
liveness record of the same pass publishes first whenever a health Task is
claimable in the tick that claims the VERIFY.

## 10. NEXT_ACTION

```text
1  obtain Human Approval for the single-file HK install in §8   (the round stopped here)
2  install, verify the post-install hash and the next agent tick
3  then issue one fresh bounded VERIFY Request through the formal channel
4  confirm a signed VERIFY_OK Evidence exists; B3 clears only then
5  afterwards (independent of this round): build the deploy plan bundle for
   rc1-depth48-pr52-bd25d7ac to clear B4, re-run readiness, stop at DEPLOY_READY=YES
```

## 11. Left undone on purpose

`prepare_rollback_handoff` clones into a fixed `work/rollback-source-evidence`, so
it carries the same defect class for a pass that claims two ROLLBACK tasks. It was
not changed: this round's authorised scope is the evidence-publication workspace,
and ROLLBACK is not in the enabled Command Center channel, so the site is not
reachable today. It is recorded in `CC_V1_CURRENT_HANDOFF_20260916.md` §9 instead
of being silently fixed or silently ignored.
