# GO Forge — Boss / Boss GPT Usage Contract

**Status:** Draft / pre-cutover  
**Audience:** Boss / Boss GPT  
**Environment in scope:** HK-STAGING-01  
**Related:** PR #309 (Forge design baseline), PR #312 (Task Consumer cutover / Old CC fallback), PR #320 (real Forge deployment candidate)

---

## 1. What GO Forge is for

GO Forge is the primary AI deployment operator for GO.

The normal interaction model is intentionally simple:

```text
Boss / Boss GPT
    |
    | deployment intent / Task
    v
GO Forge
    |
    | inspect candidate + inspect real environment
    | establish recovery point
    | execute deployment
    | verify deployment integrity
    v
HK-STAGING-01
    |
    v
Evidence
```

Boss / Boss GPT should describe **what should be deployed**, not manually prescribe every SSH, Docker, filesystem, or service command.

Forge owns the deployment procedure.

---

## 2. What Boss / Boss GPT owns

Boss / Boss GPT remains responsible for product direction and Candidate creation / qualification.

Typical responsibility:

1. Develop or select the intended Candidate / PR.
2. Decide that the Candidate is ready to be deployed to HK-STAGING.
3. Publish a deployment intent / Task identifying the Candidate and target environment.
4. After deployment, perform any product, business, UX, performance, or feature validation that the Candidate owner considers necessary.

A Candidate produced by Boss GPT is not automatically modified by Forge.

Candidate identity must remain stable through deployment.

---

## 3. What Forge owns

Once an authorized Candidate is handed to Forge, Forge is responsible for **delivery correctness**.

Forge must establish that:

- the intended Candidate identity was selected;
- the Candidate was not silently changed or substituted;
- the intended artifact / image / source identity reached the target;
- all intended target services run the authorized Candidate;
- declared runtime configuration / mounts / migration requirements were applied as intended;
- unexpected non-target mutation did not occur;
- a recovery point existed before mutation;
- minimum startup / health evidence is available;
- an auditable deployment record exists.

The long-term verification question is:

> **Does the actual runtime match the authorized Candidate?**

Forge is not the product-quality judge.

---

## 4. What Forge does not certify

Forge deployment success does **not** mean that the Candidate is product-correct.

Forge does not decide whether:

- a business workflow is correct;
- a page, button, payment flow, or user journey behaves as intended;
- a P95 / performance target is acceptable;
- the product design is good;
- the Candidate should become a production release.

Those are upstream product / Candidate-owner acceptance questions.

The boundary is:

```text
Forge proves:
"I deployed the Candidate you authorized."

Forge does not prove:
"The Candidate itself is a good product release."
```

---

## 5. Normal Boss workflow

The preferred Boss / Boss GPT workflow is:

```text
Create / select Candidate
        |
        v
Identify exact PR / commit / artifact
        |
        v
Request deployment to HK-STAGING
        |
        v
Forge investigates the real environment
        |
        v
Forge establishes rollback / recovery
        |
        v
Forge deploys
        |
        v
Forge returns deployment-integrity Evidence
        |
        v
Boss / product side performs business validation if needed
```

Do not begin a normal deployment by choosing an operator workstation, manually SSHing into HK, or constructing an ad-hoc command sequence.

Those may be useful recovery techniques, but they are not the normal control path.

---

## 6. Eason workstation is a degraded fallback, not a prohibition

Using Eason's workstation is **not forbidden**.

It is deliberately downgraded from a normal deployment method to a **break-glass / degraded-operation option**.

Boss GPT may consider Eason's workstation when there is evidence that the normal path is unavailable or materially impaired, for example:

- Forge cannot reach the required system;
- the normal credential / network / operator path is broken;
- the deployment operator itself requires repair;
- direct recovery requires a workstation capability that is not available through the normal Forge path;
- Eason explicitly asks for workstation-assisted recovery.

The expected escalation order is:

```text
1. Normal Task -> Forge
2. Forge investigates / repairs within its authorized capability
3. Old CC may be used as fallback where appropriate
4. Eason workstation may be used as a break-glass operator console
```

