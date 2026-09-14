# C05 second-round scoped evidence

Anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited first-round results remain bound to their prior source/scope.

Task: C05-R2-REPEATED-UNKNOWN-FULFILLMENT

Two unknown-result episodes across CONFIRMED and IN_PROGRESS restore the respective phase; unknown blocks fulfillment; completion cannot restart; single START/COMPLETE evidence; no refund.

Local task result: **1/1 selected tests PASS**. Complete Cell percentage is not claimed. C14 and C13 are pending independent review.

No ride business source change. This is local simulator evidence, not a real vehicle or fleet journey.

Next task: Check evidence-loss/corruption recovery boundaries before accepting a historical UNKNOWN result, then bind provider confirmation to the same ride phase.

Evidence: `result.json`, `runs.json`, `source-identity.json`, `after.raw.log`, `after.junit.xml`.

Scope excludes live providers, bank/deposit settlement, PostgreSQL, HK deployment and production. No shared model, migration or permission changes; no remote write, merge or deployment.
