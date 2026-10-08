> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# VERIFY baseline migration — INSTALLED, and what the first VERIFY after it did

> 2026-09-16. Installed under explicit human authorisation for
> `fc2120ad38e4dcbaf2846b36e8a8e55f8c1798b7`. This records a live change and its
> outcome; it is not Execution Authority.

## Authorised scope, and what was actually touched

```text
APPROVED_COMMIT   fc2120ad38e4dcbaf2846b36e8a8e55f8c1798b7
APPROVED_PLAN     docs/control-plane/hk-staging/VERIFY_BASELINE_MIGRATION_INSTALL_PLAN_20260916.md
STAMP             20260916T050020Z
```

```text
                                       sha256 BEFORE                                                        sha256 AFTER
Command Center 47.242.94.212
  /etc/go-command-center/
    boss-request-verify-baseline-v1.json  52cb3f9935634dd94205734df6769f8a892a88c7b551137f581bbb34f607be18  76bab57106fc19e677ac1f2c66f25d37cedc93525dc655ab1d7fe4076460ab4f  0600 root:root
HK-STAGING-01 47.239.57.40
  /usr/local/libexec/go-hk-deployctl-runtime/
    collector_runtime.py                  a0eeda9e270757cc8fbf70f112ac593d3da6e89e2884bd6ae01df8638126aed2  2b05e3a76845128195c931772b4927ef682e8b36e7f11ba8178c99a9d99452a9  0644 root:root
  /usr/local/libexec/go-hk-deployctl      323c30a7dda9bfa86c45a505854022ee161ef85b3bf41673c018987c88028388  b9aea31e3617e8d94326eef9234708ade5575a05b871b7e2e76c3a0252c5e475  0755 root:root
```

Backups, before/after manifests (`installed.before.tsv`, `installed.after.tsv`,
`installed.tsv`) and the staged bytes:

```text
/var/backups/CC-CHANGE-20260916T050020Z-verify-baseline-depth48/
/var/backups/HK-CHANGE-20260916T050020Z-verify-baseline-depth48/
```

No service was restarted, no container was touched, `EXPECTED_DOWNTIME = NONE`.
Each file was replaced by `install` after its staged bytes passed `sha256sum -c`
against the approved digest; the collector additionally passed `py_compile`, and
the Command Center baseline passed a key-set assertion before installation.

## Preflight, re-proved rather than assumed

```text
8/8 business services running; all .Image == sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132
api healthy; alembic current == head == 0133_flight_change_plan
compose 7ef4ab18… and env 6682ff61… unchanged on disk
```

## Post-install

```text
collector EXPECTED_REVISION  0114_ext_truth_incident_hard -> 0133_flight_change_plan
deployctl _COLLECTOR_SHA256  -> 2b05e3a76845128195c931772b4927ef682e8b36e7f11ba8178c99a9d99452a9
CC baseline image_id         -> sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132
collector imports; COMPOSE/ENV pins re-verified unchanged
```

The Bridge signed the next VERIFY from the new baseline at 05:02:20Z with
`candidate_image_id == expected_current_image_id == sha256:1c9598d6…`, where the
previous baseline had produced `66c54087…` on every VERIFY since 2026-09-11. The
migration took effect.

## The first VERIFY after the migration

```text
REQUEST_ID     boss-hk-verify-depth48-20260916T0503Z   (bus PR chenzhenxi1-sudo/go-control-tasks#27)
TASK_ID        go-boss-request-verify-20260916T050220Z-1e244b2b26e9
issued_at      2026-09-16T05:02:20Z      expires_at 05:17:20Z
dispatch       2026-09-16T05:03:58Z  go-hk-deployctl verify --release-id <task>
                                   --candidate-image-id sha256:1c9598d6… --expected-current-image-id sha256:1c9598d6…
```

The executor ran. The Task did **not** produce a success Evidence:

```text
EVIDENCE       evidence/go-boss-request-verify-20260916T050220Z-1e244b2b26e9-KxDkNoYC0mN8mZCHpIfgX0WeeCO2mjQE.json
               commit 674f60a10b44e36007b298120acf3512657dbdb6  05:05:09Z
status         FAILED
failure.kind   EVIDENCE_PUBLISH_FAILED     stage evidence_publish     reason GITHUB_TRANSPORT_REJECT
retry_permitted false     attempt_budget_exhausted true
```

`VERIFY_REJECTED` is **not** what happened. A rejection would have come back from
the deployctl as `status:"REJECTED"` with return code 2, and the agent's
`parse_executor_output` refuses anything but `status == "SUCCESS"` by raising at
stage `parser` — an execution stage, which would have been recorded as
`EXECUTION_FAILED`. The recorded stage is `evidence_publish`, which is reached only
by `run_once` line 487, after `dispatch_action` returned. The deployctl returns
`SUCCESS`/`VERIFY_OK` only when `_collect_verify` accepted the host, so the
verification itself passed and **the publication is what failed**.

That inference is not a substitute for Evidence. No signed Evidence of `VERIFY_OK`
exists, so `VERIFY` still reports `FAIL` and blocker B3 is **not** cleared.

### Why the publication failed, and why it will recur

`transport.push_evidence` clones the evidence repository into `work/dirname`:

```python
repo = work/dirname; clone(cfg["evidence_repo"], cfg["evidence_key"], repo)
```

`run_once` iterates over **every** Task file in one pass, and `clone()` is a plain
`git clone` that fails when its target already exists. So the first successful
publication in a run creates `work/evidence`, and a second successful publication
in the same run fails with `GITHUB_TRANSPORT_REJECT`.

That is exactly what happened here, and it is the first time it has:

```text
05:03:44  tick starts; two Tasks are new in this pass, sorted()
05:03:54  go-boss-health-20260916T050328Z-e869ddd14462  publishes, creating work/evidence
05:03:58  this VERIFY Task is claimed and dispatched
05:05:05  its success Evidence cannot be published: work/evidence already exists
05:05:09  the failure record publishes, because failures clone into work/evidence-failure
```

`go-boss-health-…` sorts before `go-boss-request-verify-…`, so the health Task won
the directory. A scan of all 56 Evidence records finds only three FAILED ones ever,
and this is the only `EVIDENCE_PUBLISH_FAILED` among them.

It is latent rather than chronic because it needs two Tasks to become new in the
same pass. It will happen again whenever a liveness Task and a VERIFY or TEST_PR
Task land in the same tick window.

Not fixed here: a code change to the agent is neither in this round's authorised
live scope nor needed to diagnose the state, and the fix must be installed to
matter. Left as `TD-J`.

## Readiness after the migration

Re-run against the live projection of 05:09:05Z, no plan bundle supplied:

```text
DEPLOY_READY = NO
PASS    APPROVED_CANDIDATE  SOURCE_BINDING  TEST_PR
FAIL    VERIFY              the newest verified VERIFY is 264338 s old, outside the 86400 s window
UNKNOWN PACKAGE_BINDING DEPLOYMENT_PLAN HUMAN_APPROVAL CURRENT_RUNTIME LIVE_SWITCH
        LIVE_SWITCH_PROVENANCE CANARY RELEASE_GATES BRIDGE_ACCEPTANCE
```

```text
B2  CLEARED        B3  NOT CLEARED (this attempt's Evidence was never published)
B4  OPEN           B5  deployment_requests_enabled = false, untouched and correct
```

## Installed-state statements updated

They described the retired executor and became false when the install happened;
they now record the digests verified on the host:

```text
docs/control-plane/hk-staging/HK_STAGING_DEPLOY_BASELINE.md
hk-staging/README.md
```

They record what is installed. They are not a statement that VERIFY passed.
