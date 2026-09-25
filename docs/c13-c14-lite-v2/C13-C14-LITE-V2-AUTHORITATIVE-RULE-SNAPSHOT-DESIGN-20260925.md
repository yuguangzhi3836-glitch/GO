# C13/C14 Lite V2 — Authoritative Rule Snapshot: gap report + minimal input supplement

> Round 3 decided that C14 must stop being asked to judge compliance from rule **names** alone.
> This document (a) reports what authoritative rule content actually exists **right now**, and
> (b) designs the smallest input supplement that can carry it.
>
> ⛔ **No rule text was authored, paraphrased, reconstructed or mapped in this document.** Where
> the normative text does not exist, that is reported as a gap and left open. Inventing rule text
> would manufacture the authority C14 exists to check.

- Date: 2026-09-25
- Basis commit (everything below was read at this commit, read-only): `64715d308954049eb6675d81196d7f4cd853199b` (current `main`)
- Trigger: Round 3 C14 run `361523947948` returned `BLOCKED` (see `C13-C14-LITE-V2-ROUND3-EVIDENCE-CCV1-145B-20260925.md` §4)
- Scope: **design only.** No source change, no workflow change, no dispatch, no deployment.

---

## 0. The three human decisions this document serves

```text
A  Rule input      -> supply C14 a frozen authoritative_rule_snapshot. Round 3's BLOCKED stands
                      as a correct historical verdict: not withdrawn, not rewritten, but not the
                      final design target either.
B  Seal-refusal     -> NO dedicated live drill. Covered by PR #254's offline regression. Keep
   live drill          "raw evidence survives a refusal" as a natural-failure item only; it is
                      NOT an independent blocker for C13. No test switch, no deliberate input
                      corruption, no extra production run to turn it green.
C  Round-3 commits  -> PUSH = YES (done separately; docs/evidence only).
```

---

## 1. The gap, measured

### 1.1 The three rule names have no normative text anywhere in the current repository

```sh
git grep -l '<name>' 64715d30        # at current main
```

```text
GO_CONSTITUTION       5 files
    .github/workflows/c14-rule-compliance.yml              <- ours (the default input value)
    application/src/go_hotel/autonomy/definitions.py       <- NOT rule text; see 1.2
    hk-staging/source/runtime/src/go_hotel/autonomy/definitions.py     <- mirror of the above
    deliverables/CP11_DEPTH48_.../source/.../definitions.py            <- archived copy
    deliverables/CP11_DEPTH48_.../source/hk-staging/.../definitions.py <- archived copy

PERMISSION_BOUNDARY   1 file
    .github/workflows/c14-rule-compliance.yml              <- ours, and nothing else

AI_BEHAVIOUR_RULES    1 file
    .github/workflows/c14-rule-compliance.yml              <- ours, and nothing else
```

⇒ Two of the three names exist **only inside the workflow file we wrote**. There is no document,
charter, policy or specification in the repository that defines what they require.

### 1.2 What is in `definitions.py` is a capability declaration, not rule text

`application/src/go_hotel/autonomy/definitions.py` (authoritative, on `main`) declares the C14
cell itself:

```python
C14_AI_LEGAL = _cell(
    "C14",
    "AI Constitutional, Legal & Regulatory Control Cell",
    "AI_CONSTITUTIONAL_LEGAL_REGULATORY_CONTROL",
    "CONSTITUTIONAL_LEGAL_COMPLIANCE_DECISION_TRUTH",
    "GO_CONSTITUTION_REVIEW",            # <- a capability NAME, not the constitution's text
    "AUTHORITY_CONSTITUTION_REVIEW",
    "LEGAL_EXPOSURE_ROUTING",
    ...
    forbidden=("BUSINESS_DOMAIN_TRUTH_MUTATION", "SELF_AUTHORITY_EXPANSION"),
)
```

The single `GO_CONSTITUTION` hit is the **capability string** `GO_CONSTITUTION_REVIEW`, and it is
only reached as a substring. The file also says, about accountability:

> *"Legal accountability intentionally remains unbound in Build 01. Production qualification is
> fail-closed until a Named Human Role + Legal Entity are provided by the Human Constitutional
> Core."*

That is a **fail-closed declaration that the authority is not yet bound** — which is consistent
with, not a substitute for, the missing rule text.

### 1.3 The nearest existing normative documents, none of which is named as these rules

