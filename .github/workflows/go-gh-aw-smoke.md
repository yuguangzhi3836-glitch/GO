---
emoji: "🧪"
description: "Controlled gh-aw Phase 1 paid smoke: one push-triggered Codex execution that may create exactly one Draft PR, with a deterministic path guard wired before the writer step."
intent: "Prove end-to-end that a GitHub Agentic Workflow can act as a minimal Builder execution backend (real code change + real Draft PR) that the Persistent Runtime can dispatch later."
labels: ["smoke", "gh-aw", "phase1"]

on:
  push:
    branches:
      - smoke/gh-aw-phase1-20261003

permissions:
  contents: read
  actions: read

engine:
  id: codex

strict: true

run-name: "go-gh-aw-smoke-phase1"
timeout-minutes: 5
max-turns: 4
max-ai-credits: 25

tools:
  edit:
  # Codex cannot allow-list bash per command; a single-file edit needs no shell.
  bash: false
  cli-proxy: false

network:
  allowed:
    - defaults

safe-outputs:
  # Never turn a failure into an unexpected issue write.
  report-failure-as-issue: false
  create-pull-request:
    draft: true
    title-prefix: "[smoke] "
    max: 1
    if-no-changes: "warn"
    fallback-as-issue: false
    auto-close-issue: false
    allowed-branches:
      - "smoke/*"
  # DETERMINISTIC PATH GUARD - runs in the safe_outputs job after its checkout and
  # BEFORE "Process Safe Outputs". A non-zero exit here aborts the job, so the
  # Draft PR is never created. Fully fail-closed: missing/ambiguous patch => FAIL.
  # NOTE: the safe-outputs harness blocks command substitution, backticks, indirect
  # expansion and parameter transformation in run scripts, and slim runners may lack
  # diffutils - so this guard uses bash builtins + coreutils only.
  steps:
    - name: Deterministic path guard (fail-closed)
      run: |
        set -euo pipefail
        EXPECTED="docs/smoke/gh-aw-smoke.md"
        PATCH_FILE=""
        set -- /tmp/gh-aw/aw-*.patch
        if [ "$#" -eq 1 ] && [ -f "$1" ]; then PATCH_FILE="$1"; fi
        if [ -z "$PATCH_FILE" ]; then
          echo "PATH_GUARD=FAIL reason=NO_UNAMBIGUOUS_PATCH_ARTIFACT arg_count=$#"
          exit 1
        fi
        echo "PATH_GUARD_PATCH=${PATCH_FILE}"
        grep -E '^\+\+\+ ' "$PATCH_FILE" | sed -e 's|^+++ b/||' -e 's|^+++ ||' | grep -v '^/dev/null$' | sort -u > /tmp/path-guard.actual || true
        echo "--- changed paths present in the agent patch ---"
        cat /tmp/path-guard.actual || true
        echo "--- end changed paths ---"
        FIRST=""
        SECOND=""
        { read -r FIRST || true; read -r SECOND || true; } < /tmp/path-guard.actual
        if [ "${FIRST}" = "${EXPECTED}" ] && [ -z "${SECOND}" ]; then
          echo "PATH_GUARD=PASS changed_file=${EXPECTED}"
        else
          echo "PATH_GUARD=FAIL expected=${EXPECTED} first_seen=${FIRST} second_seen=${SECOND}"
          exit 1
        fi
---

# GO gh-aw Phase 1 smoke (single controlled execution)

You are a minimal, deliberately harmless smoke executor. Do exactly one thing.

## The only allowed change

Create the file `docs/smoke/gh-aw-smoke.md` with exactly this content:

```
# gh-aw smoke

This file was created by the controlled gh-aw Phase 1 smoke test.

Execution date: 2026-10-03
```

If that file already exists, overwrite it with exactly the content above.

## Hard constraints

1. This is the ONLY file you may add, modify, or delete. Touching any other path fails a
   deterministic guard and the whole run is discarded.
2. Do not refactor, fix bugs, update README/changelog/dependencies, or touch workflows, tests,
   `application/`, `control-plane/`, `docs/canonical-baseline/`, or any existing file.
3. Do not merge anything. Do not deploy. Do not touch secrets or release configuration.
4. Create exactly one **Draft** pull request:
   - branch: `smoke/gh-aw-phase1-agent`
   - title: `[smoke] gh-aw phase 1 builder proof`
   - body: state that this is a controlled Phase 1 smoke artefact, list the single added file,
     and state that it must never be merged.
5. Do not read or print any secret. Stop as soon as the one file and the one Draft PR are done.
