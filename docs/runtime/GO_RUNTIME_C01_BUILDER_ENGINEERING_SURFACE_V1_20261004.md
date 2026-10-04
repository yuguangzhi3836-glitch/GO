# GO Runtime C01 — the Builder's engineering action surface

> Status: **candidate (stacked Draft PR)**. Date: 2026-10-04.
> Base: `chenzhenxi/runtime-c01-ghaw-u1-registration-20261004` @
> `26bb054a119348b2b60d1c2dd046a05541b93347` (PR #386), itself on #381 and `main`.
>
> Records one capability change, its boundaries, and what was deliberately left off. Not
> Evidence, not Authority, not a current-state pointer. No execution right is granted and
> nothing has been deployed.

## 1. The gap

#386 registered the gh-aw Builder workflow, bound the transport to it, and made the Runtime
adopt its result through the existing leg. But the agent could not do engineering:

```
tools: { edit, bash: false, cli-proxy: false }     no shell, so no tests
safe-outputs: report-failure-as-issue: false       no pull request
prompt: "ghaw_builder_answer.txt is the only file you may create or modify"
        "do not touch repository content"          no repository change
```

The executor could read a work order and produce prose. That is an answer executor, and the
failure it leaves open is subtler than a security one:

```
REAL_FAILURE_PREVENTED
  the Runtime accepts a real engineering work order
  -> the executor cannot edit, test, or open a pull request
  -> the task returns text and can look successful
  -> while the requested engineering work never happened
```

## 2. What was enabled, and what was not

| | before | now |
|---|---|---|
| repository editing | one file, `ghaw_builder_answer.txt` | the files the work order needs, inside `scope` |
| shell | `bash: false` | `bash: true` - the agent runs the repository's own tests |
| repository write | none | exactly one Draft PR, via gh-aw's `create-pull-request` safe output |
| branch namespace | n/a | `c01-builder/*` and nothing else |
| merge / approve / auto-merge | absent | **still absent** |
| deploy / release / secret change | absent | **still absent** |
| Production / Runtime host access | absent | **still absent** |
| agent job repository write | none | **still none** - the write path is a different job |

`bash: true` is all-or-nothing: gh-aw rejects a per-command allow-list for the codex engine
(measured in Phase 0), so the alternative to a full shell is an executor that cannot verify
its own change. What bounds it is not a command list but everything around it - an ephemeral
runner, no deployment credentials, `network: defaults`, no Runtime-host access, and the
write path existing only in the safe-outputs job.

## 3. Where the write actually happens

Compiled permissions, from `gh-aw v0.89.21` (the whole table, not a selection):

| job | permissions |
|---|---|
| *(workflow default)* | `{}` |
| `activation` | actions: read · contents: read |
| **`agent`** | **actions: read · contents: read** |
| `conclusion` | actions: read · contents: write · issues: write · pull-requests: write |
| `detection` | contents: read |
| `safe_outputs` | contents: write · issues: write · pull-requests: write |

The agent has no repository write authority of its own. The patch leaves the agent job as an
artifact; `safe_outputs` - not the agent - pushes the branch and opens the pull request. That
is a property of the compiled workflow, which is why the test asserts it on the compiled jobs
rather than on the prompt.

The compiled safe output, as the handler receives it:

```
create_pull_request: draft=true  max=1  base_branch=main
                     allowed_branches=["c01-builder/*"]
                     fallback_as_issue=false  auto_close_issue=false  if_no_changes=warn
```

and `merge_pull_request`, `auto_merge`, `push_to_pull_request_branch` and
`create_or_update_secret` occur **nowhere** in the compiled file.

## 4. The Runtime's own files must not reach the pull request

Three mechanisms, in order of strength:

1. **The seal cannot be in the patch.** `c1_result.json` is written by a `post-steps` entry
   that runs *after* the agent job collects the patch. It does not exist while the agent
   runs and does not exist when the patch is captured; the test pins that ordering.
2. **`.gitignore` at the repository root** covers all three files, so `git add -A` cannot
   stage them. The capture itself is `git format-patch` over commits - gh-aw's own
   `setup/sh/generate_git_patch.sh` at the pinned `github/gh-aw-actions@v0.89.21` - so
   untracked and ignored files are outside what it can ever emit. The test proves this with
   a real `git` in a real temporary repository, then runs the real command.
3. **A fail-closed patch guard** in the safe-outputs job, before "Process Safe Outputs": it
   extracts the changed paths from the patch and refuses the run if the patch is absent,
   ambiguous, empty, or contains any of the three files. This is the same mechanism Phase 1B
   proved for its path guard, inverted and made general. It is executed in the test against
   synthetic patches, not read.

The guard also closes the other half of the failure above: a patch with **no changed paths**
is refused, so "the run succeeded" cannot mean "the agent said something".

## 5. What this round does not do

* **No dispatch, no model call, no paid execution.** Nothing was sent to GitHub.
* **No merge, no deploy, no install, no host mutation.** The systemd unit candidate from
  #386 is unchanged and still not installed.
* **No second mechanism.** No PR broker, no path-policy database, no test runner service, no
  executor registry, no receipt/evidence layer. The Draft PR is already traceable,
  reviewable, reversible and non-production.
* **No cost model** (U8) - `max-ai-credits` is unchanged at 60; only the turn and wall-clock
  bounds grew, because an engineering turn is longer than an answering turn.
* **No enablement of the Draft-PR capability's broader policy**: `c01-builder/*` is the only
  namespace the Builder may write to.

## 6. Verification

Local, WSL `Ubuntu-24.04` as root, on an ext4 extraction of the candidate tree:

```
python -m unittest discover -s control-plane/runtime-host-channel-v1 -p 'test_*.py'
Ran 385 tests   OK          (358 on the #386 head; +27 in the new surface file)
```

Covering A the agent can edit and run tests and still has no CLI proxy, B the only write path
is one Draft PR on `c01-builder/*` with no merge anywhere, C the agent job is read-only and
the writes live in the safe-outputs job, D the execution's own files cannot reach the patch
(guard executed, git exercised), E a run that concluded failure is reported to the Runtime
and settled as `RUN_FAILED` even though a result artifact exists and is never even
downloaded, F the U1 transport binding, run name and artifact name did not move.

**Mutation check.** Ten guards disabled one at a time, each required to turn its test red:
10 mutations, 10 caught, 0 missed, 0 invalid.

> M3-M5 were **missed on the first pass**: like the previous round's M7, the tests read the
> compiled configuration only, so editing the front matter without recompiling changed
> nothing they looked at - and the difference would only have appeared at the next compile,
> as a silent behaviour change. The fix was to assert the compiled configuration **against
> the source** rather than against literals. That gap was found by the mutation check, not
> by reading the code.

Four assertions in `test_c1_ghaw_registration.py` were rewritten rather than deleted, because
this round legitimately supersedes them: the agent may now run a shell, and the workflow now
carries write permissions outside the agent job. They now assert the sharper facts - the
compiled tool surface agrees with the declared one, and the declared write surface is still
exactly one Draft PR.
