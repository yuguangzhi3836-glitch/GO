# C11 callback race follow-up

Independent C13 found a real concurrent-delivery failure after the initial scoped acceptance. The service checked the event before locking the attempt; both sessions could see no receipt, so one later failed the receipt unique constraint.

Source commit: `8e9e645e9efdc0ea4b012cb58236969354c1058e`.

The repair claims the existing event key atomically before payment state is read or changed. Only the explicit `(channel, external_event_id)` conflict is handled as a replay candidate, and its stored payload hash must match. This also acquires SQLite's writer before reading payment state. Existing PostgreSQL attempt/intent row locks remain. Any subsequent validation/constraint failure rolls the event claim back. No general IntegrityError catch is used.

- Pre-fix race regression: 6 failures, 1 pass.
- Final exact-source local regression: 101 passes, 0 failures/errors/skips, including 9 new concurrency/rollback cases.
- Intermediate 99-pass logs are retained as history; `final.*` is the final source-bound result.

The first-read barrier still ensures both concurrent sessions observe no receipt. Only each thread's first receipt lookup is synchronized, allowing legitimate conflict rereads afterward.

`STATUS.json` binds the two changed application files and records the commands, scope, limitations and next gate. PostgreSQL concurrency and independent integrated C13 review remain required. No remote write, live provider call, merge or deployment occurred.
