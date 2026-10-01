# GO Forge — Persistent AI Operator Design Baseline

**Date:** 2026-10-02  
**Status:** DESIGN BASELINE / DRAFT / NOT IMPLEMENTED  
**Owner boundary:** this PR only records our design direction and next investigation steps. It does not modify boss PRs, deploy HK, change CC, run migration, or touch Production.

---

## 1. Why this PR exists

The current GO Command Center has accumulated substantial fixed workflow, gating, projection, rehearsal, publication, and verification logic.

The immediate problem is no longer "how to make the existing Command Center smarter by adding more gates."

The practical problem is:

> A qualified candidate PR can usually be deployed successfully by a general-purpose AI operator with SSH/Shell access and the existing GO/HK assets, but the fixed Command Center workflow cannot adapt well to small real-world deviations.

The recent forced deployment of PR #298 is the reference case.

WorkBuddy / Work Party was able to enter the real environment, inspect state, run the necessary commands, deal with deployment details, and get PR #298 deployed without using the full standard Command Center workflow.

That suggests a lower-cost architecture:

> Instead of spending large model/API and engineering cost to keep teaching the fixed Command Center every possible real-world exception, keep the useful capabilities and put a persistent AI operator in front of them.

This PR freezes that idea before implementation starts.

---

## 2. Product definition

# GO Forge = Persistent AI Deployment Operator

GO Forge is best understood as a **resident / always-available WorkBuddy-style operator**.

Target interaction:

```text
Boss GPT
  ↓
GitHub Task
  ↓
GO Forge AI Operator
  ↓
real environment inspection
  ↓
direct use of existing GO / CC / HK capabilities
  ↓
migration if required
  ↓
deploy
  ↓
verify
  ↓
audit / evidence
  ↓
GitHub result
```

The Boss-side interaction should remain almost unchanged:

```text
DEPLOY PR298
```

or equivalent structured task input.

The new role exists because Boss GPT currently cannot directly operate the Command Center or HK environment. It can only publish a GitHub Task and then wait for fixed automation to finish or fail.

Forge fills the missing human/operator role after task creation.

---

## 3. Important distinction: reuse capability, not workflow

This is a core rule.

We want to reuse the **capabilities and assets** that already exist in GO / CC / HK.

Examples:

- GitHub task / candidate information
- immutable commit resolution
- SSH connectivity
- HK agent / executor assets where useful
- Docker / compose deployment knowledge
- systemd services and logs
- database inspection
- Alembic / migration assets
- existing deploy scripts
- existing verify scripts
- rollback assets
- runtime/image/environment inspection
- historical Evidence
- locks / ledgers / nonce mechanisms where they solve a real failure mode

We do **not** automatically inherit the full Command Center workflow.

Forge must not become:

```text
AI
 ↓
candidate admission
 ↓
canonical provenance
 ↓
deploy readiness
 ↓
dry-run
 ↓
state projection
 ↓
state publication
 ↓
fixed gate chain
 ↓
HK
```

If AI still has to push the same standard buttons and wait for the same complete workflow, Forge has not solved the latency or complexity problem.

The target is:

```text
AI
 ↓
read real state
 ↓
decide the required steps
 ↓
use existing low-level capabilities directly
 ↓
verify
```

For every CC component considered for Forge, ask:

> What real capability does this provide?

Then reuse the capability only if it is still useful.

Do not preserve a fixed workflow merely because it already exists.

---

## 4. Candidate qualification remains upstream

Forge should not recreate candidate governance.

The upstream development process is responsible for producing a qualified Candidate PR.

Forge consumes that candidate.

Normal start:

```text
Candidate PR
 ↓
resolve to immutable SHA
 ↓
inspect environment
 ↓
deploy
```

Forge should not repeatedly re-prove that the candidate is a candidate unless a specific safety fact is required for deployment.

The deployment target must be immutable.

Example:

```text
candidate_pr  = 298
candidate_sha = <immutable SHA>
target        = HK-STAGING-01
```

---

## 5. Why AI is required

The value of AI here is not command execution itself.

The value is **bounded operational judgment**.

