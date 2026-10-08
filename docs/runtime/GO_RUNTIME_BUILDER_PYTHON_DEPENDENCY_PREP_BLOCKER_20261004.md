# GO Runtime Builder Python dependency prep blocker

Status: `LIVE_VALIDATION_PENDING`
Date: `2026-10-04`
Scope: `C12 builder sandbox Python test dependency preparation only`

## What was verified

- The runner host Python is present and fixed:
  - `python3 --version` -> `3.12.3`
  - `sys.executable` -> `/usr/bin/python3`
- Before any setup, the runner host does **not** have the Builder's required test/runtime
  imports:
  - `pytest` -> `ModuleNotFoundError`
  - `fastapi` -> `ModuleNotFoundError`
  - `sqlalchemy` -> `ModuleNotFoundError`
  - `psycopg` -> `ModuleNotFoundError`
- `application/pyproject.toml` is the correct dependency source:
  - runtime: `fastapi`, `sqlalchemy`, `psycopg[binary]`, etc.
  - dev: `pytest`, `pytest-asyncio`
- The compiled Builder workflow proves that controlled pre-agent preparation is
  *architecturally feasible without relaxing isolation*:
  - the AWF launch uses `--container-workdir "${GITHUB_WORKSPACE}"`;
  - it forwards environment with `--env-all`;
  - it mounts the workspace read/write into the sandbox;
  - it mounts `/tmp/gh-aw` read/write into the sandbox.

These facts mean a pre-agent step could prepare a venv or dependency directory on the host
and pass it into the sandbox through the existing workspace or `/tmp/gh-aw` mounts, without
adding `host.docker.internal`, `docker.sock`, privileged mode, host networking, or new
network allowances.

## Blocker

This task explicitly forbids hand-editing the generated lock file and requires strict
recompile with `gh-aw v0.89.21`.

That compiler is not available on this runner through the documented path:

- `gh aw --help`
- `gh aw compile --help`

Both attempt extension installation and fail before compile with:

```text
failed to install extension: could not check for binary extension:
Get "https://api.github.com/repos/github/gh-aw/releases/latest":
tls: failed to verify certificate: x509: certificate is not valid for any names,
but wanted to match api.github.com
```

Additional bounded checks found:

- staged gh-aw action helpers under `/home/runner/work/_temp/gh-aw/`;
- AWF bundles under `/opt/hostedtoolcache/agentic-workflow-firewall-js/0.28.23/`;
- no local `gh aw` compiler binary or cached extension that can regenerate
  `.github/workflows/c1-gh-aw-builder-v1.lock.yml`.

## Conclusion

The Builder Python dependency-prep change should be implemented as a pre-agent setup step
plus a real no-DB pytest smoke, but it cannot be delivered safely in this environment
because the required lock regeneration tool is unavailable.

No workflow source or lock change was made from this branch. This note records the exact
blocker instead of guessing compiler behavior or hand-editing generated workflow output.
