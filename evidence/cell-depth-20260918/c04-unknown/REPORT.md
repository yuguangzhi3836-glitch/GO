# C04 UNKNOWN recovery follow-up

Source `f8fe5a969802ae1ca210f69e8bde7963c7968df2`, parent `8c59be13a1a6d39bec8c3f9ba0d64889cf4023fa`. This closes `NEXT-C04-UNKNOWN-EVIDENCE` recorded in the preceding mobility report; that earlier report and its 77-case evidence remain unchanged and source-bound.

The pre-fix real administrator HTTP path accepted another episode's reference and restored a rental order. The same path also defaulted absent or invalid history to `CONFIRMED`; `FAILED` did not validate the UNKNOWN evidence either.

The rental-owned recovery verifier now checks chain hashes and sequence, native order and evidence-row identity, current status, prior phase, supplier reference, actor and current episode. Both successful and failed recovery require the exact current episode reference. Reused references cannot open another episode on the same order, and concurrent opening has one winner. Missing/corrupt evidence retains the current state without appending evidence.

The existing `confirmation_episode_reference` API field is now forwarded through the mobility facade. Legacy callers that omit it must supply the current UNKNOWN reference. One existing rental success call was updated to pass its already-opened episode; every original assertion is retained. No model, money implementation, schema, migration, workflow, runtime or endpoint was changed.

Validation: **51 passed, 0 failed, 0 skipped**, including 35 new cases. `red.xml` records 35 pre-fix failures: 34 expose missing safety checks; one concerns the explicit concurrent-loser error code (old code already serialized the opening). `final.xml` and `final.log` contain final focused validation, including real bearer-authenticated administrator HTTP and inherited ride episode/recovery behavior. Static compilation and whitespace checks passed. Exact commands and file SHA256 values are in `COMMANDS.json` and `RESULT.json`.

Remaining: independent integrated-source C14/C13, hosted CI, true PostgreSQL competing sessions, real fleet/rental provider acceptance and visible physical three-end UI. A local correlation reference does not prove an external provider signature. No upload retry, merge or deployment occurred; the previous PR217 tool rejection remains unresolved.
