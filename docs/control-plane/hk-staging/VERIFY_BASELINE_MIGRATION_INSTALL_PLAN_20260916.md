# VERIFY baseline migration — live install plan (NOT EXECUTED)

> Prepared 2026-09-16. Status: `REPO_FIX_READY` + `LIVE_CHANGE_PLAN_READY`.
> **Nothing in this file has been run.** It exists so a human can approve an
> auditable, reversible change instead of editing live files by hand.

## What changes

The frozen VERIFY baseline described the retired R3.1.5 runtime. Two independent
hard pins were stale, and correcting only one would not have fixed VERIFY.

```text
LIVE_FILES_TO_CHANGE (Command Center, 47.242.94.212)
  /etc/go-command-center/boss-request-verify-baseline-v1.json     root:root 0600

LIVE_FILES_TO_CHANGE (HK-STAGING, 47.239.57.40)
  /usr/local/libexec/go-hk-deployctl-runtime/collector_runtime.py
  /usr/local/libexec/go-hk-deployctl

LIVE_FILES_TO_RESTART
  NONE

LIVE_SERVICES_TO_RESTART
  NONE
```

No restart is required and none should be performed. The Bridge is a `oneshot`
service driven by `go-boss-request-bridge.timer` and re-reads the baseline on every
poll; the HK agent runs `--run-once` as a fresh process per timer tick, so it reads
whichever file is complete. Both files are replaced by atomic rename.

## Digests

```text
                                     OLD                                                                 NEW
CC verify baseline                   52cb3f9935634dd94205734df6769f8a892a88c7b551137f581bbb34f607be18  76bab57106fc19e677ac1f2c66f25d37cedc93525dc655ab1d7fe4076460ab4f
  (sha256 of the file as installed; the live copy is byte-identical to the repo's LF bytes)
collector_runtime.py                 a0eeda9e270757cc8fbf70f112ac593d3da6e89e2884bd6ae01df8638126aed2  2b05e3a76845128195c931772b4927ef682e8b36e7f11ba8178c99a9d99452a9
go-hk-deployctl                      323c30a7dda9bfa86c45a505854022ee161ef85b3bf41673c018987c88028388  b9aea31e3617e8d94326eef9234708ade5575a05b871b7e2e76c3a0252c5e475
```

All six values are over LF bytes; the manifest files record the same convention.
The live copies were confirmed byte-identical to the repository before this plan,
which is why OLD values are the repository's own recorded digests.

Repository commits carrying the new bytes:

```text
a578cf131638bbda7b1cb49d9ae7bf004b5db980   collector + deployctl + regression + change record
09c8ed2                                   CC verify baseline
```

## Install commands (for the human, after approval)

Both hosts already have the conventions this reuses — the HK `HK-CHANGE-*` backup
directory with `.before` files and an `installed.tsv` manifest, and the CC
`CC-CHANGE-*` equivalent. No new mechanism is introduced.

