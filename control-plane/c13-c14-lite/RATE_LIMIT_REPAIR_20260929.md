# R7 result and bounded rate-limit repair

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.
Base: approved main `632592e627c6eb831ed92af20a4e451b8e03803d` (PR #280).

## Actual R7 result

[Run 36569488918](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36569488918)
used that main backend with candidate `059ebec3ab379099ef258effc3ab0a9833d52c35`,
application tree `6570b66bc977f89c0311d67bdc6b721cd70d4e09`, and the existing
Issue #270 / #68 lineage. Its formal result is **BLOCKED / AI_PROVIDER_FAILURE**.
The green workflow means that refusal and its evidence were published.

The original input-length problem is resolved: the full diff was planned into
40 parts. Parts 0–7 returned 8 distinct, completed OpenAI response IDs with real
token-usage records. Thus the API is currently usable after recharge; this says
nothing about remaining monetary balance or unlimited throughput. Parts 8–11
received explicit HTTP 429 `rate_limit_exceeded`, with a measured limit of
500,000 tokens per minute and retry hints from 830 milliseconds to 7.562 seconds.
These are throughput failures, not `insufficient_quota`.

Four local opinions were PASS_SCOPED; four were FAIL because the candidate brief
omitted CONTROL_PLANE while changing authority/replay logic inside application/.
This is a real scope-classification defect, not a failure of the review transport.
The whole review did not finish and has no final opinion or execution ID. None
of those local opinions is whole-candidate acceptance.

All three artifact ZIP digests, the raw manifest's 9 files, the plan hash, the
8 raw response hashes/IDs/structured reports, the sealed refusal root and the
strict artifact readback were verified after download:

| Artifact | ID | ZIP SHA256 |
| --- | --- | --- |
| Sealed refusal | 11034275067 | f5676b660e7f1ba5d9a56c2821f982f01f2e15fb48f7523306d88e97972eae06 |
| Raw review record | 11033716009 | 124335d609497507b8d743379bd7e1b014eb094d9dc779defd7f1de78d08de52 |
| Readback | 11033785701 | b1c4c62b609f31929bad0bb7aad2c345752fbef1fd7195c50c4dec1bb87a6cc9 |

C14_ROOT: `da6fa74fe0662e8939cf8d593480ce7bfaf6a1e9b1b1ff244034f1f0ae99ad45`.
Plan SHA256: `8203160ef42cf64ab2120aaff7452ad8a01dcad5e3e41d191cef924682f4e97f`.
Original diff: 13,807,858 UTF-8 bytes (public redacted projection has fewer bytes).

## Small transport follow-up

The approved backend sent four requests together with no rate pacing. The fix
uses two workers and a shared monotonic request-start scheduler with a minimum
20-second gap, including the final request and retries. It does not claim this
guarantees every organization/model rate limit: other API traffic and prompt
composition can still cause 429s.

Only an explicit provider `rate_limit_exceeded` code on HTTP 429 is retryable.
The longer valid numeric/date Retry-After header or seconds/milliseconds body
hint is honored; the shared cooldown also retains the 20-second floor plus a
one-second cushion. There are at most 2 retries per request and 8 extra attempts
for the entire review, across all parts and the final request. The maximum is
64 + 1 + 8 = 73 API attempts, though the frozen candidate has 40 local parts.
No retries of quota exhaustion, generic 429, auth failures, 5xx, malformed
opinions, local FAIL/BLOCKED, or an incomplete coverage plan. No output reuse
from another round and no reduction of reviewed source.

Every recovered retry is retained in the outcome/trace; exhausted retries and
final-request failures preserve completed earlier responses. Seal/readback
reject traces claiming retries beyond the configured budgets. Review duration
is bounded at 25 minutes to accommodate pacing; the AI jobs have 35-minute
wall limits for setup, evidence publication and cleanup. Candidate-contract
expiry stays unchanged and still fails closed. C13 may require a fresh C14
round if the complete acceptance chain outlives the original C14 contract.

## Classification correction and next round

PR #279's current review brief now includes CONTROL_PLANE explicitly for AI
policy authority/binding, idempotency and receipt/claim fencing, Command Center
claim/lease/convergence/recovery and maker-checker contracts. An unchanged
control-plane directory does not mean there are no semantic authority changes
inside application/. Its prior broader assertion is explicitly corrected.

This is a brief-only correction: candidate SHA, root and application tree remain
fixed. R7's frozen brief and evidence remain unchanged. The next fresh round
must bind the corrected brief in its new full-facts/prompt/plan identity and
review all parts again; it must not resume or relabel partial R7 opinions.
No rule text, rule resolver, verdict, permission or acceptance threshold changes.

The rate repair is a separate PR for human review/merge approval, as required
by AGENTS.md. Formal workflows continue using approved main. After approval,
dispatch a fresh linked round, inspect the actual C14 opinion, and run C13 only
after an admissible sealed C14 on the same candidate. Capacity, registration
opening, HK/deployment and release keep their existing independent gates.

Validation: offline fake-clock pacing, seconds/millisecond/date header parsing,
per-request and global budgets, quota/auth/server non-retry cases, recovered and
exhausted retries, final failure retention, tampered retry evidence, plus all
existing source-coverage, refusal, schema, ledger, prerequisite and artifact tests.
No paid API calls were made to validate this patch. PR CI uses Python 3.12/3.13.
