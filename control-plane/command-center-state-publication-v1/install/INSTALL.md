# Installation record - CC V1-04 publication target + CC V1-05 PHASE 2

Installed on the Command Center host (`go-cc`, `i-j6c7k6k01biwlbnwutu5`,
cn-hongkong) on 2026-09-15. This is the wiring that turns two shipped
capabilities into one live path:

```
Bridge journal -> Request Fact -> control bus -> State Projection
-> Publication Target -> CURRENT.json
```

Neither half works alone and both are now installed. `CC V1-05` exports the facts
but declared `PHASE 2 publish the facts to the control bus NOT INSTALLED`; the
projection side that consumes `--request-facts-dir` was not installed either, so
the facts had nothing to feed. `CC V1-04` defined the publication target and the
publisher but installed no scheduler, so `CURRENT.json` did not exist and a reader
reported `UNKNOWN`.

## What is installed

```
/usr/local/libexec/go-command-center-state-cycle            operator timer wrapper
/opt/go-command-center/state-publication-v1/projection/     state_projection.py + identity/
/opt/go-command-center/state-publication-v1/publication/    go-state-publication + contract
/opt/go-command-center/state-publication-v1/installed.json  the revision record
/etc/systemd/system/go-command-center-state-cycle.service   oneshot, hardened
/etc/systemd/system/go-command-center-state-cycle.timer     900 s
/var/lib/go-command-center/state-publication-v1/            export/ bus/ requests/ projection/ target/
```

Each cycle, in order:

1. exports the Request facts read-only from the Bridge ledger plus the poll journal
   that `go-request-fact-cycle.timer` maintains, into this component's own export
   root. The other timer's store is read, never written;
2. publishes the export to the control bus on branch `request-facts/live` of
   `go-control-tasks` -- the ref namespace the state contract already declares for
   facts -- and only when its content changed;
3. refreshes the `go-control-tasks` / `go-control-evidence` / `GO` checkouts and
   collects the Request files the bus carries on its `boss-request-*` branches;
4. runs the projector read-only with `--requests-dir` and `--request-facts-dir`
   pointing at what is on the bus;
5. hands the projection to the publisher, which validates it, writes an immutable
   snapshot into the target and only then advances `CURRENT.json`.

The publisher's own contract supplies the two-phase guarantee, so a failure can
never leave a pointer to a snapshot that was not written and verified. The wrapper
adds the scheduling rule: republish when the sources move, and at least hourly.

## Evidence

