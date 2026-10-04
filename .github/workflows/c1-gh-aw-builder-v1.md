---
emoji: "🏗️"
description: "C01 gh-aw Builder executor: the Runtime's GHAW_BUILDER_V1 task executed by a GitHub Agentic Workflow, sealing the standard c1_result.json artifact so the existing pull/adopt/complete leg works unchanged."
intent: "Execute one real C01 Builder work order dispatched by the Persistent Runtime and seal a result bound to the same execution identity. Dispatch-only: this workflow cannot fire by itself and spends nothing until the Runtime dispatches it."
labels: ["runtime", "gh-aw", "executor", "c01"]

on:
  # `workflow_dispatch` ONLY, deliberately.
  #
  # The documented way to make a non-default-branch workflow dispatchable early is an
  # automatic trigger plus a step that skips the agent. That is exactly what this
  # workflow must NOT do: an automatic trigger on a shared branch fires for reasons
  # nobody chose, and every firing is a run whose bookkeeping is visible to everyone.
  # Registration is therefore a property of this file reaching the default branch, not
  # of a trigger that exists to work around it.
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
      task_kind:
        description: "Task kind; must be GHAW_BUILDER_V1"
        required: true
        type: string
      task_payload:
        description: "Canonical JSON of the validated real-task payload"
        required: true
        type: string

permissions:
  contents: read
  actions: read

engine:
  id: codex

strict: true

run-name: "C1 ${{ inputs.runtime_task_id }} ${{ inputs.attempt }} ${{ inputs.execution_request_id }}"
timeout-minutes: 10
max-turns: 10
# A ceiling, not a cost model. The formal cost model is still open (U8); this value only
# bounds a single execution so that a runaway turn cannot spend without limit.
max-ai-credits: 60

tools:
  edit:
  # Codex cannot allow-list bash per command, and a work order must not be able to reach
  # a shell through this executor.
  bash: false
  cli-proxy: false

network:
  allowed:
    - defaults

safe-outputs:
  # No safe output at all. This executor produces a workspace file that the seal step
  # turns into an artifact; it writes nothing to GitHub, opens no issue and no pull
  # request, and `report-failure-as-issue: false` removes the last write capability.
  report-failure-as-issue: false

# Pre-agent step. It is also the first fail-closed gate: a dispatch that carries a kind
# this executor does not own stops here, before the agent starts, so a misrouted task can
# never be executed - let alone paid for - by the wrong executor.
steps:
  - name: Accept the work order (fail closed on any other kind)
    if: github.event_name == 'workflow_dispatch'
    env:
      TASK_KIND: ${{ inputs.task_kind }}
      TASK_PAYLOAD: ${{ inputs.task_payload }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import json, os, sys

      expected = "GHAW_BUILDER_V1"
      kind = (os.environ.get("TASK_KIND") or "").strip()
      if kind != expected:
          # AI_WORK_V1 / AI_TASK_V1 / RUNTIME_PROBE / anything unknown is refused here.
          sys.exit("TASK_KIND_NOT_OWNED_BY_THIS_EXECUTOR:%r" % kind)

      try:
          payload = json.loads(os.environ.get("TASK_PAYLOAD") or "")
      except ValueError:
          sys.exit("TASK_PAYLOAD_NOT_JSON")
      if not isinstance(payload, dict):
          sys.exit("TASK_PAYLOAD_NOT_AN_OBJECT")
      for name in ("schema_version", "cell_id", "external_task_id", "objective", "scope"):
          if name not in payload:
              sys.exit("TASK_PAYLOAD_MISSING_FIELD:%s" % name)
      if str(payload["cell_id"]).strip().upper() not in ("C1", "C01"):
          sys.exit("TASK_PAYLOAD_CELL_IS_NOT_C01:%r" % payload["cell_id"])

      # The agent reads this file; the prompt body is imported verbatim at run time and
      # therefore cannot carry a per-task payload itself.
      with open("c1_builder_task.json", "w", encoding="utf-8") as handle:
          handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
      print("WORK_ORDER_ACCEPTED", payload["external_task_id"])
      PY

post-steps:
  - name: Seal the C1 result
    id: seal
    env:
      RUN_ID: ${{ github.run_id }}
      RUN_ATTEMPT: ${{ github.run_attempt }}
      RUNTIME_TASK_ID: ${{ inputs.runtime_task_id }}
      ATTEMPT: ${{ inputs.attempt }}
      EXECUTION_REQUEST_ID: ${{ inputs.execution_request_id }}
      TASK_KIND: ${{ inputs.task_kind }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import hashlib, json, os, sys

      expected_kind = "GHAW_BUILDER_V1"
      if (os.environ.get("TASK_KIND") or "").strip() != expected_kind:
          sys.exit("TASK_KIND_NOT_OWNED_BY_THIS_EXECUTOR")

      try:
          answer = open("ghaw_builder_answer.txt", encoding="utf-8").read()
      except OSError:
          sys.exit("ANSWER_FILE_MISSING")
      output = answer.strip()
      if not output:
          # The real-class acceptance rule is "any non-empty answer". An empty transcript
          # must not be sealable: it would be indistinguishable from a completed run.
          sys.exit("ANSWER_EMPTY")

      document = {
          "version": 1,
          "kind": "c1-ai-execution-result",
          "runtime_task_id": os.environ["RUNTIME_TASK_ID"],
          "attempt": int(os.environ["ATTEMPT"]),
          "execution_request_id": os.environ["EXECUTION_REQUEST_ID"],
          "github_run_id": int(os.environ["RUN_ID"]),
          "github_run_attempt": int(os.environ["RUN_ATTEMPT"]),
          # The executor's own identity, not the Responses endpoint: the same task
          # executed by a different executor must not resolve to the same result.
          "provider": "GITHUB_AGENTIC_WORKFLOWS",
          "model": "codex",
          "response_id": "gh-aw-run-" + os.environ["RUN_ID"],
          "status": "SUCCEEDED",
          "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
          "output": output,
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

# C01 Builder executor, hosted on GitHub Agentic Workflows

You are executing exactly one work order that the Persistent Runtime dispatched to you.
Your execution identity is fixed by the dispatch; you cannot change it and you do not
need to know it.

## Your work order

Read `c1_builder_task.json` in the repository root. It is the task's own payload:

* `objective` — what the work order asks you to produce;
* `scope` — the boundary you must stay inside;
* `external_task_id`, `cell_id` — identification only.

Answer the objective within the scope.

## Your single output

Write your answer to `ghaw_builder_answer.txt` in the repository root: plain text,
non-empty, no wrapper markup. That file is the result of this execution; the seal step
turns it into the result artifact.

## Hard constraints

1. `ghaw_builder_answer.txt` is the only file you may create or modify. Do not edit,
   create or delete anything else, and do not touch the repository's own content.
2. Do not run shell commands. Do not install anything. Do not use the network beyond
   what this workflow already allows.
3. Do not open, merge, approve or close a pull request or an issue. You have no write
   access to this repository and no authority to acquire any.
4. Do not touch secrets, workflow files, or configuration.
5. You have no authority to change money, state, deployment, release or configuration,
   and you must not claim any. If the objective asks for something outside the scope,
   say so in your answer instead of doing it.
6. After writing the file, stop.
