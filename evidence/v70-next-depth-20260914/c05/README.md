# C05 — V70-R2-C05-02

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited candidate PR73 `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

Reject ride recovery when the current UNKNOWN evidence is missing, chain hashes are damaged, previous phase is invalid or contradicts the immediately prior proven state; preserve supplier binding and leave UNKNOWN without compensation.

Builder finite scope: **10/10 new cases PASS**; 14/14 selected cases PASS in the final run. Six-stage completion: 4/6; C14 and C13 remain pending. Full-domain percentage is unknown.

Limitations:

- One ride-service repair plus a local chain validator. Valid recovery and terminal protections inherited and rerun only because the changed path touches them.

- This is evidence-integrity validation, not proof of a real fleet outcome or a cryptographic external signature. No production repair or compensation was added.

Next proposed task (not executed): V70-R2-C05-03: explicitly correlate fleet confirmation identity with the same current UNKNOWN episode and reject delayed confirmations from an earlier episode.

Final raw run: `phase-after.raw.log`, `phase-after.junit.xml`; commands in `RUNS.json`; current source hashes in `SOURCE_IDENTITY.json`; actual task times in `EXECUTION.json`.

Preserved red evidence: original fallback fails all eight initial corruption/loss cases; the intermediate candidate fails two correctly hashed but contradictory-phase cases. Final repair passes ten new cases plus four affected inherited ride cases. The initial relative-interpreter failure is retained separately.

No dependency, model, migration, permission, deployment or remote Git operation. Existing passes are inherited with their original scope. Earlier builder runs preceded final source pinning; C13 must validate the final fixed candidate independently.