```
BEFORE   /opt/go-command-center/state-publication-v1                    ABSENT
         /usr/local/libexec/go-command-center-state-cycle               ABSENT
         go-command-center-state-cycle.{service,timer}                  ABSENT
         /var/lib/go-command-center/state-publication-v1                ABSENT
         bus refs/heads/request-facts/live                              DID NOT EXIST
         target CURRENT.json                                            DID NOT EXIST
         go-request-fact-cycle.timer                                    active/enabled (untouched)
         go-boss-request-bridge.timer, go-ai-command-center.service     active (untouched)

AFTER    go-command-center-state-cycle  8b2dfb687967907af3e35246d8e7143affeac41e4844e11eaad8b18a919df32c
         state_projection.py            6ac4b9dd472d78ba50ae56f15abb25d8e8de6910c92efd227105e0e89776d175
         VERIFIER_IDENTITIES_V1.json    b91394fb1b5d251cd265361676e3e41dd68ccdc2e7e0b10a77088be5a47aa3f8
         cc-task-manifest-signing.pub   7329ad0eff6c38973b0aa5c7481ae9e61d8383dd98f790940c8970eceaaad42c
         hk-evidence-signing.pub        3800e9a87b2fe47c2ccdb18209ac35bec0cfe5cc7a1c1ad3927573fe848d7ae3
         go-state-publication           d1313e0500d1a0d5d0ea7a8574137e6edddc527a95e2ef57fea0b4bf9d940f2e
         state_publication_v1.schema.json 9f92733f0f46297f8564996fe03e3d90122d1d4d938885ba2131126830e04962
         .service                       84e91e30e9fe93ca7446221c4c025b01063a81f81ac26a11cec20bb69c9c7f61
         .timer                         efbf24e6831b197c81fab5591cfeae26a6f6c3b327c11a2f2ba7876d36d3d300
         the installed bytes are identical to the repository working tree

REVISION install source       cc/v1-finalization-20260914 @ 4c3391a1edff30c3f57ef316c6210b24780d6682
         projector_revision   4c3391a1edff30c3f57ef316c6210b24780d6682
         the wrapper re-hashes the installed projector every cycle and refuses to
         publish if it no longer matches this record (PROJECTOR_INTEGRITY=OK)

STATE    timer    active/enabled, last trigger 2026-09-15 19:51:18 +0800
         service  oneshot Result=success ExecMainStatus=0
         untouched: go-request-fact-cycle.timer active/enabled, go-boss-request-bridge.timer
         active, go-ai-command-center.service active

SMOKE    cycle 1  FACTS=18 SUBMISSIONS=20 AUTHORITY=NONE -> facts published to the bus
                  (branch request-facts/live created, commit b35e83a4861be6073e41c68fd57c78bba77a62d0)
                  projection 4 documents -> publish PUBLISHED / snapshot NEW
                  pointer CURRENT / verify OK
         cycle N  facts_publish=UNCHANGED, publication=UNCHANGED, pointer CURRENT / verify OK
                  snapshot count does not move
         independent readbacks: git ls-remote shows refs/heads/request-facts/live at the
         same commit; a consumer following CURRENT.json finds the snapshot it names;
         `go-state-publication selftest` on the installed copy SELFTEST_PASS=15

ROLLBACK disable --now go-command-center-state-cycle.timer
         systemctl disable --now go-command-center-state-cycle.timer
         rm /etc/systemd/system/go-command-center-state-cycle.{service,timer}
         systemctl daemon-reload
         rm /usr/local/libexec/go-command-center-state-cycle
         rm -rf /opt/go-command-center/state-publication-v1
         rm -rf /var/lib/go-command-center/state-publication-v1
         The rollback leaves the Bridge, its ledger, its config, its keys,
         go-request-fact-cycle.{timer,service} and its store, the command center
         service, the HK host and the runtime untouched. The only residue it cannot
         remove on its own is branch refs/heads/request-facts/live on
         go-control-tasks, which is a published record and is deleted deliberately,
         not automatically, or not at all.
```

## Two defects this install found

**1. Publishing on "the index differs" would have committed forever.** The
exporter stamps `INDEX.json` with the instant of the run, so an unchanged
observation still produces a byte-different index. Publishing on that signal would
have committed to the branch on every cycle and grown it without bound -- exactly
the time-not-content mistake the poll journal already had. The gate is a digest
over the facts plus the index **with that one instant field removed**; three
consecutive cycles now leave the branch at the same commit.

**2. A fact alone does not put a Request on the bus.** The first projection, with
facts and no Request files, produced 18 `REQUEST_FACT_WITHOUT_REQUEST` anomalies
and reported every single Request as `UNKNOWN` -- it refuses to invent a lifecycle
for a Request whose file it cannot see. Collecting the Request files the bus
carries on `boss-request-*` branches took the anomalies 19 -> 7 and produced real
lifecycles:

```
by_lifecycle   REQUEST_VALIDATED 13   REQUEST_CREATED 1   UNKNOWN 4
```

`REQUEST_VALIDATED` is not taken on the fact's word: the projection accepts it
only when the named Task is on the bus, carries `sha256(request_id)[:12]`, and
verifies against the published Command Center identity. 13 of 18 facts survived
that corroboration.

## Boundaries

