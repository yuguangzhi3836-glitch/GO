# C13 first / isolated Hong Kong C14 admission proposal

The source-only gate encodes the Owner's revised sequence. It admits a first
formal C13 test for a Command Center approved candidate and scope. It admits a
Hong Kong isolated C14 retest only after the host verifies a C13 PASS_SCOPED
evidence object bound to the same candidate SHA, application tree and test scope.
The two test actors must be distinct. Neither decision authorizes release.

The `Host` protocol is a dependency on the existing Command Center trust root,
not a new authority. An unconfigured checkout has no host implementation and
cannot issue signed tasks or publish to `go-control-tasks`. A real adapter must
read the immutable source and signed evidence from authoritative storage and
apply the existing task signing, persistence and readback rules. The Hong Kong
isolated Runner must be installed and separately restricted from staging
deployment. Those runtime facts are **not** proven by these unit tests.

Run the refusal checks locally with:

```sh
python -m unittest discover -s control-plane/c13-c14-v2 -p 'test_*.py' -v
```

This Draft has no runner installation, KMS call, C13/C14 execution, request
dispatch, Hong Kong change, provider/payment access, merge or deployment.

## Signed task / evidence protocol (Draft)

`task_evidence.py` accepts **only an admission already derived by the gate**.
It creates a deterministic task ID from the action, environment, independent
runner, candidate SHA, application tree and frozen test-scope digest. A C14
task also binds the verified C13 evidence SHA-256; the host must independently
re-read and verify that prerequisite at issuance. It requires an injected
host signer, stores the signed envelope, reads it back and verifies its
signature and exact bytes. No caller may supply a command, path, URL,
provider, deployment or production action. Task lifetime is 30 minutes.

After execution, the host must read the runner-signed evidence and three raw
artifacts (`junit`, `stdout`, `manifest`) from authoritative storage. The
protocol checks the runner identity, task/source/scope identity, C13 digest on
C14, every artifact SHA-256, manifest fields and JUnit counts. A PASS needs at
least one executed test and zero failures, errors and skips. The host remains
responsible for checking the actual candidate tree and frozen test command,
executing in a restricted environment, qualifying independent actors, signing
with keys held outside the repository, making storage immutable, and reading
the result back from the actual task bus. The unit-test host is memory only.

The local contract suite is:

```sh
python -m unittest discover -s control-plane/c13-c14-v2 -p 'test_*.py' -v
```

The real `go-control-tasks` contract, Command Center host adapter, isolated
C13 Runner, Hong Kong isolated C14 Runner and signed evidence readback are not
installed by this Draft. **No formal C13 or C14 can be claimed from these
tests.** Do not route these action IDs through TEST_PR, CANARY or DEPLOY.

**Integration mismatch to resolve:** this module's `{payload, signature}` is
an internal test proposal, not the installed `task_v1.schema.json` house
envelope. The installed contract allows only `HK-STAGING-01` and six existing
actions; neither acceptance action/environment is registered. A host must
derive the existing house envelope, extend and validate its closed action and
environment contract through normal review, and provide a separate restricted
acceptance executor before writing any real bus object. Passing a proposal
directly to `go-control-tasks` is invalid. The in-memory `publish_task` test
does not perform or prove that integration.