A fixed automation path often behaves like:

```text
A PASS
B PASS
C FAIL
→ task stops
```

An AI operator can instead do:

```text
C FAIL
 ↓
inspect actual error
 ↓
inspect logs / runtime / DB / container / service
 ↓
classify the deviation
 ↓
choose a safe response
 ↓
continue / retry / recover / rollback / abort
```

This is the primary reason to introduce Forge.

If every decision is converted back into hard-coded gates, there is little reason to use an LLM.

---

## 6. AI autonomy boundary

Forge should have real Shell / SSH operating capability.

It is not limited to a tiny set of single-purpose "deploy" buttons.

It may use existing operational tools such as:

```text
git
docker
docker compose
systemctl
journalctl
curl
psql
alembic
sha256sum
grep
diff
existing GO/HK scripts
existing verify tools
existing rollback tools
```

The important restriction is the **scope of mutation**, not the existence of Shell access.

### 6.1 AI may change the deployment process

Examples:

- inspect logs
- wait for a slow service
- retry a transient command
- stop/remove a stale container
- select an existing equivalent execution path
- run an existing migration
- verify migration head
- recover runtime state
- fix an execution/runtime problem in CC or executor
- adjust execution ordering
- use rollback
- re-run verification
- clean a clearly stale task/lock when evidence proves it is safe

### 6.2 AI must not silently change the delivery artifact

The Candidate is fixed.

Forge must not, merely to manufacture a successful deployment:

- modify Candidate source code
- add commits to the Candidate
- replace the immutable SHA
- rewrite Candidate migration files
- invent a new DB schema to make the Candidate fit
- patch business code directly on HK
- bypass final verification
- declare success when the deployed bytes are not the requested Candidate

Core rule:

> AI may change the execution method, but it must not secretly change the deployment target.

If continuing requires Candidate modification:

```text
RESULT     = CANDIDATE_DEFECT
DEPLOYMENT = ABORT
```

That becomes a development task, not a deployment workaround.

---

## 7. Deployment tolerance envelope

The AI should not stop for every minor deviation, but it also must not "heroically" force an incompatible version into place.

### GREEN — Operational Variance

AI may handle autonomously.

Examples:

- transient connection failure
- service startup delay
- stale container
- expected old runtime residue
- expired historical task state
- safe retry
- equivalent existing command/tool path
- migration already at target head, therefore skip duplicate execution

### YELLOW — Material Drift

AI should investigate, collect evidence, and only continue if the situation can be proven to remain within the intended deployment.

Examples:

- unexpected DB generation
- runtime/image differs materially from expected starting state
- required dependency missing
- environment generation unclear
- executor installation drift
- migration chain cannot be established confidently

If the drift cannot be safely reconciled without altering the Candidate, abort.

### RED — Candidate / Delivery Mutation

Forbidden inside the deployment task.

Examples:

- edit Candidate source
- create an unreviewed Candidate commit
- manually redesign DB schema
- change migration logic
- deploy a different SHA
- skip final verify

---

## 8. Audit is mandatory

Forge is allowed to act more freely than fixed automation, therefore its audit trail must be stronger and more direct.

Do not create a large secondary audit platform.

Use an append-only action/evidence model.

Every task should preserve two layers.

### Layer 1 — machine action log

Automatically capture:

```text
timestamp
task_id
host
cwd
command/tool
arguments
exit_code
stdout
stderr
before state where applicable
after state where applicable
```

The AI must not be able to replace these facts with a natural-language summary.

### Layer 2 — AI decision log

For non-trivial decisions record:

```text
observation
classification
decision
reason
action
result
next_step
```

The objective is operational auditability, not disclosure of hidden chain-of-thought.

A useful record should answer:

> What did the AI observe, what did it decide, why was that action inside the allowed boundary, and what happened afterwards?

Example evidence bundle:

```text
task.json
actions.jsonl
decisions.jsonl
stdout.log
stderr.log
before.json
after.json
verify.json
summary.md
```

---

## 9. Controls that should remain hard-coded

AI judgment should handle operational detail.

A small set of controls should remain enforced by the runtime because they prevent clear real-world failures:

