# Installation record — liveness-request-transport-v1

## 2026-09-15 — the liveness relay is automatic, through one branch and one pull request

```text
WHY      The operator wiring this replaces opened a NEW BRANCH AND A NEW PULL
         REQUEST PER PROBE: 48 open pull requests a day. The Bridge accepts a
         submission only when the diff against merge-base(main, head) is exactly
         one added requests/<id>.json, so a reused branch has to be force-updated
         with a commit built on the current main that adds one file and removes
         none -- and the superseded file has to be archived, or the projection
         would emit one REQUEST_FACT_WITHOUT_REQUEST anomaly per probe.
WHAT     A new component, its units, and its timer. The tool is git-only: it holds
         no HTTP client, so it can push branches and nothing else. The one pull
         request (go-control-tasks #23) was opened once, by the operator.
```

### Where things went

```text
/opt/go-command-center/liveness-request-transport-v1/            the component
/usr/local/libexec/go-liveness-request-transport                 the tool the unit runs
/etc/systemd/system/go-liveness-request-transport.{service,timer}  the units
/var/lib/go-command-center/liveness-request-transport-v1/        the tool's own clone and scratch
/var/backups/CC-CHANGE-20260915T153449Z-liveness-transport/      the pre-install copies of the units
```

### Hashes — installed bytes ARE the repository bytes

```text
5c3d6eb81dcde33048efeae71e50561d59396d44e10971ff5a9c5a826015ca98  command-center/go-liveness-request-transport
                                                                  (and /usr/local/libexec/…)
dfe4f694de35a5fde0888428ef11e76ab915baae380194189268506b3e54bc9f  contracts/liveness_request_transport_v1.schema.json
f36a4851bc138d9c6007b376a39ac23ff165e43cfef89158947b8f073d12dd8b  README.md
03b34d2f37f94e228c7d12d655497e6e7f251bcb53b8d4b32e8ddfc9781ab2d6  run_checks.py
bbadb58773577d9ca10398d7f26cac55f3f25422f4f7882749aefb6c67ce8ed1  install/verify_transport_is_bounded.py
0fc3866de4a13865d7f669f284f310bdb45010f57441a745a4fcb95168b600cc  tests/test_liveness_request_transport.py
333adec476286224ccb1fee63f0e6646cf5cba4765272eca138ffbe693ab3ece  install/go-liveness-request-transport.service
c93adf1ff32d1b6b561433e68b7a5f50d7e20507201fd3cad7bcc38a108cd0a2  install/go-liveness-request-transport.timer
BEFORE   all of the above: ABSENT
```

### Verified on the host, before anything was pushed

```text
selftest on the installed tool                 PASS
the component's own gate, on the host          PASS, 32 tests, 0 failures, 0 errors
the real-git boundedness proof, on the host    PASS (30 checks)
preflight status (ls-remote to the bus)        OK -- the tasks-writer key reaches the bus
preflight dry run                              SKIPPED_STALE, age 1832 s > 600 s window, nothing pushed
```

**Note on the gate's output directory.** `run_checks.py` forbids opening anything
under `/etc/go-command-center/` or `/var/lib/go-command-center/`, which is its own
rule about runtime state and credentials -- so its output directory must be a scratch
path outside them. `/tmp/lrt-gate` works; `$WORK/checks` is refused by design.

### What the first automatic cycle did

```text
the producer published bucket            liveness-control-plane-health-994159
the timer ran the relay, age 10.5 s      PUBLISHED
added_vs_main                            ["requests/liveness-control-plane-health-994159.json"]
removed_vs_main                          []            (a deletion would be a second diff entry)
transport_parent_is_main                 true
archived_now                             []            (first cycle: nothing to supersede yet)
transport head                           99b81d1e807326b76631a76ad5196321eb7d2af5
open pull requests on the bus            22 -> 23      (+1 permanent; the old wiring added 48/day)
the one pull request                     go-control-tasks #23, changed_files 1, additions 1

the Bridge then published that submission, from its own ledger:
  23:99b81d1e807326b published  liveness-control-plane-health-994159
and the signed read-only Task is on the bus:
  tasks/go-boss-health-20260915T153628Z-f24972903a93.json
  action_id CONTROL_PLANE_HEALTH, environment HK-STAGING-01, parameters {}, signed true
  (task_id suffix = sha256(request_id)[:12], the link the projection verifies itself)

the HK agent picked it up on its own timer and published signed Evidence:
  evidence_commits ["28b127f6f9e51b516aaec4246ec02b59947aee6f"], processed 1

the projection then answered:
  hk_agent_online = PROVEN, age 41 s
  reason "signature-verified liveness Evidence inside the freshness window"
```

The whole chain above is automatic. The single manual step was opening the one pull
request, which is what the transport branch needs to become a submission the Bridge
can see; after that the branch is force-updated and the pull request follows it.

### Deliberately not done

```text
the outbox backlog 994154 / 994155 / 994157 / 994158 is NOT relayed.
  They are older than the Bridge's 900 s staleness limit, so relaying them would
  mint a refusal and a REJECTED fact per probe instead of a probe. The tool takes the
  NEWEST fresh probe and reports SKIPPED_STALE rather than publishing an old one.
994153 stays where the old manual wiring put it (branch and pull request #21). Its
  fact already refers to it; moving it is not this change's business.
```

### Rollback

```text
systemctl disable --now go-liveness-request-transport.timer
rm -f /etc/systemd/system/go-liveness-request-transport.{service,timer} \
      /usr/local/libexec/go-liveness-request-transport
rm -rf /opt/go-command-center/liveness-request-transport-v1
systemctl daemon-reload

NOT part of the rollback:
  · the transport branch and its pull request, and the archive branch -- they are
    records of what was already asked of the Bridge, and deleting the archive would
    break the fact-to-Request join for every probe already relayed
  · facts already minted, Tasks already signed, Evidence already published
  · the producer, its outbox, the Bridge, its ledger, the keys and the runtime
Rolling back therefore stops the relay; it does not and must not unask what was
already asked.
```