```bash
# --- 0. fetch the exact bytes for the commit under approval and verify them
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
KEY=~/.ssh/id_ed25519_workbuddy

# --- 1. HK-STAGING: collector + deployctl, staged then renamed
ssh hk-staging 'mkdir -p /var/backups/HK-CHANGE-'"$STAMP"'-verify-baseline-depth48'
scp -i $KEY <checkout>/hk-staging/source/executor/runtime/collector_runtime.py \
           hk-staging:/var/backups/HK-CHANGE-$STAMP-verify-baseline-depth48/staged-collector_runtime.py
scp -i $KEY <checkout>/hk-staging/source/executor/go-hk-deployctl \
           hk-staging:/var/backups/HK-CHANGE-$STAMP-verify-baseline-depth48/staged-go-hk-deployctl
ssh hk-staging '
  set -eu
  B=/var/backups/HK-CHANGE-'"$STAMP"'-verify-baseline-depth48
  R=/usr/local/libexec/go-hk-deployctl-runtime/collector_runtime.py
  D=/usr/local/libexec/go-hk-deployctl
  # backups first, with the digests recorded, before anything is replaced
  cp -p "$R" "$B/collector_runtime.py.before"; cp -p "$D" "$B/go-hk-deployctl.before"
  ( cd / && sha256sum "$R" "$D" > "$B/installed.before.tsv" )
  # integrity of the staged bytes against the approved digests, then compile
  echo "2b05e3a76845128195c931772b4927ef682e8b36e7f11ba8178c99a9d99452a9  $B/staged-collector_runtime.py" | sha256sum -c -
  echo "b9aea31e3617e8d94326eef9234708ade5575a05b871b7e2e76c3a0252c5e475  $B/staged-go-hk-deployctl" | sha256sum -c -
  PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile "$B/staged-collector_runtime.py"
  # both renames back to back: the deployctl pins the collector by exact bytes, so a
  # tick landing between them fails closed rather than acting on a mix
  install -m 0644 -o root -g root "$B/staged-collector_runtime.py" "$R"
  install -m 0755 -o root -g root "$B/staged-go-hk-deployctl" "$D"
  ( cd / && sha256sum "$R" "$D" > "$B/installed.after.tsv" )
  cat "$B/installed.after.tsv"
'

# --- 2. Command Center: the baseline JSON
ssh go-cc 'mkdir -p /var/backups/CC-CHANGE-'"$STAMP"'-verify-baseline-depth48'
scp -i $KEY <checkout>/command-center/config/boss-request-verify-baseline-v1.json \
           go-cc:/var/backups/CC-CHANGE-$STAMP-verify-baseline-depth48/staged-baseline.json
ssh go-cc '
  set -eu
  B=/var/backups/CC-CHANGE-'"$STAMP"'-verify-baseline-depth48
  T=/etc/go-command-center/boss-request-verify-baseline-v1.json
  cp -p "$T" "$B/boss-request-verify-baseline-v1.json.before"
  sha256sum "$T" > "$B/installed.before.tsv"
  echo "76bab57106fc19e677ac1f2c66f25d37cedc93525dc655ab1d7fe4076460ab4f  $B/staged-baseline.json" | sha256sum -c -
  # the Bridge validates the key set as closed; prove it before installing
  python3 -c "
import json,sys
v=json.load(open(\"$B/staged-baseline.json\"))
assert set(v)=={\"version\",\"environment\",\"image_id\",\"evidence_task_id\",\"evidence_commit\",\"evidence_path\"}, sorted(v)
assert v[\"version\"]==1 and v[\"environment\"]==\"HK-STAGING-01\"
assert v[\"image_id\"]==\"sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132\"
print(\"baseline shape OK\")
"
  install -m 0600 -o root -g root "$B/staged-baseline.json" "$T"
  sha256sum "$T" > "$B/installed.after.tsv"; cat "$B/installed.after.tsv"
'
```

## Rollback commands

```bash
# Command Center
ssh go-cc 'B=/var/backups/CC-CHANGE-<STAMP>-verify-baseline-depth48; \
  install -m 0600 -o root -g root "$B/boss-request-verify-baseline-v1.json.before" \
          /etc/go-command-center/boss-request-verify-baseline-v1.json; \
  sha256sum /etc/go-command-center/boss-request-verify-baseline-v1.json'

# HK-STAGING
ssh hk-staging 'B=/var/backups/HK-CHANGE-<STAMP>-verify-baseline-depth48; \
  install -m 0644 -o root -g root "$B/collector_runtime.py.before" \
          /usr/local/libexec/go-hk-deployctl-runtime/collector_runtime.py; \
  install -m 0755 -o root -g root "$B/go-hk-deployctl.before" /usr/local/libexec/go-hk-deployctl; \
  sha256sum /usr/local/libexec/go-hk-deployctl-runtime/collector_runtime.py /usr/local/libexec/go-hk-deployctl'
```

Rollback is the two `install` calls and nothing else: no service is restarted in
either direction, and no ledger, evidence or task record is touched.

## Expected downtime

```text
EXPECTED_DOWNTIME = NONE
```

No process is restarted and no container is touched. The only exposure is a tick
landing inside the sub-second window between the two HK renames, where the
deployctl's collector integrity check would fail closed and the attempt would be
recorded as a failed VERIFY. That is the same outcome as today's rejection, so it
is not a regression; the two renames are issued back to back to keep the window as
small as possible.

## After the install (separate authorisation)

```text
1. publish one fresh bounded VERIFY Request (bus PR with one requests/*.json)
   -> the Bridge signs the Task with candidate_image_id == expected_current_image_id
      == sha256:1c9598d6...
   -> the HK collector checks DEPTH48 compose/env/image/alembic
   -> signed Evidence with VERIFY_OK
2. confirm readiness: the VERIFY gate moves off FAIL
3. update the two installed-state statements that still record the old executor
   digest, because only then are they false about the host:
     docs/control-plane/hk-staging/HK_STAGING_DEPLOY_BASELINE.md
     hk-staging/README.md
```

## Deliberately not in this change

```text
BASELINE_AUTO_UPDATE = false      no mechanism follows the runtime
no new gate, no new verifier, no new timer, no daemon, no runtime watcher
control-plane/depth40-compat-v2/executor/.../collector_runtime.py  carries the same
  stale revision but is not installed on HK and not on the VERIFY path; migrating it
  is a separate decision
blocker B4 (the deployment plan bundle) is untouched by this change
```
