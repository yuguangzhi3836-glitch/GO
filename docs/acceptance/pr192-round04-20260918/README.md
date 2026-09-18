# PR192 round04 pressure acceptance

Run `hk3-mu67txw3-2d1cc6` finished 2026-09-18 00:34:06.147 UTC. Generator exited and all 1000 test accounts logged out successfully. Telemetry remained healthy. The readonly sampler was stopped afterward. No additional load run or HK application change was performed.

20, 100 and 250 VUs passed the original thresholds for 60 seconds each. The 500 stage stopped at the original sustained-latency/error gate; 1000 was not attempted. This is not 1000-user acceptance.

The 500 full stage includes arrival ramp: 1074 measured requests, 8 timeouts, P95 3550.96 ms. Its measured steady interval was only 5.716 seconds: 302 requests, 3 timeouts; consumer/supplier/admin P95 4033.88/3283.12/3256.55 ms. Shutdown cancellations are explicitly excluded from both acceptance denominators.

Exact request-ID correlation against the original API container found all 1074 measured requests in the fixed 00:29:45–00:30:20 UTC window. They all eventually logged HTTP 200 server-side; the eight client timeouts were HOTEL searches with server durations 3492–4758 ms and client deadlines near 5000 ms. This does not erase the eight client failures. HOTEL server P95 was 4124.72 ms; other endpoint classes also degraded (ME 1248.01, supplier orders 1401.73, TRIPS 1420.06 ms). Measured client-minus-server duration increased well above the roughly 89 ms minimum, up to 2834 ms. This gap includes ingress, scheduling and transport outside the application timing span and cannot be assigned solely to the network.

At the slowdown API CPU reached 109.77% and its PIDs field reached 48. The generator event loop lag stayed at or below 15 ms with more than 7.6 GB free memory. API remained healthy with zero restart/OOM. DB snapshots showed one active connection (including the probe), ten idle and two idle-in-transaction, without a sampled lock wait. No SQLAlchemy pool-timeout classifier or traceback was found in the API window. Sampling cannot rule out short-lived DB contention.

Evidence supports server-side shared scheduling/CPU pressure with an additional hotel-path delay. Candidate causes include default threadpool queuing, CPU/GIL contention and the serialized hotel persistence section; the current logs lack per-span queue/DB/limiter timings to distinguish these. Increasing the hotel limiter would weaken an intentional write-race safeguard and is not justified by this evidence. No speculative performance patch was prepared.

The first diagnostic inventory was partial: its optional Health template failed for some containers, so Caddy logs were not available. The subsequent API-only collector pins the original container and exact client IDs. `server-matched-500.json` is exploratory and includes deliberate shutdown cancellations; use `server-matched-500-full.json` for acceptance attribution. The API window's 21 HTTP 400 events are outside the 1074 measured request IDs and must not be added to the acceptance error count.

Archive and every manifest member were hash-verified; independent recomputation reported zero discrepancies. `ROUND04_DIAGNOSIS.json` records exact identities, separate windows, original evidence hashes and limitations. This documentation-only evidence submission does not change application source, PR196 or HK runtime.


## Reproduce the evidence review

Decode `RAW_EVIDENCE.zip.base64.json` payload with Python `base64.b64decode`; verify the resulting ZIP SHA256 against the envelope before extracting into `evidence/`. Verify each member against `evidence/evidence-manifest-round04.json`. Then run:

```sh
python recompute_pr192.py --evidence evidence/run-01 --host evidence/host-telemetry-v2.ndjson --expected-harness 52021f1d6b42bfd1d0ad77ad52e2a254cce5b313ece199b07ff262eccd6d1aa6 --output recomputed.json
```

The archive contains the original reports, sanitized request/activity/host NDJSON, binding observations, reviewed harness and sampling/packaging sources. It contains no account file, password, bearer token, session credential or browser cookie. Session population counts are aggregate only. `match_500_server.py` is the historical read-only API-log collector source; it is evidence, not an instruction to contact HK. `server-matched-500-full.json` is its preserved stdout. The earlier exploratory output is intentionally not included; its limitations are recorded above.

Runtime binding: PR192 source `96721782158b5d665f7723305e5fb2212bd256ae`, image `sha256:6c005a88ec772ac971e560e5f29d0cfa6a8354bb16e0d52d9cbefef0def1dfe1`, observed database revision `0137_hosted_unknown_episode`. Evidence branch is based on canonical main solely for archiving; it does not assert that main equals this tested source.
