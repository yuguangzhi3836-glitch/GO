# C14 PR66 source compatibility boundary review

Date: 2026-09-13 UTC. Decision: **SOURCE_COMPAT_GATE=PASS_SCOPED**.

Reviewer: independent C14 agent; implementation owner: C12. Scope is one existing source file, `application/src/go_hotel/api/routes/operations_console.py`. No source, candidate metadata, GitHub branch, runtime, or deployment was modified by this reviewer.

## Exact source binding

Reference commit: `9f28f822110e187c22baf82391063c8b05c039c1` (PR 66).
Reference application tree: `b9aee82e8c3932a540349b1f62b714c5ea52e837`.
The reference source was independently read at the full commit from GitHub, not inferred from an unfixed local checkout.

| Item | Fingerprint |
| --- | --- |
| Reference file Git blob | `1244ebeeb0126ce92ac678120518ab44d777cd72` |
| Reference file SHA256 | `63a823940f5b72eb033d222a51cb831bb34b7e25d0d5906f07736bb0e865a4ff` |
| Repaired file Git blob | `f6f437a86598f2f7d96e6ebed74f1abc2e171c1f` |
| Repaired file SHA256 | `e945428dec148fcabdb904a3fcbd9232a3bed6a657a61dbb78869d0866113724` |

The repaired file is byte-for-byte equal to the reference with only `typing.Annotated` imported and four `vertical_snapshot` argument declarations converted. An independent AST comparison, normalizing only that import and those function arguments, found all remaining code identical.

## Boundary findings

| Boundary | Result |
| --- | --- |
| `page`, `refund_page` | Ordinary Python default 1; HTTP integer constraint `ge=1, le=1000000` preserved in Query metadata |
| `page_size` | Ordinary Python default 50; HTTP integer constraint `ge=1, le=100` preserved |
| `order_id` | Ordinary Python default None; `str \| None` and HTTP `max_length=64` preserved |
| Authorization | `p: Principal = Depends(admin_principal)` and route decorator unchanged |
| Data/query | SQL filters, exact-order lookup, sorting, count, paging/clamping, ride/rental refund isolation, hotel refund amount alias unchanged |
| Other rules | No refund execution, fee, status, schema, migration, provider, security policy, or deployment behavior changed |

The old direct Python call `vertical_snapshot('HOTEL', p=None)` received a `Query(None)` default and failed at `.strip()`. Ordinary defaults repair that existing direct-call compatibility. FastAPI still receives the same validation metadata for HTTP. A direct Python function call remains an internal call rather than an authentication or request-validation boundary; this patch does not claim to authenticate such callers.

## Evidence read and verified

C12 report: `C12_PR66_COMPATIBILITY.md`. Raw XML fingerprints were independently recalculated:

| Existing test evidence | Result | SHA256 |
| --- | --- | --- |
| `c12-pr66-compat-red.xml` | 1 failure, original Query `.strip()` error reproduced | `b236ea6a179172db1a973f4953caa84417de9dcbc8be8653f337ebfffec273aa` |
| `c12-pr66-compat-green.xml` | 12 passed, unchanged transaction-view tests | `d489b8a5ca06abceaf345627ab5497f7a9908116e018c35ec6d87ba09024d7f4` |
| `c12-pr66-pagination-green.xml` | 28 passed, unchanged pagination tests | `0a891a311212225163c93d9d73217875b704934e93973c73265dd0e587b0e934` |

These are implementation-owner test results reviewed by C14, not C14 reexecutions or new capabilities. C14 did not rerun previously passed suites. Existing original CI failure remains a failure of reference commit 9f28f822; the repaired file does not retroactively change it.

## Remaining gates

C13 owns independent necessary targeted verification. The coordinator must bind this exact repaired file into a new application tree and commit and obtain repaired fixed-head frozen CI results. This narrow source gate is not overall regression, complete browser, capacity, Final Release, merge, or deployment acceptance. No percentage completion is claimed. Hong Kong runtime is unchanged; Production remains HOLD.
