---
emoji: "🏗️"
description: "Builder executor for the normal engineering cells C01-C12: the Runtime's GHAW_BUILDER_V1 work order executed by a GitHub Agentic Workflow, which investigates, edits and tests the repository and requests exactly one Draft PR, then seals the standard c1_result.json artifact so the existing pull/adopt/complete leg works unchanged."
intent: "One Builder executor serves C01 through C12 - one workflow, one executor, one outbox, with the cell carried by the task. C13 and C14 are the control-only cells and are refused here as well as in the worker and the payload validator. The work order's source anchor must equal this run's own execution SHA, so a task written against an older main cannot be executed on today's tree. Dispatch-only; the agent has no repository write authority of its own."
labels: ["runtime", "gh-aw", "executor", "c01", "builder"]

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
      owner_c:
        description: "Canonical owner cell; must equal canonical(task_payload.cell_id) and be C1..C12"
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

# The cell leads, because it is the one field a human looks at when a run has to be
# resolved by name. For C1 this renders exactly the string the live Runtime Host has
# already recorded.
run-name: "${{ inputs.owner_c }} ${{ inputs.runtime_task_id }} ${{ inputs.attempt }} ${{ inputs.execution_request_id }}"
# An engineering turn is longer than an answering turn: investigate, edit, test, commit,
# request the Draft PR. These are bounds, not a cost model - the formal cost model is
# still open (U8), and `max-ai-credits` below is unchanged from the answering executor.
timeout-minutes: 15
max-turns: 16
max-ai-credits: 60

tools:
  edit:
  # A Builder has to run the repository's own tests. Codex cannot allow-list bash per
  # command (gh-aw rejects that for this engine), so the choice is all-or-nothing; the
  # alternative is an executor that cannot verify its own change. What bounds it is
  # everything around it rather than a command list: an ephemeral GitHub runner, no
  # deployment credentials, `network: defaults`, no Runtime-host access, and a repository
  # write path that exists only in the safe-outputs job (see below).
  bash: true
  # Nothing here needs an MCP server mounted as a CLI.
  cli-proxy: false

network:
  allowed:
    - defaults

safe-outputs:
  # Never turn a failure into an unexpected issue write.
  report-failure-as-issue: false
  # The ONLY repository write path this workflow has. The agent job stays read-only; the
  # patch travels to the safe-outputs job as an artifact, and that job - not the agent -
  # pushes the branch and opens the pull request. Draft by construction, one at most,
  # against main, and only onto a branch in the Builder's own namespace. One namespace for
  # all the cells, not one per cell: the branch is where the change lives, and a cell does
  # not need its own directory of branches to stay distinguishable - the pull request
  # title, the work order and the artifact all carry the cell.
  create-pull-request:
    draft: true
    base-branch: main
    title-prefix: "[Builder] "
    max: 1
    if-no-changes: "warn"
    fallback-as-issue: false
    auto-close-issue: false
    allowed-branches:
      - "builder/*"
  # Runs in the safe_outputs job after its checkout and BEFORE "Process Safe Outputs", so
  # a non-zero exit here aborts the job and the Draft PR is never created.
  #
  # It closes two things a prompt alone cannot:
  #   * the patch must contain something. The failure this round exists to prevent is a
  #     Builder that returns text and looks successful while no engineering work happened,
  #     and "no changed paths" is exactly that shape.
  #   * the patch must not contain this execution's own files. They are git-ignored, so
  #     `git add -A` cannot pick them up; this is the independent second check on the
  #     patch itself, in case anything ever adds them by force.
  #
  # The harness blocks command substitution, backticks and parameter transformation in
  # run scripts, and slim runners may lack diffutils - so this uses bash builtins and
  # coreutils only.
  steps:
    - name: Builder patch guard (fail-closed)
      run: |
        set -euo pipefail
        PATCH_FILE=""
        set -- /tmp/gh-aw/aw-*.patch
        if [ "$#" -eq 1 ] && [ -f "$1" ]; then
          PATCH_FILE="$1"
        fi
        if [ -z "$PATCH_FILE" ]; then
          echo "BUILDER_PATCH_GUARD=FAIL reason=NO_UNAMBIGUOUS_PATCH_ARTIFACT arg_count=$#"
          exit 1
        fi
        echo "BUILDER_PATCH_GUARD_PATCH=${PATCH_FILE}"
        grep -E '^\+\+\+ ' "$PATCH_FILE" | sed -e 's|^+++ b/||' -e 's|^+++ ||' | grep -v '^/dev/null$' | sort -u > /tmp/builder-guard-paths.txt || true
        echo "--- changed paths present in the builder patch ---"
        cat /tmp/builder-guard-paths.txt || true
        echo "--- end changed paths ---"
        if [ ! -s /tmp/builder-guard-paths.txt ]; then
          echo "BUILDER_PATCH_GUARD=FAIL reason=NO_CHANGED_PATHS"
          exit 1
        fi
        for forbidden in ghaw_builder_answer.txt c1_result.json c1_builder_task.json; do
          if grep -qx "$forbidden" /tmp/builder-guard-paths.txt; then
            echo "BUILDER_PATCH_GUARD=FAIL reason=RUNTIME_EXECUTION_FILE_IN_PATCH path=$forbidden"
            exit 1
          fi
        done
        echo "BUILDER_PATCH_GUARD=PASS"

