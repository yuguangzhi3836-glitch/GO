# Installation record — CC V1-05 request visibility

Two phases, deliberately separated. **Phase 1 is installed. Phase 2 is not.**

```text
PHASE 1  journal the Bridge's own poll output + drive the read-only exporter   INSTALLED
PHASE 2  publish the facts to the control bus                                  NOT INSTALLED
```

Until phase 2 exists the control bus still carries no Request facts, the
projection still reads zero, and every collected Request still shows
`REQUEST_CREATED`. Phase 1 makes the facts correct and durable **on the Command
Center host**; it does not put them on the bus.

The split is reported rather than smoothed over: `run_checks.py` emits
`installed = PHASE_1_EXPORT_ONLY`, `installed_publish_side = NO`.

## Installed on `go-cc` (i-j6c7k6k01biwlbnwutu5, cn-hongkong)

| Path | Role |
|---|---|
| `/usr/local/libexec/go-request-fact-cycle` | the operator timer wrapper |
| `/opt/go-command-center/request-visibility-v1/command-center/go-request-fact-export` | the exporter (verbatim from this repository) |
| `/opt/go-command-center/request-visibility-v1/contracts/request_fact_v1.schema.json` | its closed vocabulary |
| `/etc/systemd/system/go-request-fact-cycle.service` | oneshot, root, hardened |
| `/etc/systemd/system/go-request-fact-cycle.timer` | 300 s cadence |
| `/var/lib/go-command-center/request-visibility-v1/` | `poll/` journal, `facts/` store, `state.json` |

The exporter is laid out as `<root>/command-center/…` + `<root>/contracts/…`
because it resolves its contract as `__file__.parent.parent / contracts/…`.

## The wrapper (phase 1)

```text
1. journalctl -u go-boss-request-bridge.service -o cat --since <last capture>
   -> keep the newest line that parses as a Bridge poll object (has "results")
2. write {"schema_version","journaled_at","bridge_output"} under poll/
   -- only when that object's sha256 differs from the last one captured
3. run the exporter over the ledger plus every poll document -> facts/
```

Step 2's condition is load-bearing and was found during the install: the Bridge
re-reports the same view every 60 s, so journalling unconditionally would place an
unchanged observation at a new instant, mint a fresh fact per submission per
cycle, and grow the store without bound. Measured before the fix: 2 cycles -> 36
fact files for 18 facts. Measured after: 3 cycles -> 18 fact files, 1 poll
document, no growth.

The wrapper holds no key, signs nothing, creates no Task, never reads the DEPLOY
request switch, and writes only under its own state directory.

## Evidence

```text
BEFORE_HASH     component           ABSENT  (/opt/go-command-center/request-visibility-v1)
                wrapper             ABSENT  (/usr/local/libexec/go-request-fact-cycle)
                units               ABSENT  (service + timer)
                state dir           ABSENT  (/var/lib/go-command-center/request-visibility-v1)
                facts INDEX         ABSENT
                bridge ledger       size=17414 sha256=9c795b9dbe478ec8109ae523d00b05f3846ecb32825f74bdb0cbb4721a22265b

AFTER_HASH      wrapper             1edc398dda739572e0431c6fa14412419b1d4c03d4f92e7f5659cca353bf5e6c
                service             c52437fdd8658781e4b9503f4eb1a0641297bcfbc34c5b466ec319ea3b19727c
                timer               4c3185590913d42f7107c2b45b20b42353c9efac2a2ade20171edb7dacb5de87
                exporter            a72abb97b2e2d283828495bed0cf66015e53f0a7ed22a3ac55a3998cdabe9c2c
                contract            46ee367cd2a1980bb6d9fa387ea96c08aedd6667020ad3f547f3a7d1027e25c6
                installed == repository working tree (all three hashes identical)

INSTALLED_REVISION
                repository          23e5fc705167b68854ad01b20e27f1a36a381408 (branch cc/v1-finalization-20260914)
                exporter blob       6958d1f18217fbeb001bc3c754ab5ade26e0ac40
                contract blob       8b4070be2a31b894211a009ae63ba23609eb3bc8

SERVICE/TIMER_STATE
                go-request-fact-cycle.timer     active/enabled, last trigger 2026-09-15 18:58:58 +0800
                go-request-fact-cycle.service   oneshot, Result=success, ExecMainStatus=0
                go-boss-request-bridge.timer    unchanged (active/enabled)
                go-ai-command-center.service    unchanged

LIVE_SMOKE_PROOF
                exporter selftest on the installed copy                 PASS
                cycle run 1  {"bridge_results":20,"journal":"20260915T105956Z.json",
                              "exporter":"RUN","exporter_rc":0}
                             -> FACTS=18 SUBMISSIONS=20 SUBMISSIONS_WITHOUT_FACT=2 AUTHORITY=NONE
                cycle run 2  {"journal":"UNCHANGED","bridge_sha256":"885ea6f406746ca1", ...}
                             -> poll_files=1 fact_files=18 (no growth)
                cycle run 3  {"journal":"UNCHANGED", ...} -> poll_files=1 fact_files=18
                INDEX        counts={"facts":18,"facts_emitted":18,"submissions":20,
                                     "submissions_without_fact":2,
                                     "by_kind":{"REQUEST_VALIDATED":18}}
                             authority={every field false}
                             vocabulary.source=contracts/request_fact_v1.schema.json

ROLLBACK_PROCEDURE
                systemctl disable --now go-request-fact-cycle.timer
                rm -f /etc/systemd/system/go-request-fact-cycle.service \
                      /etc/systemd/system/go-request-fact-cycle.timer
                systemctl daemon-reload
                rm -f /usr/local/libexec/go-request-fact-cycle
                rm -rf /opt/go-command-center/request-visibility-v1
                rm -rf /var/lib/go-command-center/request-visibility-v1
                # the Bridge, its ledger, its config, the keys and the runtime are not touched
                # by this install and must not be touched by this rollback
```

## Boundaries

```text
LIVE_DEPLOY_PERFORMED=NO      ROLLBACK_PERFORMED=NO      PRODUCTION_TOUCHED=NO
REQUEST_CHANNEL_CHANGED=NO    TASK_SIGNER_CHANGED=NO     SWITCH_TOUCHED=NO
HONG_KONG_TOUCHED=NO          PRIVATE_KEY_HELD=NO        EXECUTION_AUTHORITY=NO
PHASE_1_INSTALLED=YES         PHASE_2_PUBLISH_INSTALLED=NO
```

## Known gap

Phase 2 — publishing the facts to the control bus — is not installed. It is also
not useful yet: the projection side that consumes `--request-facts-dir` is not
installed either (CC V1-04), so there is nothing for the facts to feed. Both
belong to the same wiring task and should be installed together.
