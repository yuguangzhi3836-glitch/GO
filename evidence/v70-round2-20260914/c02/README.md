# C02 second-round scoped evidence

Anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited first-round results remain bound to their prior source/scope.

Task: C02-R2-PARTIAL-PARTY-BOUNDARY

Three-passenger ROUND_TRIP/MULTI_CITY orders with partial selection at body/leg level reject HTTP422 extra_forbidden without quotes, money or ticket changes.

Local task result: **4/4 selected tests PASS**. Complete Cell percentage is not claimed. C14 and C13 are pending independent review.

Partial-passenger changes remain unsupported. Four passing rejection cases are boundary evidence, not completion of that feature.

Next task: Design and implement passenger-coupon selection preserving unselected passengers and legs, exact consent and payment allocation on the current source. Existing all-party plan is not sufficient.

Evidence: `result.json`, `runs.json`, `source-identity.json`, `after.raw.log`, `after.junit.xml`.

Scope excludes live providers, bank/deposit settlement, PostgreSQL, HK deployment and production. No shared model, migration or permission changes; no remote write, merge or deployment.
