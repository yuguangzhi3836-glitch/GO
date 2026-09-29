# Bounded complete-coverage review transport

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.

## Concrete failure and unchanged candidate

C14 run [36557919867](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36557919867)
called the real provider on frozen candidate
`059ebec3ab379099ef258effc3ab0a9833d52c35` using backend main
`2b4863540d07b9a07aed1fc4d8cec9d081602f0b`. The provider rejected input length
13,832,332 against its 10,485,760 character field limit (HTTP 400,
`string_above_max_length`). The formal result is BLOCKED. A green workflow
publishing that refusal is not C14 acceptance and does not confirm recharge.

This repair starts from that main on a separate PR. PR #279's candidate and
application tree `6570b66bc977f89c0311d67bdc6b721cd70d4e09` stay frozen. Its
payment query-reuse experiment was rolled back: 100-concurrency ABBA median
P95 improved 23.39% to 7.954 seconds, but transaction CPU improved only 6.88%.
The CPU reduction target of 20% and formal P95 <= 5 seconds were not met.
No greater-than-100 load, deployment or release is authorized by this repair.

## Transport and evidence contract

Small inputs retain one provider call. Large inputs use deterministic contiguous
UTF-8 diff ranges, preferring file boundaries then line boundaries. Every byte
is included; documentation, historical evidence and workflow diffs are not
filtered out. Each part receives all non-diff facts: complete changed paths,
brief, authoritative rules and (for C13) machine evidence. A manifest binds
candidate SHA, full facts digest, full logical prompt digest, diff digest,
every byte range, content digest and actual submitted prompt digest.

Backend limits are 512 KiB per submitted prompt, at most 64 local requests plus
one final request. The R7 rate-limit follow-up reduces concurrency to two, spaces
starts by at least 20 seconds and bounds the entire review to 25 minutes. Only
explicit HTTP 429 `rate_limit_exceeded` may retry, at most twice per request and
eight extra attempts in the whole review (at most 73 API attempts). Numeric/date
Retry-After and provider seconds/milliseconds hints extend the shared cooldown;
quota, authentication, generic 429, 5xx and opinion failures are never retried.
See RATE_LIMIT_REPAIR_20260929.md. These are application budgets, not a claim about model
context capacity. Oversized global context, too many parts, or an oversized
final context blocks before paid calls. Reports exceeding 4096 canonical UTF-8
bytes block without truncation. Worst-case final-report space is reserved
before calls. Provider context/quota/timeout failures remain BLOCKED.

Each local structured response echoes its part identity and supplies a local
opinion plus cross-file integration notes. A final fresh provider request sees
the complete manifest and every local report, including all findings. A local
FAIL or BLOCKED cannot become whole-candidate PASS or NOT_APPLICABLE. A final
NOT_APPLICABLE requires all local opinions to be NOT_APPLICABLE. All execution
IDs within a review are distinct; the final response ID is the cell's execution
identity. C13 remains a separate execution behind the same-candidate C14 gate.

The final reviewer consumes reports, not all raw source in one context. It must
BLOCK when material cross-file dependencies cannot be resolved from the reports.
Complete byte coverage is not proof that an AI understood every interaction.
Offline mocks below prove transport/validation, not semantic acceptance.

Raw provider responses, response hashes, actual prompt hashes and all completed
parts survive failure inside the outcome. Atomic BLOCKED checkpoints are written
during the run, before the final opinion. A process interruption cannot leave a
partial PASS. C13 gains raw-evidence publication using the existing credential
shape guard and the existing public-facts projection. Credential-shaped output
is refused before sealed artifact publication; it is not silently rewritten.

Sealing a completed partitioned opinion requires the original frozen facts and
recomputes the entire plan and final prompt. Readback verifies the bound response
bytes, identities, range continuity, local opinions and final decision. Readback
without original facts does not independently reconstruct the source; seal-time
replay supplies that check. Published redacted facts are explicitly projections,
not substitutes for the original full-facts identity.

The existing workflow copies the complete outcome envelope to `*_opinion.json`.
The bundle now hashes exactly those file bytes, including the batch trace. Its
inner `opinion_sha256` still identifies the semantic opinion separately. Existing
canonical-opinion artifacts remain readable with their original raw-byte hashes.
The verifier also rejects envelope/bundle identity or verdict inconsistencies.
Bundle field sets and authority semantics are unchanged.

An input-budget refusal before any API request records `ai_called=false` in raw
evidence. The existing C14 bundle schema only supports rule-source prechecks or
attempted AI calls, so it refuses to seal that transport preflight as an AI review;
the raw BLOCKED record is preserved. This patch does not invent a provider ID or
change decision-origin semantics to make that refusal look like a reviewed bundle.
Likewise, a C13 provider failure without an opinion is raw BLOCKED evidence;
sealing refuses rather than filling its legacy required identity with a synthetic ID.

## Validation and activation

Local command: `python -m unittest discover -s control-plane/c13-c14-lite -p 'test_*.py'`.
Dedicated PR CI runs this offline suite with Python 3.12 and 3.13, read-only
repository access, no OpenAI secret, no candidate execution and no deployment.
The suite covers exact UTF-8/historical-file coverage, deterministic replay,
both reviewer roles, malformed responses, invalid enums/types, missing/duplicate/
reordered parts, gaps/overlaps, source tampering, quota/time failures, checkpoints,
blocked-to-PASS contradictions, fresh IDs and actual CLI seal/workflow artifact
bytes. Existing rules, schema, ledger, prerequisite and secret-projection tests
remain part of the suite.

Offline replay of the R6 **public projection**, artifact `11029210476`:

| Field | Measured value |
| --- | --- |
| Changed paths | 1,211 |
| Diff UTF-8 bytes | 13,803,308 |
| Local parts / final mock request | 40 / 1 |
| Largest submitted prompt | 524,288 UTF-8 bytes |
| Final mock prompt | 153,817 UTF-8 bytes |
| Real API calls | 0 |
| Full plan/source replay | Verified offline |

Projection file SHA256:
`bce3e03309ece1b2ae3918ee6c54bc8a2532a956c272a655f133f8ff7f8e2a11`.
Diff SHA256: `745fc854cf316170fa8f6fd7c667a0740b8a87dc350de15b55e05bda0147f1d1`.
Plan SHA256: `1cfee85852c32b536298b96a4b5bbb1804216f039a88c06f05076a7633078dc7`.
The projection already has 25 historical bearer strings redacted by the existing
public-evidence policy; this replay makes no claim to equal original secret-bearing
facts. The formal runner must plan and verify its freshly rebuilt original facts.

Activation requires review and explicit human merge approval under `AGENTS.md`
and `docs/governance/CHANGE_CONTROL_POLICY.md`. Formal workflows consume the
approved main backend. After activation, keep the candidate SHA fixed, create a
fresh linked round on the existing Issue #270 ledger lineage, and run real C14.
Only a real provider response can establish that the API is usable after recharge;
only an admissible sealed C14 opinion allows C13. Formal capacity remains HOLD,
and release/HK/Production gates keep their existing independent requirements.
