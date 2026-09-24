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
