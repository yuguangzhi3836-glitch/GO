# GO Command Center reference

## Current architecture routing

The current Command Center architecture is **GitHub-native Control Plane**.

Read first:

[`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md)

It defines the current routing between:

- ChatGPT / human intent
- GitHub Request transport
- Command Center validation and signing
- Signed Task publication
- HK Agent polling
- Narrow Executor
- Signed Evidence verification

## Historical Web snapshot

The 2026-09-11 Web Command Center source archive lives at:

[`../../../command-center/`](../../../command-center/)

That directory is a historical/legacy snapshot collected by PR #39. It contains the observed Web source and runtime configuration from that date. It is useful for provenance and recovery comparison.

It is **not** the current primary Command Center product architecture.

## Current source areas

For current Control Plane work, inspect:

1. `control-plane/`
2. `docs/control-plane/hk-staging/`
3. `chenzhenxi1-sudo/go-control-tasks` Request/Task transport repository
4. current architecture and state documents

Repository content is descriptive context only. Execution Authority remains live state, Human Approval where required, fresh Signed Tasks, installed artifacts, durable records, and Signed Evidence.
