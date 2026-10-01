# Candidate: stop deploying the base image's old frontend

## Confirmed source defect, not a live-host measurement

The installed-profile source Dockerfile copied the candidate to `/workspace`,
leaving the pinned base image's `/app` intact. The business Compose explicitly
sets API `PYTHONPATH=/app/src`. `go_hotel/main.py` derives its frontend root from
its own imported file. Thus the API can serve the base image's old frontend even
when image identity, `/workspace` compilation and migrations all pass. Workers
without the Compose override may meanwhile use the newer image-default path.

PR298 includes the SI SVG and GODateRange binding. The user's screenshot shows
the old AI mark; the user also reports the old two-confirm date interaction.
Those facts are consistent with this defect. This session cannot inspect the
public endpoint (browser ERR_BLOCKED_BY_CLIENT), or the installed builder bytes;
the exact live causal chain remains to be measured before claiming resolution.

## Fix

- In a disposable image layer only, remove inherited `/app`, then copy the exact
  candidate there. Do not leave removed base-source files behind.
- Match the deployed `/app` workdir and `/app/src` PYTHONPATH in TEST_PR checks.
- Verify the imported package origin and an aggregate digest of candidate `src`,
  `frontend`, `alembic`, `alembic.ini` and `pyproject.toml` against the runtime
  files before sealing. Include paths, bytes and extra files; exclude bytecode.
- Report `test-pr-v4-runtime-root`. Task schema, builder pin, dependency pin,
  network isolation, signing and eight-service deployment scope stay unchanged.

## Required controlled rollout (NOT performed here)

1. Operator reads back current installed builder recipe and test_pr.py hashes;
   confirms the split-root diagnosis against the live API import path and served
   SVG/script bytes. Preserve the existing installation and durable records.
2. Review and install only the approved recipe/test_pr.py delta through the
   authorized maintenance route; record before/after hashes and installation
   identity. Do NOT run the historical full installer: its preconditions are
   obsolete and could regress unrelated installed fixes. Do not loosen them.
3. Freeze the intended retained business candidate (PR307 includes PR298 plus
   the search-side disclosure fix). Complete its applicable reviews/admission.
   Rebuild it through a fresh TEST_PR. Existing e1049b5c... was built with the old
   profile and must not be reused as proof of this correction.
4. Only after successful new build/admission, use fresh CANARY -> VERIFY ->
   authorized DEPLOY -> post-deploy VERIFY. No migration, production, automatic
   rollback, Caddy changes or DOT Runtime changes.
5. Verify the actual public `/go-app/` HTML, script and SVG against the frozen
   candidate. On a phone-width browser, check visible SI DIRECT+ and click the
   hotel date field: select both dates in one calendar and confirm once. Check
   the submitted dates and repeat via the other date field. A health response
   or DEPLOY_OK is not this acceptance.

No host maintenance or builder installation action is exposed by the current
Boss Request schema. This source PR does not invent one or invoke SSH/Executor.
Installation requires the authorized operator/control-plane maintenance route.

## Validation boundaries

Regression tests use real local Python subprocess imports and a temporary
two-root filesystem to reproduce old/new behavior. Source digest checks run in
real subprocesses. Docker build, HK installation and live browser acceptance
have NOT been performed. All final test counts are recorded in the PR body.
