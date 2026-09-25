# C13/C14 Lite V2 — implementation map (repository facts, not guesses)

- Task: `CCV1-143-C13-C14-LITE-V2-GITHUB-IMPLEMENTATION`
- Branch: `cc/c13-c14-lite-v2-github-backend-20260925` (based on `origin/main` = `aa2ec62b`)
- Design baseline reference: **PR #247** @ `4c6561b4dcd5db61f585646f782ddd7e6e203d34` (`DESIGN_AND_FACT_BASELINE_ONLY`)
- Every path below was located in the repository; nothing is inferred from a name.

## The existing 14-Cell ledger and scheduler are real, and stay authoritative

| Object | Real path | What it already provides |
|---|---|---|
| 14-Cell ledger validator | `ci/round2/validate_ledger.py` | `schema_version:1`, `source_anchor`, exactly one cell each `C01–C14`, `events[]`, per-task `gates.{tests,evidence,c14,c13}`, `PASS_SCOPED/HOLD/FAIL`, evidence `path+sha256+source_anchor+task_id`, **C14 and C13 PASS require distinct `reviewer` identities**, `SCHEDULER_FAIL` + reconciliation |
| Ledger schema example | `ci/round2/example-ledger.json` | the exact record shape (synthetic example) |
| Ledger tests | `ci/round2/test_validate_ledger.py` | existing regression suite for the above |
| ACK / start / output admission | `ci/round2/verify_execution_receipt.py` | `cell_id`+`task_id`+`agent`+`source_anchor`+`parent_candidate_commit` binding, tz-qualified timestamps, content-addressed `execution_evidence` |
| Candidate contract precedent | `ci/round2/CANDIDATE.json` | `source_anchor`, `base_application_git_tree`, `application_git_tree`, `source_tree_sha256`, per-file `sha256`, `full_release: HOLD`, `hong_kong: NOT_ACCESSED`, `production: HOLD` |
| Signed evidence contract | `control-plane/command-center-state-v1/contracts/evidence_v1.schema.json` | `authorizes_any_action: const false` precedent |
| Canonical JSON + SHA256 + Ed25519 | `control-plane/boss-deploy-request-v1/go_deploy_request.py` | `canonical()` / `digest()` reused verbatim in convention |
| GitHub run + artifact readback precedent | `.github/workflows/c01-02-c13-independent.yml` L46–L64 (repo history) | `GET /actions/runs/{id}` + `GET /actions/artifacts/{id}` + `artifact.digest` + `not expired` assertions |
| AI review prompt / output-schema precedent | `v70-r3-ai-cell-pipeline.yml` (repo history) | `output-schema` with `enum [PASS_SCOPED, BLOCKED, FAIL]`, `ACK.json` with run id / attempt, per-role prompt files |
| Direct API call precedent | `openai-api-smoke.yml` (repo history) | one real Responses API call from CI, no agentic tooling |
| GitHub-hosted Docker/PG sandbox precedent | `c13-c14-v2-contract.yml` (repo history) | `ubuntu-24.04`, disposable image build, `upload-artifact` |

## IMPLEMENTATION_MAP

### KEEP — reused unchanged

- `ci/round2/validate_ledger.py` (**imported by path, never copied or patched**) and its SOURCE_ANCHOR
- `ci/round2/example-ledger.json` shape for the synthetic ledger
- `ci/round2/verify_execution_receipt.py`'s binding discipline (identity dict + content-addressed evidence)
- `ci/round2/CANDIDATE.json`'s candidate-contract shape
- `evidence_v1.schema.json`'s `authorizes_any_action: const false`
- `go_deploy_request.py`'s canonical JSON convention
- The existing `gates.{tests,evidence,c14,c13}` vocabulary and the "two distinct reviewers" rule

### MODIFY — extended, not rewritten

- Nothing on the hard path. The adapter *adds* a producer for existing gate
  evidence; it does not change the validator, the gate names or the statuses.

### NEW — this round

- `control-plane/c13-c14-lite/` (engine, adapter, CLI, reviewer, readback, schemas, tests)
- `.github/workflows/c14-rule-compliance.yml` — C14 read-only rule review
- `.github/workflows/c13-quality-acceptance.yml` — C13 machine job + C13 fresh AI job
- `.github/workflows/c13-c14-lite-poc.yml` — quota + run/artifact readback PoC (`POC_ONLY`)
- `docs/c13-c14-lite-v2/` — this map and the implementation plan

### DROP_FROM_HARD_PATH — forbidden on the execution path this round

- OIDC (V1.1 optional; V1 is the GitHub API readback above)
- HSM / KMS / WIF / registration authority / new ECS / new external service
- Docker + PostgreSQL inside **C14** (they belong to C13's machine job)
- CC `ReviewVerifier` / `WitnessLedger` / `FinalAcceptanceAggregator` install
- HK `AcceptanceWitness` install, any new signing key
- Any parallel C13/C14 task registry, cell registry or scheduler
- Issue writeback (the adapter is `DRY_RUN`; reviewer and scheduler write scopes stay separate)

## Deliberate non-actions

No owner PR is touched (`#202`, `#238`, `#240`, `#241`, `#245` read-only). No
historical issue or ledger fact is rewritten. No CC/HK connection is opened. No
key is generated. `#247` is referenced, never merged and never used as evidence.
