---
emoji: "🔌"
description: "gh-aw HELLO executor: the Runtime's C1 SMOKE task executed by a GitHub Agentic Workflow, sealing the standard c1_result.json artifact so the existing pull/adopt/complete leg works unchanged."
intent: "Prove the transport leg Runtime -> gh-aw -> Runtime: a durable Runtime task is dispatched to a gh-aw workflow, the AI answers, and the sealed result is adopted by the Runtime's existing loop."
labels: ["runtime", "gh-aw", "executor"]

on:
  # The push trigger exists ONLY so GitHub registers this workflow: a workflow that
  # declares nothing but `workflow_dispatch` and lives on a non-default branch is not in
  # the repository's workflow registry, so `POST .../dispatches` answers 404 and the
  # Runtime cannot wake it at all. The run this trigger causes is made free by the
  # `steps:` noop below, which stops the engine before any AI Credits are spent.
  push:
    branches:
      - smoke/gh-aw-hello-20261003
  workflow_dispatch:
    inputs:
      runtime_task_id:
        description: "Runtime durable task id"
        required: true
        type: string
      attempt:
        description: "Runtime attempt number"
        required: true
        type: string
      execution_request_id:
        description: "Derived execution identity"
        required: true
        type: string

permissions:
  contents: read
  actions: read

engine:
  id: codex

strict: true

run-name: "C1 ${{ inputs.runtime_task_id }} ${{ inputs.attempt }} ${{ inputs.execution_request_id }}"
timeout-minutes: 6
max-turns: 8
max-ai-credits: 60

tools:
  edit:
  # The task needs no shell and no repository knowledge.
  bash: false
  cli-proxy: false

network:
  allowed:
    - defaults

safe-outputs:
  # No safe outputs at all: this executor only writes a workspace file that the seal
  # step turns into an artifact. Disabling failure-issue reporting removes the last
  # write capability from the run (activation/detection/conclusion otherwise get
  # `issues: write`), so the whole workflow becomes read-only against GitHub.
  report-failure-as-issue: false

# Pre-agent hook. On any event that is NOT the Runtime's dispatch, stop the engine before
# it starts by writing the `noop` entry the harness checks for: zero AI Credits, zero model
# calls. This is what makes the registration run free.
steps:
  - name: Registration-only run (skip the agent)
    if: github.event_name != 'workflow_dispatch'
    run: |
      printf '%s\n' '{"type":"noop","message":"registration-only run; agent intentionally skipped"}' >> "$GH_AW_SAFE_OUTPUTS"

post-steps:
  - name: Seal the C1 result
    id: seal
    env:
      RUN_ID: ${{ github.run_id }}
      RUN_ATTEMPT: ${{ github.run_attempt }}
      RUNTIME_TASK_ID: ${{ inputs.runtime_task_id }}
      ATTEMPT: ${{ inputs.attempt }}
      EXECUTION_REQUEST_ID: ${{ inputs.execution_request_id }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import hashlib, json, os, sys

      expected = "GO_C1_REAL_AI_WORKER_V1_OK"
      try:
          answer = open("ghaw_answer.txt", encoding="utf-8").read().strip()
      except OSError:
          sys.exit("ANSWER_FILE_MISSING")
      if answer != expected:
          sys.exit("ANSWER_MISMATCH:%r" % answer)

      document = {
          "version": 1,
          "kind": "c1-ai-execution-result",
          "runtime_task_id": os.environ["RUNTIME_TASK_ID"],
          "attempt": int(os.environ["ATTEMPT"]),
          "execution_request_id": os.environ["EXECUTION_REQUEST_ID"],
          "github_run_id": int(os.environ["RUN_ID"]),
          "github_run_attempt": int(os.environ["RUN_ATTEMPT"]),
          "provider": "OPENAI_RESPONSES_API",
          "model": "codex-gpt-5.4",
          "response_id": "gh-aw-run-" + os.environ["RUN_ID"],
          "status": "SUCCEEDED",
          "output_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
          "output": answer,
          "accepted": True,
          "reused_terminal_result": False,
          "authorizes_any_action": False,
      }
      with open("c1_result.json", "w", encoding="utf-8") as handle:
          handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")))
      print(open("c1_result.json", encoding="utf-8").read())
      PY
  - name: Upload the sealed result
    uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
    with:
      name: c1-ai-execution-result-${{ inputs.execution_request_id }}
      path: c1_result.json
      retention-days: 3
---

# C1 SMOKE executor, hosted on gh-aw

This is the Runtime's own C1 SMOKE task. Do exactly one thing.

## Your single action

Create the file `ghaw_answer.txt` in the repository root containing exactly this text and
nothing else — no quotes, no newline beyond the final one, no explanation:

```
GO_C1_REAL_AI_WORKER_V1_OK
```

## Hard constraints

1. Do **not** read any file. Do **not** inspect the repository. You do not need any context.
2. Do **not** modify, create, or delete any other file. `ghaw_answer.txt` is the only path
   you may touch.
3. Do **not** run shell commands. Do **not** merge, deploy, approve, or open a pull request.
4. Do **not** touch secrets, workflow files, or configuration.
5. After writing the file, stop. One file, one line, then done.