```
EXECUTION_AUTHORITY=NO      the wrapper holds no signing key and signs nothing
TASK_SIGNER_TOUCHED=NO      no Task was created, published or modified
SWITCH_TOUCHED=NO           deployment_requests_enabled is still false
DEPLOY_PERFORMED=NO         no compose, no deploy, no rollback
HONG_KONG_TOUCHED=NO        nothing was read from or written to the HK host
PRODUCTION_TOUCHED=NO
REQUEST_CHANNEL_CHANGED=NO  the Bridge is not modified and keeps its own keys
RUNTIME_CHANGED=NO

SCHEDULED_PUBLICATION=YES   go-command-center-state-cycle.timer, 900 s
TARGET_INSTALLED=YES
REQUEST_FACT_PUBLICATION=YES   branch request-facts/live on go-control-tasks

STILL OUTSTANDING
  * the publication target lives on this host. Mirroring it to a branch, so a
    remote reader can follow CURRENT.json, is not part of this install and needs
    its own decision.
  * snapshot retention. `runs/` is append-only by contract and is not pruned; the
    hourly floor bounds growth to about 24 snapshots a day, and a retention
    policy is a decision, not something to hide inside the publisher.
  * hk_agent_online is still null on the answer surface. A public key can never
    prove an agent is online; only fresh signed liveness Evidence can, and the
    producer that would create it is CC V1-08 / #98.
```

---

## Change: the projector folds the fact shapes (2026-09-15, source `846fb0a`)

The bus carries facts written under two rules at once. They are one business fact
per outcome, so the projector now says so instead of counting the same outcome
twice.

```
BEFORE   projector  6ac4b9dd472d78ba50ae56f15abb25d8e8de6910c92efd227105e0e89776d175
         wrapper    895e269a6973ea0c2a41c6717c3d6fa10b82608376091afb9ae6042ddc2fa1d4
AFTER    projector  c3cb6448754203b42bc7e0da0809cc5e6495dd1d454f69caa99806a5a50efaa8
         wrapper    a3324a501300686c9030319e22a8b5059a54bea13d6102df01247e2bc89f6f69
         installed.json projector_sha256 updated in the same step, because the
         wrapper re-hashes the installed projector every cycle and refuses to
         publish if it no longer matches: PROJECTOR_INTEGRITY=OK
STATE    go-command-center-state-cycle.timer active/enabled; the request-visibility
         timer, the Bridge timer and the command center service untouched
SMOKE    request_facts 56 -> 19; request_fact_observations 75;
         request_facts_collapsed 56;
         facts_by_identity_rule {LEGACY_TIMESTAMP: 19, SEMANTIC: 19};
         a sample identity on_bus=4 collapsed=3 -> one business fact;
         anomalies 7; a repeat cycle reports everything UNCHANGED with the pointer
         CURRENT and verify OK
         answers.hk_agent_online UNKNOWN with the age in the reason, and
         freshness reporting liveness_window 2400 / interval 1800 / grace 600
ROLLBACK restore the four files from
         /var/backups/CC-CHANGE-20260915T143916Z-semantic-facts/ and the wrapper
         from /var/backups/CC-CHANGE-20260915T144827Z-liveness-answer/, put
         projector_sha256 back, daemon-reload and start the timer. Nothing in the
         published branch is deleted: the facts and the target are records.
```

Reading the wrong document for the liveness answer was its own defect and is
recorded in the commit that fixed it: `CURRENT_CONTROL_STATE.json` carries
`control_state.hk_agent_liveness` (the assertion) while `CONTROL_STATUS_V1.json`
carries `answers.hk_agent_online` (the answer). A reader that asks the wrong one
gets null and concludes the agent is unobserved.

The line above saying `hk_agent_online` is still null describes the state before
the producer was installed; the producer, the Bridge extension that lets its Task
be signed, and one full probe through the real path are all in place now, and the
answer returns to UNKNOWN between probes by design.
