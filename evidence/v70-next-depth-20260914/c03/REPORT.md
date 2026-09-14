# C03 — V70-R2-C03-02

EVIDENCE_READY (4/6 stages), independent C14 then C13 still pending. Whole-domain completion is unknown.

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited candidate: `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

Rail checkout-to-payment-root handoff with cancellation/expiry and full-target inventory before supplemental money; isolated SQLite transactions.

No product change required. Four new real overlap/inventory assertions retain the inherited implementation.

Current targeted result: **4 PASS, 0 failures, 0 errors, 0 skips**. Exact command, unique SQLite DB path, timestamps, source hashes before/after, raw output and JUnit remain alongside this report.

boundary-first has 3 PASS / 1 FAIL caused by an incorrect test helper signature; it is preserved as harness evidence, not a product regression. Corrected helper yields 4 PASS against unchanged rail source.

Remaining concrete scopes:

- PostgreSQL execution of these C03 races remains unproven.
- Actual railway operator seat maps and external money/provider evidence are outside this engineering simulation.

Next executable task for scheduler: `V70-R2-C03-03` — Run the four source-bound payment/inventory races under isolated PostgreSQL and audit order/root/claim convergence after process exit.