| Artifact (on `main`) | What it authoritatively is | Why it is **not** automatically the rule text |
|---|---|---|
| `docs/governance/CHANGE_CONTROL_POLICY.md` (67 lines) | The repository's normative change-control policy, with an explicit **"AI-agent self-constraint"** section | It is not named `AI_BEHAVIOUR_RULES`; adopting it under that name is an **authority decision**, not a derivation |
| `application/governance/workbench/cell_charters/C04_CELL_CHARTER.json`, `C05_CELL_CHARTER.json` | The established per-cell normative pattern (`owned_paths` / `forbidden_paths` / policy strings / `final_merge_authority`) | Charters exist for C04 and C05 only — **no C13/C14 charter exists**; and a charter is a scoping document, not a rule set |
| `application/src/go_hotel/autonomy/definitions.py` | The authoritative cell/capability/truth registry | Declares capabilities and forbidden capabilities — never normative obligations |
| `deliverables/CP11_DEPTH18_20260908/MASTER_V7_PARAGRAPH_TRACE.json` | A paragraph-level trace of a V7 master document (369 KB, carries a `master_sha256`) | It is a **deliverables/ archive** of an earlier depth; it contains **zero** occurrences of any of the three rule names. Reading it would be exactly the "archaeology into old rules" that this round forbids |

### 1.4 Conclusion of the gap report

```text
GO_CONSTITUTION      normative text: NOT PRESENT in the current repository
PERMISSION_BOUNDARY  normative text: NOT PRESENT in the current repository
AI_BEHAVIOUR_RULES   normative text: NOT PRESENT in the current repository

The three names are OUR OWN defaults (control-plane/c13-c14-lite/lite_cli.py:52,
DEFAULT_APPLICABLE_RULES). The test fixture openly labels their versions "synthetic-v1".

⇒ C14's Round 3 BLOCKED is not the model being difficult. It was asked to assess compliance
  against three rule sets whose contents were never supplied. As currently fed it can never
  return PASS_SCOPED — correctly so.
```

---

## 2. Minimal input supplement — `authoritative_rule_snapshot`

### 2.1 Shape (exactly the six required fields)

```json
{
  "schema_version": "go.c13c14.authoritative_rule_snapshot.v1",
  "rules": [
    {
      "rule_name": "GO_CONSTITUTION",
      "rule_version": "<as declared by the authoritative source, else a derived identity>",
      "authoritative_source": {
        "path": "<repository path on the default branch>",
        "blob_sha": "<git blob SHA of that path at the frozen ref>",
        "ref": "main"
      },
      "rule_text": "<the normative text, verbatim, byte-for-byte>",
      "sha256": "<sha256 of the rule_text bytes>",
      "effective_at": "<ISO8601>"
    }
  ]
}
```

Notes on two fields that could otherwise be filled in dishonestly:

- **`rule_version`** — every rule is `unversioned` today, so the design must not invent a version.
  Two acceptable forms, in order of preference:
  1. the authoritative source declares a version → use it verbatim;
  2. it declares none → use a **derived identity** `sha256:<first 16 hex of the rule_text digest>`,
     and the field must be labelled as derived so nobody later reads it as an authored version.
- **`effective_at`** — the date the text became authoritative, taken from the authority, not the
  date the snapshot file was committed.

### 2.2 Where the snapshot lives, and why not elsewhere

**Recommendation: a single JSON file committed on the frozen candidate**, at a fixed path
(proposed `docs/c13-c14-lite-v2/authoritative-rule-snapshot.json`; reusing an existing directory —
no new service, no new registry).

- ⛔ **It cannot be a dispatch input.** Measured: `c14-rule-compliance.yml` declares **exactly 10**
  `workflow_dispatch` inputs, and GitHub's hard ceiling is **10**. Adding an input is impossible,
  and passing normative text through dispatch would bloat the payload anyway. The existing
  `applicable_rules` input stays what it is — the **selector** — and the snapshot supplies the
  **content**.
- ⛔ **It should not live in the pinned execution backend.** The pinned backend is our own review
  code; the rules are the Owner's normative content. Putting the text in our backend would make the
  reviewed authority a property of the thing being reviewed.
- ✅ **On the candidate it is inside the frozen identity**, so the exact rule set a verdict was
  produced against cannot drift afterwards.

### 2.3 The anti-self-serving check (what stops a candidate writing its own rules)

A candidate that could author its own rule text could trivially produce its own pass. So the
snapshot is **not trusted on its own**: for each entry, C14 re-reads `authoritative_source.path`
from the **default branch** through the same read-only contents call the workflow already makes for
D-2 (`lite_cli.py workflow-identity`, one API call, proven working in step 6 of runs
`36141430817` / `36148838395` / `36152394748`), and compares that blob against
`authoritative_source.blob_sha` and the text against `sha256`.

⇒ Reuse of an already-proven capability. No new service, no new credential, no new permission
scope (the workflow already has `contents: read`).

### 2.4 Binding into the frozen record

One added field, in four places that already exist:

| Where | Field | Purpose |
|---|---|---|
| `lite_cli.py:329-336` `cmd_scope` payload | `rule_snapshot_sha256` | the frozen scope digest now covers *which rule content* was under review |
| `lite_cli.py:166-167` `_facts()` (C14 branch) | `rule_text` per rule | this is the whole delivery mechanism — see 2.5 |
| `lite_cli.py:285-286` `cmd_seal` | `authoritative_rule_snapshot_sha256` + per-rule `sha256` | the sealed record states the exact rule content it judged against |
| workflow step 7 (scope freeze) | one extra `--rule-snapshot <path>` argument | passes the path; the file itself is read from the candidate checkout |

