# R8 provider refusal and safe diagnostic retention

This is a failure report and a proposed diagnostic repair, not acceptance evidence.
Classification: CONTROL_PLANE / TEST_ONLY / DOCUMENTATION.

## Observed run

The user explicitly approved merging #281 and rerunning complete C14 -> C13 on
2026-09-29 21:28 Asia/Shanghai. #281 merged as
`dfdcabab3809306cdadb40a4665c3a19fb083686`, with the exact approved root tree
`ce7487953145d27f9b80a1f06d1c56d041e78f07`.

R8 request/round: `GO-MOBILE-REGISTRATION-20260929-R8`, existing Issue #270 / #68.
Candidate: `059ebec3ab379099ef258effc3ab0a9833d52c35` (#279).
Application: `6570b66bc977f89c0311d67bdc6b721cd70d4e09`.
C14 run: https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36575907117
Job: `109431351895`; backend/head is the approved merge above.

Candidate identity, full first-parent diff, corrected review brief and rule-source
steps passed. The reviewer ran from 13:35:57 to 13:39:46 UTC. Logs report:

```text
2026-09-29T13:39:46.4562965Z {"verdict": "BLOCKED", "failure_class": "AI_QUOTA_EXHAUSTED"}
2026-09-29T13:39:46.7127880Z {"refused": "opinion_artifact_secret_shape", "detail": "openai_key"}
2026-09-29T13:39:48.9462458Z raw-evidence: refusing to publish outcome: matches openai_key
```

The GitHub artifact collection is empty. The job failed. There is no sealed C14
bundle, final admissible opinion, or usable C13 prerequisite. The reported provider
class is not a formal sealed verdict. The R8 completed-part count, HTTP status,
raw provider error body and exact matched substring are unavailable. Do not infer
them from elapsed time or from R7. The classifier only assigns this quota class
when the body contains `insufficient_quota` or `no credits remaining`; a plain
429 or explicit token rate limit remains AI_PROVIDER_FAILURE. The precise
account/project/billing cause cannot be independently confirmed from this log.

R7's eight completed provider responses demonstrated usability at that earlier
time. They do not establish continuing credit availability or a complete C14 PASS.
C13 remains WAITING_C14; original capacity/release HOLD remains unchanged.

## Proposed repair

Keep the original seal and raw-evidence secret guards unchanged. Add a separate,
always-run diagnostic step for the C14 and C13 AI jobs, with no API credential.
It exports only fixed-vocabulary classifications, bounded identifiers/status
numbers, counts, source-file hashes and secret-shape family labels. It never
copies provider messages, opinion text, response bodies, arbitrary keys, paths or
credentials. Malformed or missing inputs are recorded without copying their bytes.

Publish the result under a separate `c13c14-lite-*-diagnostic-*` artifact. Its
record explicitly says diagnostic_only=true, not_acceptance_evidence=true,
c13_prerequisite_eligible=false and authorizes_any_action=false. Existing bundle
validation rejects this record as a prerequisite, including when the source
outcome reports PASS_SCOPED. The original seal refusal still fails the workflow;
the diagnostic is not a substitute opinion, root, ledger or acceptance path.

This cannot recover R8's disposed runner files, resolve provider billing, prove a
matched string was a real credential, or make a future C14 pass. It makes the next
failure explainable without publishing the material the guard rejected. No
credential replacement, account change, guard weakening, prompt change, candidate
change, replay of partial opinions or paid retry is included.

## Validation

Local complete suite: 266 tests run, 265 passed, 1 historical POC skipped. Seven
new tests cover quota plus key-shaped text, every existing secret family and
arbitrary fields, poisoned allowlisted values, malformed/missing sources, refusal
as a C13 prerequisite, unchanged raw-evidence refusal, and both workflows' always
execution / separate artifact / no-credential boundary. Existing seal-refusal,
rate pacing and complete-coverage tests remain unchanged and pass.

All new tests are offline with synthetic inputs. No real credential or original
provider response is included here. Remote CI must bind the proposed PR head.
This new backend change remains Draft and needs its own human merge approval.