The workstation must **not** become the first idea simply because it can SSH to the server.

Before workstation-assisted mutation:

- Eason must explicitly authorize the intervention;
- the target must remain within the authorized environment;
- recovery / rollback must be understood;
- candidate identity must not silently change;
- the operation must remain auditable;
- Production remains out of scope unless separately and explicitly authorized in the future.

The workstation is an access path, not a replacement control plane.

---

## 7. Do not silently repair the Candidate during deployment

If the Candidate itself is defective, Forge must not modify it in place to manufacture deployment success.

Correct behavior:

```text
Candidate defect detected
        |
        v
CANDIDATE_DEFECT
        |
        v
stop / report / return to Candidate owner
```

Operational or environment defects may be repaired within Forge's authorized scope if recovery and audit are clear.

Candidate identity must not change secretly.

---

## 8. Legacy Command Center relationship

Old Command Center is retained as a fallback capability.

It is not the required normal path for Forge.

Target architecture:

```text
Boss Task
    |
    v
GO Forge
    |
    v
HK-STAGING
```

Not:

```text
Boss Task
    |
    v
Forge
    |
    v
Old Command Center
    |
    v
HK-STAGING
```

PR #312 tracks the Task Consumer cutover and fallback design.

Legacy CC verification assumptions must not become permanent requirements for new Forge deployments.

Where a legacy verifier carries historical implementation assumptions, a bounded compatibility repair may be performed for historical closure, but Forge should not evolve into Command Center V2.

---

## 9. Deployment verification model

Deployment verification should compare Candidate facts with runtime facts.

Examples of useful evidence:

- source commit / Candidate ID;
- artifact digest / image ID;
- target service count and exact image identity;
- runtime metadata;
- exact content tree / digest where applicable;
- declared migration requirement versus actual migration action;
- startup / basic health;
- unexpected target changes;
- recovery point and rollback identity.

File counts may be useful as human-readable supporting evidence, but count equality alone is not sufficient. Exact identity / digest / tree evidence is stronger.

Implementation details such as a historical `/workspace`, current `/app`, a particular migration revision, or a historical image tag must not be treated as permanent universal answers unless the Candidate contract actually declares them.

---

## 10. Current transition state

As of 2026-10-02:

- GO Forge has already demonstrated a real HK-STAGING deployment path with PR #320.
- Forge is the architectural direction for the primary deployment operator.
- Old CC remains available as fallback.
- PR #312 still tracks the formal Task Consumer cutover.
- Legacy verification compatibility is being closed out separately.
- Production remains out of scope.

Therefore this document defines the intended Boss / Boss GPT usage contract, but does **not** claim that every legacy consumer has already been switched off.

---

## 11. Good Boss / Boss GPT requests

Good:

> Deploy PR #NN to HK-STAGING-01. Preserve the exact Candidate identity. Inspect the real environment first, establish recovery, execute the deployment, and return deployment-integrity Evidence.

Good:

> Inspect whether PR #NN is the Candidate currently running on HK-STAGING-01. Do not mutate anything.

Good:

> Forge is unavailable. Investigate the failure first. If the normal path cannot be restored, propose the least invasive fallback, including whether Old CC or Eason's workstation is necessary.

Avoid as a default:

> Use Eason's PC, SSH into HK, run these commands, and deploy it manually.

The latter may become valid **after** a real failure makes that fallback necessary. It should not be the opening move.

---

## 12. One-sentence rule

> **Boss chooses the Candidate and deployment intent; Forge owns the normal deployment procedure and proves Candidate-to-runtime integrity; workstation/manual access remains a deliberate fallback when the normal operator path is actually impaired.**

---

## REAL_FAILURE_PREVENTED

This contract prevents a real coordination failure already visible during the Forge transition:

> Boss GPT continues reasoning from the previous operating model and reaches first for Eason's workstation / direct HK manipulation even when Forge is available, creating multiple mutation paths, bypassing Forge recovery/audit, and dragging legacy operating assumptions into the new architecture.

The control added here is intentionally small: **prefer the normal Forge path; retain workstation/manual access as an explicit degraded fallback rather than banning it.**
