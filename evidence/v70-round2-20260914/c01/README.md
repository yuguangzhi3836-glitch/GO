# C01 second-round scoped evidence

Anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited first-round results remain bound to their prior source/scope.

Task: C01-R2-MIXED-FUNDING-ROLLBACK

Mixed prepaid credit and cash: 200000 redemption -> 140000 dated room -> 180000 dated room -> cancel; fault after credit release rolls back atomically; 60000 forfeiture never restored; original credit expiry retained.

Local task result: **2/2 selected tests PASS**. Complete Cell percentage is not claimed. C14 and C13 are pending independent review.

No hotel business source change. This proves this two-case local simulator scope only.

Next task: Review unknown money outcomes during mixed cash/credit checkout, retaining zero change fee, 365-day original deadline and irreversible cheaper-price difference.

Evidence: `result.json`, `runs.json`, `source-identity.json`, `after.raw.log`, `after.junit.xml`.

Scope excludes live providers, bank/deposit settlement, PostgreSQL, HK deployment and production. No shared model, migration or permission changes; no remote write, merge or deployment.
