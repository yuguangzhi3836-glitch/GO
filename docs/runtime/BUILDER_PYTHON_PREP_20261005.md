# Builder portable Python dependency preparation

Change classes: BUILD, TEST_ONLY, DOCUMENTATION.

Status: **CANDIDATE / LIVE_VALIDATION_PENDING**. This follows #423 and the
documentation-only blocker #424; it does not modify their history or replay their
executions. Base: `ee4a0a4ea4c9a95b7017b8db991de7554962f42a`.

## Problem and minimal change

#424 could not obtain gh-aw v0.89.21 inside the old Builder sandbox and correctly
refused to hand-edit the generated lock. Here the official linux-amd64 v0.89.21
compiler was obtained outside that sandbox, checked against both the official
release API digest and checksums.txt, and used for strict compilation.
The untouched workflow reproduced the existing lock's YAML semantics first.

The workflow now uses a pinned setup-uv action and uv 0.12.19 to create a portable
CPython 3.12.12 plus virtual environment under the already-mounted
`/tmp/gh-aw/python`. This follows the same gh-aw version's managed-Python pattern:
copying a runner-CPython venv can fail inside AWF because of a GLIBC mismatch.
No new mount, daemon, container privilege, network domain or command proxy is added.

`uv pip install -r application/pyproject.toml --extra dev --only-binary :all:`
installs project runtime/dev requirements without executing a project build or
inventing a second dependency list. No application dependency constraint changes.
The existing lower bounds still resolve different versions over time; the actual
resolved versions and input pyproject hash are uploaded per run. This is not a
dependency-locking or production-compatibility project. A missing wheel fails
closed rather than invoking an unreviewed source build.

The original work-order/source gate runs before preparation. The new pre-agent
host smoke verifies imports and four real no-DB pytest behaviors. The agent is
instructed to run the same command inside its sandbox before editing files:

```sh
/tmp/gh-aw/python/venv/bin/python application/script/builder_python_smoke.py --python /tmp/gh-aw/python/venv/bin/python --context agent --evidence /tmp/gh-aw/python/agent-smoke.json
```

The smoke uses isolated Python (`-I`) and a temporary pytest root/config outside
`application/tests`. It never imports the project's DB-reset conftest, changes it,
connects to PostgreSQL, or silently substitutes SQLite. In-process HTTP, SQL
compilation and validation exercise installed packages without network or DB.
Missing interpreter/dependency or a failed pytest returns nonzero. Existing
PYTEST_ADDOPTS/PYTEST_PLUGINS cannot silently alter the smoke.

Host reports always say HOST_ONLY. Passing `--context agent` cannot certify the
sandbox: the report remains PENDING_EXTERNAL_RUN_VERIFICATION. Review must bind
the command, interpreter, exit codes and evidence to the actual agent log/run.
The prompt requirement is not a new machine-enforced sandbox attestation gate.

## Completed local validation

- Official compiler SHA256:
  `1c74ff5fc28b1891d32b67f4348a9b7f750946b6d4a721e909187a848868016b`.
- Strict compile, exit 0, using:
  `gh-aw compile c1-gh-aw-builder-v1 --strict --no-check-update --action-mode action --action-tag 924af5fdc64061cfbf66fb584c8b07e2ac230c60`.
- YAML object comparison: after removing exactly the three named added steps,
  every existing agent step and every other job equals the base. Top-level
  trigger/concurrency/permissions unchanged. Agent execution/AWF configuration,
  source gate, 180 AIC/15 minutes/16 turns, safe-output guard and review flow unchanged.
- Host managed interpreter: Python 3.12.12; pytest 9.1.1, fastapi 0.142.2,
  SQLAlchemy 2.1.3, psycopg 3.3.6. Four real pytest smoke cases passed, exit 0.
- Four subprocess regressions passed, exit 0: missing interpreter, empty venv
  missing dependencies, real smoke with poisoned external pytest options, and
  refusal to turn an agent label into a verified sandbox claim.
- One upstream Starlette TestClient deprecation warning is retained; it is not a
  failure and did not justify changing application dependencies.
- The compiler retains the existing missing concurrency.job-discriminator warning.
  This change does not authorize batch recovery or settle that separate concern.

Evidence: `docs/runtime/evidence/20261005-builder-python-prep.json`.

## Remaining controlled validation

This workspace has no Docker/AWF runtime. Local host success does not prove
visibility or native-wheel compatibility inside the real Builder sandbox.
No paid Builder, review dispatch, workflow rerun, merge, deployment, Runtime-host
mutation, PostgreSQL setup or V73 parallel task was performed here.

After independent review and separately approved merge, read the new main SHA
and use one fresh formal task/identity for a bounded no-DB environment canary.
Do not reuse #422/#423 runs, old source anchors, or #407–#418. The canary must:

1. execute the exact prepared interpreter command inside the real agent sandbox;
2. record sys.executable, sys.version, package imports, pytest exit 0 and four
   passing cases, with host and agent reports separate;
3. read back the actual artifact and agent log, bound to the new main/run/task;
4. fail/stop on missing evidence or any environment error; no automatic retries,
   budget increases, network relaxation or batch recovery;
5. distinguish Builder transport/review delivery from test acceptance; if a scoped
   candidate is produced, bind automatic C14/C13 to its exact head and read back
   the sealed verdict instead of inferring PASS from a green workflow.

Only after that evidence should the owner choose which mapped V73 tasks resume.
PG-dependent tasks still require a separate genuine isolated PG18.4 capability
check and cannot borrow this no-DB smoke's result.

## Risk and rollback

Adds one SHA-pinned setup action and portable-runtime/dependency downloads during
trusted pre-agent preparation. Downloads may fail or take time within the unchanged
15-minute job limit. Missing wheels and package/API incompatibility stop the run.
The interpreter and packages are disposable under the existing AWF mount; no
cache is shared between jobs. Revert this candidate's workflow/script/test/docs
commit to restore the prior Builder; no DB or business-runtime rollback is needed.

## Primary source references

- https://github.com/github/gh-aw/releases/tag/v0.89.21
- https://github.com/github/gh-aw/blob/v0.89.21/.github/workflows/shared/python-dataviz.md
- https://github.com/github/gh-aw/blob/v0.89.21/pkg/cli/python_shared_env_workflow_contract_test.go
- https://github.com/github/gh-aw/blob/v0.89.21/docs/adr/26666-add-pre-agent-steps-support.md
- https://github.com/astral-sh/setup-uv/commit/d0cc045d04ccac9d8b7881df0226f9e82c39688e
- https://github.com/astral-sh/uv/releases/tag/0.12.19