1. fixed allowed repository
2. fixed allowed target: HK-STAGING-01 for this phase
3. Candidate resolved to immutable SHA
4. only one mutation task for the same environment at a time
5. task deduplication / idempotency
6. migration double-run prevention
7. automatic action logging
8. final verification is mandatory
9. Production access denied in this phase
10. crash/restart recovery must know whether the task was not started, in progress, complete, failed, or requires investigation

Any additional hard-coded control must answer:

> Which concrete real-world failure does this prevent?

If that answer is unclear, prefer AI judgment plus audit rather than another permanent gate.

---

## 10. Cost model

The objective is to move cost from "continually modifying a rigid control plane" to "paying for AI only when useful operational judgment is needed."

Normal deployment work is usually:

- read state
- interpret command output
- follow a known runbook
- handle small deviations
- execute existing tools
- verify

This should be suitable for a low-cost model and may potentially work with a free/very-low-cost API model if reliability is demonstrated.

Proposed model strategy:

```text
normal task
→ low-cost model

ordinary operational exception
→ same model investigates first

complex / ambiguous exception
→ escalate to stronger model

outside allowed boundary
→ abort + human/development task
```

The architecture must not require a premium model for every simple deployment step.

---

## 11. Minimal first implementation shape

Do not start implementation until the investigation below is complete.

The expected first version may be very small:

```text
forge-worker.service
├── GitHub Task listener
├── LLM client
├── SSH / Shell execution tool
├── GitHub read/write tool
├── audit wrapper
├── task state / lock / dedupe
└── deployment runbook / policy
```

The first implementation should avoid a large agent framework unless the investigation proves one is necessary.

---

# 12. Next work — Phase 001A

## PR298 Shadow Deployment / Runbook Discovery

Before writing Forge, ask WorkBuddy / Work Party to simulate deploying PR #298 again.

**This is read-only. Do not redeploy PR298.**

PR298 is already running and is used only as a real case from which to extract the operator process.

### Goal

Pretend the input is:

```text
TASK   = DEPLOY PR298
TARGET = HK-STAGING-01
```

Reconstruct the historical pre-deployment state as far as evidence allows, then walk through:

```text
candidate resolve
→ inspect current/historical state
→ compare candidate vs environment
→ migration decision
→ migration procedure if required
→ deploy procedure
→ verify
→ evidence
→ success / abort
```

For every step record:

```text
OBJECTIVE
OBSERVE
COMMAND_OR_TOOL
EXPECTED
DECISION
IF_NORMAL
IF_VARIANCE
IF_MATERIAL_DRIFT
STOP_CONDITION
EXISTING_CAPABILITY
CC_WORKFLOW_REQUIRED = YES/NO
WHY
```

### Historical reconstruction rule

Because PR298 is already deployed, current HK state must not be presented as if it were the original pre-deployment state.

Use historical sources where available:

- GitHub history
- Task / Evidence
- deployment logs
- systemd journal
- Docker history
- runtime/image facts
- DB/migration history
- existing audit records

Anything not proven must be marked:

```text
UNKNOWN
```

No guessing.

### PR298 incident review

Identify the actual obstacles encountered during the PR298 deployment and compare:

```text
fixed automation response
vs
AI operator response
```

For each obstacle answer:

- what actually happened?
- why did the fixed path struggle or stop?
- what did / could an AI operator safely do?
- did it require Candidate modification?
- what evidence should be retained?
- should this become hard-coded logic, or remain AI operational judgment?

### Deliverable

```text
GO-FORGE-001A-PR298-SHADOW-DEPLOYMENT-2026-10-02.md
```

It must include:

1. reconstructed PR298 before-state
2. full shadow deployment
3. actual PR298 exception review
4. decision tree
5. operational variance boundaries
6. abort conditions
7. directly reusable existing capabilities
8. CC fixed workflow that does not need to be inherited
9. audit requirements
10. AI_DEPLOYMENT_RUNBOOK_V0
11. issues that must be solved before Forge implementation

### 001A mutation policy

