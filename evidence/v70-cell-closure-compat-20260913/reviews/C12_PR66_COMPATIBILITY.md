# C12 PR66 admin console direct-call compatibility

Date: 2026-09-13 UTC. Scope: one-file PRODUCT_FIX on the coordinator-provided PR66 candidate (head prefix `9f28f822`). This local materialized directory is not a Git checkout; the coordinator owns full commit/tree binding and remote persistence.

## Finding and correction

Inherited PR62 pagination used `Query(...)` objects as Python argument defaults. HTTP dependency injection supplied ordinary values, but the existing direct invocation `vertical_snapshot('HOTEL', p=None)` retained `Query(None)` and failed at `.strip()`. The other three pagination defaults were also Query objects.

Only `application/src/go_hotel/api/routes/operations_console.py` was edited: import `typing.Annotated`; attach the existing Query validation metadata to annotations; restore ordinary Python defaults `1`, `1`, `50`, `None`. No SQL, pagination behavior, fields, route, role dependency, status mapping, or business rules changed. Existing tests were not edited and no new tests were added.

Final source SHA256: `e945428dec148fcabdb904a3fcbd9232a3bed6a657a61dbb78869d0866113724`.

## Existing-test evidence

| Run | Result | Raw evidence |
| --- | --- | --- |
| Original `test_admin_hotel_refund_amount_is_real_column` before edit | RED: 1 failed, exact Query `.strip()` AttributeError reproduced | `c12-pr66-compat-red.xml`, `.log` |
| Entire unchanged `application/tests/test_depth41_transaction_views.py` after edit | 12 passed | `c12-pr66-compat-green.xml`, `.log` |
| Entire unchanged `ci/admin-pagination/test_pagination.py` after edit | 28 passed | `c12-pr66-pagination-green.xml`, `.log` |

The 28 tests retain six-vertical pagination, exact SQL lookup, refund isolation, page sizes, empty results, invalid parameter HTTP 422, absent authentication HTTP 401, consumer/supplier HTTP 403, and unknown vertical HTTP 404 coverage. All three executions used Python 3.12.14, pytest 9.1.1, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, and `PYTHONPATH=application/src`. The first two runs used fresh private `GO_TEST_DB_PATH` locations under `/tmp/go-c12-pr66-*`; pagination creates its own private fixture database, with `--basetemp` under a separate fresh `/tmp/go-c12-pr66-pagination-*` directory. Default workers were not disabled. Local environment is not the frozen CI environment.

Unchanged existing test SHA256 values:

- transaction views: `2125f248b60585ba5e01667c83347c89dee617f7363ecebad12bbf216f4f1217`
- pagination: `c2570af58dc54d7009eb08548dd5dc49af00902285ece78199c6202d0b1ebd1e`

## Raw evidence SHA256

| File | SHA256 |
| --- | --- |
| c12-pr66-compat-red.xml | b236ea6a179172db1a973f4953caa84417de9dcbc8be8653f337ebfffec273aa |
| c12-pr66-compat-red.log | 6068441248116a5f1ec3e8ae8f17fad9816cb1d7d9dea13d8e207230ba432059 |
| c12-pr66-compat-green.xml | d489b8a5ca06abceaf345627ab5497f7a9908116e018c35ec6d87ba09024d7f4 |
| c12-pr66-compat-green.log | 3dd1601f98d43307e51b639b135bc0fd6d08c7c5904ca4c3bd8672d3a177c87a |
| c12-pr66-pagination-green.xml | 0a891a311212225163c93d9d73217875b704934e93973c73265dd0e587b0e934 |
| c12-pr66-pagination-green.log | 08575a26359326d86df7323791cd1fb0a69af9ec05a7e94580727482710ae603 |

## Gate boundary

C12 local compatibility repair: PASS_SCOPED. These 40 existing tests are not 40 new capabilities. C13 independent review, C14 integration/source-binding checks, and repaired fixed-head frozen CI remain coordinator-owned. This result does not retroactively change the failed original CI shard. No GitHub write, merge, deployment, migration, or runtime operation was performed by this agent.
