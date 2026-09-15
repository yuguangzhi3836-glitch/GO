# C10 round two execution evidence

Source anchor: `main fef9c748adb77d37ba5d4dc4fa4662eb668303a1`.
Local candidate only; C14/C13 pending independent review.

## Result

All six verticals accepted caller facts that replaced a canonical 50000 CNY
order amount with 1 USD during both create and attach. `red.xml` records the
12 failures. The one-line merge-priority repair makes canonical order facts
win, while user notes and custom titles remain available. This changes only
new attachment snapshots; it does not rewrite old snapshots or any order,
payment, refund or business fee rule.

`green.xml`: 27 passed, no skips/errors/failures. Twelve new cases cover six
verticals at both entrypoints, persistence/readback, notes/title retention and
unchanged canonical order amount/currency. Fifteen inherited cases retain
current-status projection and authorization/missing-order fallback behavior.
Tests use isolated SQLite tables, not Hong Kong or external providers.

## Automatically continued depth task

The separate query-scaling probe measured the existing list implementation:

| Journeys | Timeline items | SELECT statements |
| --- | --- | --- |
| 1 | 1 | 4 |
| 1 | 25 | 28 |
| 25 | 25 | 52 |

These are measurements, not a performance acceptance PASS. Next C10 task is to
batch item and current-status reads while retaining member authorization,
canonical order ownership, timeline ordering and missing-order fallback.
No query refactor is included in this candidate.

Current finite fix: code + local tests + evidence ready, execution chain 4/6.
C14 and C13 are unsigned/pending; whole-domain completion is not asserted.