```text
GITHUB_WRITE     = NO
SERVER_WRITE     = NO
DEPLOY           = NO
MIGRATION        = NO
CANARY           = NO
ROLLBACK         = NO
SERVICE_RESTART  = NO
DOCKER_MUTATION  = NO
DB_MUTATION      = NO
PRODUCTION       = NO
SECRET_DUMP      = NO
```

---

# 13. Next work — Phase 001B

## Targeted Live Inventory

Only after 001A tells us what an AI operator actually needs, perform the broader live inventory.

Do not inventory everything merely because it exists.

For each relevant component classify:

```text
DIRECT_OPERATOR_CAPABILITY
SAFETY_CONTROL
OBSERVABILITY
AUDIT_ASSET
FIXED_CC_WORKFLOW
LEGACY_UNUSED
UNKNOWN
```

Focus on:

- exact Shell/SSH paths available to a resident Forge worker
- existing deployment scripts
- existing migration assets
- existing verify / rollback capabilities
- HK agent / executor components
- CC components that expose useful low-level capability
- locks / ledgers / task state
- evidence storage
- installed systemd services and timers
- live binaries and their GitHub correspondence
- credentials architecture without dumping secrets

Key question:

> What is the minimum existing capability set required for an AI operator to safely deploy a qualified Candidate without running the entire Command Center workflow?

Deliverable:

```text
GO-FORGE-001B-LIVE-CAPABILITY-INVENTORY-2026-10-02.md
```

Still read-only.

---

# 14. Next work — Phase 002

## Thin Forge Architecture Proposal

Only after 001A and 001B.

Design the smallest persistent AI operator that can execute the runbook.

The proposal must answer:

- where Forge Worker should run
- how it receives GitHub Tasks
- how it authenticates to GitHub / CC / HK
- whether it needs a permanent API endpoint
- how Shell commands are wrapped and audited
- how task locking and dedupe work
- how restart/crash recovery works
- how migration double-run is prevented
- how model selection/escalation works
- how API keys are stored
- how candidate immutability is enforced
- how final verification is enforced
- how Production is denied
- which existing CC/HK assets are reused directly
- which fixed CC workflow is intentionally bypassed

Deliverable:

```text
GO-FORGE-002-PERSISTENT-AI-OPERATOR-PROPOSAL-2026-10-02.md
```

No implementation until this proposal is reviewed.

---

# 15. Expected sequence

```text
THIS PR
Design baseline frozen
        ↓
001A
PR298 Shadow Deployment
        ↓
AI_DEPLOYMENT_RUNBOOK_V0
        ↓
001B
Targeted capability inventory
        ↓
002
Persistent AI Operator architecture
        ↓
review
        ↓
small prototype
        ↓
controlled non-production test
```

---

## 16. Non-goals for this phase

Do not use GO Forge as an excuse to:

- rebuild Command Center V2
- redesign Candidate governance
- add another large migration subsystem to current CC
- rebuild C13/C14 independence/governance concepts
- add zero-trust architecture without a real failure case
- touch Production
- replace working assets simply because their implementation is old
- hard-code every operational exception discovered during PR298

---

## 17. Acceptance criteria for the eventual Forge

The design is successful if:

1. Boss GPT can still create a normal GitHub Task.
2. A resident AI operator can take over from that point.
3. A normal qualified Candidate can be deployed without a human entering the server.
4. Small operational deviations are handled by AI rather than causing immediate workflow failure.
5. Material drift causes investigation or abort, not uncontrolled "hero fixes."
6. Candidate bytes / immutable SHA are not silently changed.
7. Migration is executed only when required and cannot accidentally double-run.
8. Final verification is mandatory.
9. Every real action is auditable.
10. Existing useful GO/CC/HK capabilities are reused.
11. The full legacy Command Center workflow is not required for every deployment.
12. The system is materially simpler and cheaper to operate than continually extending the current fixed CC.

---

## 18. One-sentence baseline

> GO Forge is not a new Command Center. It is a persistent WorkBuddy-style AI operator that receives a qualified GitHub Candidate, directly uses existing GO/CC/HK operational capabilities, adapts to bounded real-world variance, keeps the Candidate immutable, and records every action for audit.