# Pre-agent step. It is also the fail-closed gate: a dispatch that carries a kind this
# executor does not own, a cell it does not serve, an owner that disagrees with the payload,
# or a source anchor that is not the tree this run is executing stops here, before the agent
# starts - so a misrouted or mis-bound task can never be executed, let alone paid for.
steps:
  - name: Accept the work order (fail closed on any other kind, cell or source)
    if: github.event_name == 'workflow_dispatch'
    env:
      TASK_KIND: ${{ inputs.task_kind }}
      TASK_PAYLOAD: ${{ inputs.task_payload }}
      OWNER_C: ${{ inputs.owner_c }}
      # The workflow's OWN execution SHA, supplied by GitHub - not an input, so a dispatch
      # cannot claim to have run somewhere it did not. `ref` is `main` for every Builder
      # dispatch, so this is main's head at the moment this run was created.
      WORKFLOW_SHA: ${{ github.sha }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import json, os, re, sys

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

      # The cells this workflow serves, as its own check. A workflow runs in a checkout it
      # does not share with the Runtime and cannot import the contract, so it states the
      # range itself rather than pretending to derive it - a gate that cannot run its own
      # check is not a gate. This is the third of three independent refusals, and it does
      # not rely on either of the other two.
      builder_cells = tuple("C%d" % n for n in range(1, 13))

      def canonical(value):
          text = str(value).strip().upper()
          padded = re.match(r"^C0([1-9])$", text)
          if padded:
              return "C" + padded.group(1)
          if re.match(r"^C([1-9]|1[0-4])$", text):
              return text
          sys.exit("TASK_PAYLOAD_CELL_NOT_A_KNOWN_RESPONSIBILITY_DOMAIN:%r" % value)

      # The owner cell travels here as its own input, copied from the validated binding.
      # It must be the CANONICAL spelling - `C1`, never `C01` - because that is exactly
      # what the contract puts on the wire; a padded owner means the sender did not use
      # the contract, and guessing which of the two spellings was meant is not this
      # step's job. It is checked against the range FIRST and against the payload second,
      # so a control-only cell is refused as a control-only cell rather than as a
      # mismatch, and each of the three refusals below is reachable on its own.
      owner_c = (os.environ.get("OWNER_C") or "").strip().upper()
      if not owner_c:
          sys.exit("OWNER_C_MISSING")
      if owner_c not in builder_cells:
          sys.exit("OWNER_C_NOT_OWNED_BY_BUILDER_EXECUTOR:%r" % owner_c)

      payload_cell = canonical(payload["cell_id"])
      if payload_cell not in builder_cells:
          # C13 and C14 land here, and that is the point: they are the control-only cells.
          sys.exit("TASK_PAYLOAD_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR:%r" % payload_cell)

      # Both halves are inside the range; now they have to agree with each other. This
      # comparison is the entire reason the cell is sent twice - a dispatch that names one
      # cell in `owner_c` and another in the payload stops here, before the agent starts.
      # Which of the two is "right" is not this step's problem: a disagreement is a
      # refusal either way.
      if owner_c != payload_cell:
          sys.exit("OWNER_C_DOES_NOT_MATCH_TASK_PAYLOAD:%s:%s" % (owner_c, payload_cell))

      # Source binding, checked against GitHub's own record of what this run is executing
      # rather than against anything the dispatch said. The ingress already refuses an
      # issue written against an older main, but main can move between admission and
      # dispatch: a task admitted against A, queued, and dispatched after main became B
      # would otherwise be executed on B while claiming to be about A. So the same
      # equality is checked again here, and again strictly - no ancestry, no tree
      # equivalence, no "close enough". A mismatch stops the run before the agent starts,
      # which is what keeps a mis-bound task from ever reaching a paid model call.
      source_anchor = str(payload.get("source_anchor") or "").strip().lower()
      if not re.match(r"^[0-9a-f]{40}$", source_anchor):
          sys.exit("TASK_PAYLOAD_SOURCE_ANCHOR_MISSING_OR_INVALID:%r"
                   % payload.get("source_anchor"))
      workflow_sha = (os.environ.get("WORKFLOW_SHA") or "").strip().lower()
      if not re.match(r"^[0-9a-f]{40}$", workflow_sha):
          sys.exit("WORKFLOW_SHA_UNAVAILABLE:%r" % workflow_sha)
      if source_anchor != workflow_sha:
          sys.exit("SOURCE_ANCHOR_DOES_NOT_MATCH_WORKFLOW_SHA:%s:%s"
                   % (source_anchor, workflow_sha))

      # The agent reads this file; the prompt body is imported verbatim at run time and
      # therefore cannot carry a per-task payload itself. The path is git-ignored, so it
      # cannot reach the Builder's pull request.
      with open("c1_builder_task.json", "w", encoding="utf-8") as handle:
          handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
      print("WORK_ORDER_ACCEPTED", payload["external_task_id"], owner_c)
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
need to know it. You are a builder, not a reviewer, and not an authority.

## Your work order

Read `c1_builder_task.json` in the repository root. It is the task's own payload:

* `objective` — what the work order asks you to produce;
* `scope` — the boundary you must stay inside;
* `cell_id` — the cell this work order belongs to. It is not decoration: the cell is what
  the work is *for*, so a change that belongs to a different cell's domain is out of
  scope even when the objective does not say so.
* `external_task_id` — identification only.

## What to do

1. Read `c1_builder_task.json`.
2. Investigate this repository only as far as the objective actually requires. Read the
   code you are about to change, and the tests that cover it. `cell_id` names one of the
   workbench cells, whose domain, owned paths and forbidden paths are declared in
   `application/src/go_hotel/workbench/definitions.py`; stay inside the paths that cell
   owns, and out of the ones it forbids.
3. Implement the objective inside the supplied scope. Keep the change minimal and
   coherent: solve the stated problem, do not refactor around it.
4. Run the relevant tests and make them pass. If a test cannot run in this environment,
   say so plainly rather than assuming it passes.
5. Create a local branch whose name starts with `builder/`, and commit exactly the files
   your change needs. Commit nothing else.
6. Request exactly one Draft pull request through the `create_pull_request` safe output,
   against `main`. The branch name you pass must be the branch you are actually on.
7. Write a concise execution summary — what you changed, which files, which tests you ran
   and what they reported — to `ghaw_builder_answer.txt` in the repository root. That file
   is the Runtime's result; it is git-ignored and must NOT be committed.
8. Stop.

## Hard constraints

1. **Nothing outside the work order.** Do not change files unrelated to the objective. Do
   not reformat, do not tidy "while you are here", do not upgrade dependencies.
2. **No merge, no approve, no ready-for-review, no auto-merge, no release, no deploy.** The
   Draft pull request you create is a candidate for a human to review; it is not a
   decision, and a green run is not an approval.
3. **No secrets.** Do not read, print, modify or create credentials or tokens, and do not
   change repository secrets or variables.
4. **Workflow files only if the work order is explicitly about them.** `.github/**` is not
   yours to touch by default, and workflow changes are their own kind of risk.
5. **No Production and no Runtime host.** You cannot reach them, and you must not try. You
   have no authority to change money, state, deployment, release or configuration.
6. **Never rewrite history or evidence.** Do not amend or rebase published work, do not
   rewrite historical records, do not force-push.
7. **The Runtime's own files are not yours.** `c1_builder_task.json`,
   `ghaw_builder_answer.txt` and `c1_result.json` belong to this execution. They are
   git-ignored; do not commit them, do not delete them, do not add them with `-f`.
8. If the objective cannot be done inside the scope, do not widen the scope. Implement
   what can be done, and say plainly in your summary what you could not do and why.
