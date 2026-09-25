# CCV1-145 — full-chain acceptance simulation over the Lite V2 backend and the witness layer

- Task: `CCV1-145-14CELL-FULL-CHAIN-SIMULATION` (first layer: local execution carrier +
  real host witnesses)
- Branch: `cc/ccv1-145-full-chain-simulation-20260925`
- Base: `cc/ccv1-144a-github-witness-credential-20260925` @ `5cebdb5b5` (PR #250)
- Authorisation for this round: temporary witness runtime in `/tmp` at each host, reading
  each host's own installed witness key, signing once per host, pulling back the
  non-sensitive products, and cleaning up afterwards. **Not** a deployment authorisation.

## Result

```text
RESULT = FULL_CHAIN_SIMULATION_ACCEPTED_AT_HUMAN_GATE

REAL_CANDIDATE_COMMIT        = YES   aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0 (origin/main)
REAL_CC_WITNESS_SIGNING      = YES   signed on CC with CC's installed key
REAL_HK_WITNESS_SIGNING      = YES   signed on HK with HK's installed key
C13_C14_BUNDLE_SOURCE        = LOCAL_BACKEND
C13_PRODUCTION_WORKFLOW_DISPATCHED = NO
C14_PRODUCTION_WORKFLOW_DISPATCHED = NO
REAL_C13_C14_VERDICT         = NOT_TESTED
PR247_IS_EVIDENCE            = NO

status                       = ACCEPTED
gate                         = READY_FOR_HUMAN_AUTHORIZATION
FINAL_ROOT                   = fe00f69dc4f213d5b414e58937c5d6cc845cc410fd445a675598cc760c3c9346
```

The chain reached the human gate and stopped there. Nothing was deployed, no service was
restarted, and no production C13/C14 workflow was dispatched.

## The chain, and which parts are real

```text
real candidate commit (origin/main)
    -> C14 record      (LOCAL_BACKEND)
    -> C13 record      (LOCAL_BACKEND)
    -> CC ReviewVerifier          (run on CC, from the received package)
    -> CC witness                 (signed ON CC, with CC's installed key)
    -> HK witness                 (signed ON HK, with HK's installed key)
    -> FinalAcceptanceAggregator  (local)
    -> FINAL_ROOT                 (local, recomputable)
    -> READY_FOR_HUMAN_AUTHORIZATION   (stop)
```

| element | real or simulated | why |
|---|---|---|
| candidate sha + application tree | **real** | `git rev-parse origin/main` / `^{tree}`, a commit that exists |
| C14 and C13 verdicts | simulated | produced by the local backend; no GitHub Actions run was dispatched |
| execution identity inside the bundles (run ids, AI execution ids) | simulated | there is no run to name |
| CC witness signature | **real** | signed on CC by `/etc/go-command-center/keys/c13-c14-witness-ed25519.pem` |
| HK witness signature | **real** | signed on HK by `/etc/go-hk-agent/keys/c13-c14-witness-ed25519.pem` |
| remote GitHub readback | **real** | each host read a real run and re-hashed a real artifact with its own credential |

## Where each signature was actually produced

Neither private key left its host. Each host ran the same runtime from `/tmp`, re-derived
the verification from the received task package, and signed with its own key:

| | CC | HK |
|---|---|---|
| hostname | `iZj6c7k6k01biwlbnwutu5Z` | `iZj6ccs8t04f1p4d8pe69zZ` |
| python / cryptography | 3.10.12 / 3.4.8 | 3.10.12 / 3.4.8 |
| key | `/etc/go-command-center/keys/c13-c14-witness-ed25519.pem` `0600 root:root` | `/etc/go-hk-agent/keys/c13-c14-witness-ed25519.pem` `0600 go-hk-agent:go-hk-agent` |
| key_id | `26ca5651b363c463` | `36458250ffc1b404` |
| purpose | `c13c14-acceptance-witness` | `c13c14-acceptance-witness-hk` |
| witness issued_at | `2026-09-25T12:26:40Z` | `2026-09-25T12:27:01Z` |
| witness digest | `de8fd2c67645c752…` | `69c965a7301be4d8…` |

Both key ids equal the values recorded at installation in CCV1-144B, so the same keys that
were installed are the ones that signed.

## Remote facts each host verified for itself

While signing, each host also read a real GitHub run with **its own** credential. This is
recorded as carrier evidence — it targets a pre-existing harmless POC run and is
**explicitly not** an artifact binding for this candidate, because this candidate has no
GitHub run:

| | CC | HK |
|---|---|---|
| credential | `/etc/go-command-center/keys/github-witness-reader.token` | `/etc/go-hk-agent/keys/github-witness-reader.token` |
| credential fingerprint | `sha256:bcead04ba2b607cbecdf475881b2eddb` | `sha256:7f11873b443120d1f7a843590002bd3a` |
| run | `36110672586` | `36110672586` |
| run / artifact metadata | read + verified | read + verified |
| artifact bytes | 4285 B, downloaded and re-hashed | 4285 B, downloaded and re-hashed |
| re-hashed digest | `sha256:6202a664…b256fc` | identical |
| `refusals` | `[]` | `[]` |

Two hosts, two credentials, two keys, two independent verifications of the same remote
facts. Neither host's result was used as the other's.

## Two defects found while building this layer

**1. The witness could not express "this carrier has no artifact".** `lw_verifier` already
recorded `artifact_payload_not_supplied` when no run/artifact was supplied, but
`lw_witness.build_witness` dereferenced `verification["artifact"][role]["artifact"]["id"]`
and would have raised. So a round whose execution carrier is the local backend could be
verified but not witnessed. Fixed by making the artifact metadata state its binding
explicitly:

```text
binding = GITHUB_RUN_ARTIFACT   the artifact was read back from a run
binding = NOT_APPLICABLE        there is no run to bind to; every artefact field is null
```

`NOT_APPLICABLE` is required to be **empty** and cannot carry an identity; a
`GITHUB_RUN_ARTIFACT` binding is required to carry a digest and a run id. The two states
can no longer be confused, and neither can be dressed up as `verified`.

**2. `FINAL_ROOT` is an integrity check, not an authenticity check.** The root is a public
hash with no key in it, so an attacker who edits a witness can recompute it and satisfy
`verify_final_root`. Only the signatures — which need the hosts' private keys — can tell a
forged record from a real one. Concretely:

```text
CC_WITNESS.C13_ROOT edited, FINAL_ROOT left stale   -> final_root_recompute_mismatch   (caught)
CC_WITNESS.C13_ROOT edited, FINAL_ROOT recomputed   -> verify_final_root PASSES          (NOT caught)
                                                    -> verify_witness  witness_signature_invalid  (caught)
```

A consumer that only called `verify_final_root` would have accepted a forgery. So a single
entry point was added, `lw_aggregate.verify_record`, which checks the signatures **first**,
then the cross-witness bindings, then the root. `lw_chain.finalise` now uses it, and two
tests pin the distinction so a future caller cannot quietly start trusting the root alone.

## Files

Added under `control-plane/c13-c14-witness/`:

- `lw_chain.py` — freezes a round for a real candidate, builds the task package, re-derives
  the verification from received bytes, aggregates, and emits the labelled summary.
- `lw_host_witness.py` — the host runner: re-derives the verification, optionally performs
  the carrier readback with the host's own credential, signs with the host's own key,
  verifies what it is about to write, and refuses to write anything containing private-key
  material.
- `lw_round_cli.py` — local driver (`prepare` / `finalise` / `ledger`).
- `test_lw_chain.py`, `test_lw_host_witness.py`.

Changed:

- `lw_witness.py` — the binding states, `artifact_metadata_for`, and the binding checks in
  `verify_witness`.
- `lw_hk.py` — `compare_with_cc` handles the `NOT_APPLICABLE` case, and refuses when CC
  reports no artifact while this host's own verification found a verified one.
- `lw_aggregate.py` — `verify_record`, and a docstring on `verify_final_root` stating what
  it does **not** prove.

## Verification

```text
witness suite   192 tests OK (1 skipped: the POSIX permission-bit test, by platform)
backend suite    93 tests OK
lite_schemas      --check  stale = []
lw_schemas        --check  stale = []
lite_workflow_check        pass
SECRET_LEAK_SCAN  PASS over 6055 files, 0 gate hits
```

Tamper suite against the **real** produced record: 12/12 intended refusals
(`C14_ROOT`/`C13_ROOT` altered, candidate altered, gate forged to `DEPLOY`,
`auto_deploy` forced true, `authorizes_any_action` forced true, both signatures tampered,
both witnesses edited with the root recomputed, a witness artifact digest forged into a
`NOT_APPLICABLE` slot, and an HK witness from another round substituted in).

## Boundaries

```text
NO service install        NO systemd/unit change     NO restart
NO deploy                 NO database change         NO merge
NO production C13/C14 dispatch   NO Issue writeback
NO private key printed, logged, committed, copied between hosts, or placed in an artifact
```

- No `systemctl start|stop|restart` was issued. `NRestarts=0` for
  `go-boss-request-bridge.service`, `go-command-center-state-cycle.service`,
  `go-ai-command-center.service` and `go-hk-agent.service`; zero
  stop/reload/restart events for them in the window. (The only start/stop lines the journal
  shows belong to `/run/user/0` runtime directories created by these SSH sessions, and the
  bridge's own timer-driven runs.)
- `CC_TOUCHED` / `HK_TOUCHED` = temporary runtime under `/tmp`, read of each host's own
  key, one signature each. `/tmp/ccv1-145` removed from both hosts; the credentials and
  signing keys remain at `0600` and untouched.
- The local rehearsal keys used to exercise the CLI were deleted; the evidence directory
  re-scans clean.

## What this does not establish

The C13/C14 verdicts are simulated. This round proves the **acceptance chain** works end to
end with real host signatures; it does not prove a real C13 or C14 verdict for any
candidate. That is the next layer: dispatching the production C13/C14 workflows, which the
task explicitly deferred and which this round did not touch.

`ACCEPTED` here means the acceptance chain is complete and valid, and it stops at
`READY_FOR_HUMAN_AUTHORIZATION`. It is not a deployment authorisation.