D-3's discipline carries over unchanged: **one derivation, and the record cannot widen or narrow
the set it was reviewed against.**

### 2.5 Why this is genuinely minimal: the prompt needs no change

`lite_ai_reviewer.build_prompt` (line 143-144) serialises the **entire facts dict** into the prompt:

```python
        "FROZEN CANDIDATE",
        json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2),
```

⇒ Once rule text is a facts field, it reaches the reviewer automatically. **No reviewer change, no
new prompt template, no new tool.** The supplement is: load one file, verify its digests, put its
text into `facts`, and put its digest into the scope payload and the sealed record.

### 2.6 Fail-closed semantics (the part that must not be softened)

| Condition | Required outcome |
|---|---|
| Snapshot file absent | `BLOCKED`, reason names the missing snapshot path |
| A name in `applicable_rules` has no snapshot entry | `BLOCKED`, reason names that rule |
| `rule_text` in the snapshot ≠ the text at `authoritative_source.path` on `main` | `BLOCKED`, digest mismatch |
| `rule_text` empty / placeholder | `BLOCKED` — an empty string is not authority |
| All entries present, verified, and covering the selector | review proceeds normally |

⛔ **The design must never synthesise, paraphrase, or infer rule text.** If the Owner has not
declared where a rule's normative text lives, its entry stays **absent** and C14 keeps returning
`BLOCKED`. That is the **correct** result — not a failure to be worked around, and not a reason to
add a test switch or a fallback default.

---

## 3. Insertion points (exact, measured)

```text
control-plane/c13-c14-lite/lite_cli.py
    : 52     DEFAULT_APPLICABLE_RULES = ("GO_CONSTITUTION", "PERMISSION_BOUNDARY", "AI_BEHAVIOUR_RULES")
    :138-142 _env_spec()      -> load + verify the snapshot, derive per-rule version/sha256
    :166-167 _facts() C14     -> add rule text (this is what reaches the prompt)
    :285-286 cmd_seal() C14   -> bind the snapshot digest into the sealed record
    :329-336 cmd_scope()      -> add rule_snapshot_sha256 to the frozen scope payload

control-plane/c13-c14-lite/lite_ai_reviewer.py
    :143-144 build_prompt()   -> NO CHANGE NEEDED (facts are dumped verbatim)

.github/workflows/c14-rule-compliance.yml
    step "Freeze the rule-review scope digest"  -> one added --rule-snapshot argument
    workflow_dispatch inputs                    -> UNCHANGED (already at the 10-input ceiling)
```

C13's workflow declares no `applicable_rules` input and has no rule-review step, so **nothing here
applies to C13.**

---

## 4. What is explicitly NOT proposed

```text
NOT a new rule service / registry / daemon
NOT a new dispatch input            (impossible: already at 10/10)
NOT a new credential or permission scope (contents: read already suffices)
NOT a new schema file beyond one snapshot JSON
NOT a change to the reviewer or its prompt template
NOT any authored rule text, and NOT any mapping of an existing document onto these three names
NOT a change to C13/C14's gate semantics, the ledger, or the sealed-record shape beyond §2.4
```

---

## 5. Owner decisions required to unblock (only the Owner can supply authority)

```text
A1  For each of the three names, which current artifact is its normative home?
      - docs/governance/CHANGE_CONTROL_POLICY.md        (nearest existing candidate for AI behaviour)
      - application/governance/workbench/cell_charters/ (established pattern; no C13/C14 charter yet)
      - application/src/go_hotel/autonomy/definitions.py (C14 capability/truth declaration only)
      - or: none of these exists yet, and the normative text must be authored by the Owner
A2  Or: retire the three names and declare the authoritative rule set that C14 should actually use.
A3  Where should the snapshot live — on the candidate (recommended, §2.2) or on `main`?
A4  Who signs off on a snapshot edit, given the snapshot effectively defines what C14 will accept?
```

⚠ Until A1/A2 are answered, the honest state is: **the snapshot cannot be populated without
inventing rule text**, so C14 will keep returning `BLOCKED` — and that BLOCKED is correct.

---

## 6. Round-3 decision B, recorded

```text
SEAL_REFUSAL_LIVE_DRILL = NO

Rationale (accepted): PR #254's dedicated offline regression covers the refusal path, and Round 3
already proved in a real run that (a) a model-authored BLOCKED seals legally, (b) the raw review
artifact publishes normally, and (c) the D-4 core path is closed. A green run is not the same as
having covered the refusal path, so the item is not upgraded to live-verified.

Standing rule from here on:
  - keep "raw evidence survives a refused seal" as a NATURAL-FAILURE verification item
  - do NOT add a test switch, do NOT deliberately corrupt input, do NOT spend an extra production
    run just to turn this item green
  - it is NOT an independent blocker for C13

Consequence for the record: the runbook's honesty caveat stays as written (success path), and no
future C13 dispatch may be gated on this item.
```
