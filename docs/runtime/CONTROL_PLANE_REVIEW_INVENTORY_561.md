# Scoped control-plane inventory compatibility for #561

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.

Base: a10db3e38dd2a0f4d41e0864f29e6f1365a8c76b.
Owner approved the minimal compatibility repair on 2026-10-07.

## Defect and scope

#561 freezes #560 at a99cf482d85f8f28e8fae7f10daf4ac5a62489ef.
Its two mandatory tests were rejected by the application-only explicit inventory
parser before enqueue. Removing the inventory would lose mandatory coverage.

This patch allows explicit regular `test_*.py` files directly under
`control-plane/boss-test-pr-live-integration-v1/tests/`, with the existing optional
pytest node selectors. Other control-plane components and directory-wide control
inventories remain rejected. Automatic changed-test discovery is unchanged.

Ingress resolves the allowed control-plane paths through the exact candidate's
root Git tree, validating every component's type/mode and rejecting symlinks,
submodules, missing files and invalid tree identities. Application inventories
keep their existing tree resolution. Candidate-head equality, round/idempotency
identity, max_attempts=1 and C14-before-C13 remain unchanged.

The trusted machine validator accepts the same narrow directory, checks real
filesystem boundaries and rejects symlinks at every component. No C13 workflow
execution change is needed: it already checks the exact candidate HEAD, mounts
the full checkout at `/srv:ro` and passes individual validated argv to pytest.
No host credentials, deployment actions, services or queues are added.

## Validation

Local Python 3.12 validation (isolated venv, pytest 9.1.1):

- `python -m unittest discover -s control-plane/runtime-host-channel-v1 -p test_c1_review_inventory.py`: 15 passed.
- `python -m unittest discover -s control-plane/runtime-host-channel-v1 -p test_c1_review_issue_ingress.py`: 51 passed.
- `python -m unittest discover -s control-plane/c13-c14-lite -p test_lite_machine_inventory.py`: 15 passed.
- From `application/`, pytest on both #561 control-plane files: 58 passed, 31 subtests passed.

Negative tests include traversal, unlisted components, option injection, missing
files, symlink/submodule tree entries, changed candidate refusal, unchanged
idempotency, and a real deliberately failing mixed application/control-plane
pytest run retaining exit 1 and JUnit failure evidence.

The initial local machine suite failed because pytest was absent. Installing
pytest in an isolated venv resolved that environment failure; no assertion was
removed. Local Docker is unavailable. The existing offline CI now additionally
executes both real control-plane test files in its read-only machine container
and preserves stdout, exit code and JUnit. Its result must be read after dispatch.

## Release boundary

This is an unmerged compatibility candidate, not #561's review verdict. No
runtime host was changed. After independent review, separate merge/install
authorization and installed-byte verification, consume the existing #561 issue;
do not create a duplicate review or delete its required tests. The installed
consumer and the trusted C13 backend must both include this repair. Read live
queue state first; this patch does not reset attempts or purchase a second run.
Formal C14/C13 and container evidence remain pending until actually produced.
