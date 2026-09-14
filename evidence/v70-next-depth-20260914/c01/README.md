# C01 — V70-R2-C01-02

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited candidate PR73 `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

Isolated mixed credit/cash settlement rejects UNKNOWN cash authorization or source-credit capture before either funding leg mutates; committed settlement with a lost response replays once.

Builder finite scope: **3/3 new cases PASS**; 3/3 selected cases PASS in the final run. Six-stage completion: 4/6; C14 and C13 remain pending. Full-domain percentage is unknown.

Limitations:

- No hotel source change; inherited zero change fee / original 365-day policy remains intact.

- Fault-injected source rows are restored only by test-fixture SQL; no production reconciliation API or external callback verification was added.

Next proposed task (not executed): V70-R2-C01-03: source-bound read-only diagnosis of mixed hotel funds before a controlled reconciliation decision.

Final raw run: `unknown.raw.log`, `unknown.junit.xml`; commands in `RUNS.json`; current source hashes in `SOURCE_IDENTITY.json`; actual task times in `EXECUTION.json`.

No dependency, model, migration, permission, deployment or remote Git operation. Existing passes are inherited with their original scope. Earlier builder runs preceded final source pinning; C13 must validate the final fixed candidate independently.
