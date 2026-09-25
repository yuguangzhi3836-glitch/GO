# C14 temporal evidence boundary — Draft source candidate

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.
Reviewed source: `350552565a7469befb62d1e6bc35007110df97e9`.
Integration parent: `419a553cf2b358c016be03e73d4676aa8312eea3` (preserves the
concurrent KMS/receipt-storage increment and tests it with the time checks).
This increment is not an installation manifest or a formal C13/C14 verdict.

The Runner previously copied its start timestamp into `completed_at`; the
receiver accepted signed evidence whose completion lay after its own current
time. Signature validity alone did not establish a coherent event sequence.

The installed Runner host must now provide `now_epoch()`: an integer Unix UTC
second read from the host clock after the fixed isolated suite returns. The
`epoch` argument to `execute()` must likewise be the trusted host start time,
never a Request field. A missing clock adapter refuses before claiming. Clock
rollback, non-integer readings and durations over 3600 seconds refuse after
claiming, without publishing artifacts or Evidence. The claim is not released.
This completion check does not kill an overrun sandbox: the trusted sandbox
must still independently enforce its runtime timeout and clean up resources.

Task timestamps are exact `YYYY-MM-DDTHH:MM:SSZ`, with a 900-second admission
window. The Runner checks that window even if a faulty host freshness adapter
returns true. The receiver requires:

`issued <= started <= expires`; `started <= completed <= started + 3600`;
`completed <= verified_at <= readback_time`.

Non-UTC/naive timestamps, malformed dates and future completions fail closed.
A valid completed record may still be read after Task expiry; it cannot be
rerun. Existing receipt replay is checked against the same Evidence completion
time and current readback time. No clock-skew allowance is silently introduced;
clock synchronization is a controlled host prerequisite.

Tests use synthetic hosts/signatures only. They cover future evidence, invalid
wire times, receipts before completion or after readback, genuine completion
clock sampling, missing/bad clocks, expiry checks and late immutable readback.
No real key, signing registration, HSM call, Request, Task or runtime installation
is supplied. C13 formal signing and C14 execution remain HOLD pending real
independent identities, installed isolated Runner and signed evidence readback.
