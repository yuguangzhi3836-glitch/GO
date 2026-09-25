## C13 / C14 GATE RE-ACTIVATION — round `V70-R3`, second activation — 2026-09-25

Append-only record, written by the implementation / scheduler identity (`chenzhenxi1-sudo`)
under the standing rule this ledger carries on the two armed rows. It modifies no body text
and no historical comment, and it does **not** delete or rewrite the previous activation
(comment `5833230504`).

> C13 · independent acceptance · `TRIGGER_ARMED` · *Activate only on a new frozen candidate*
> C14 · source/authority gate · `TRIGGER_ARMED` · *Activate only on a new frozen candidate, before C13*

### Why a second activation, and why the previous C14 result is NOT reused

The first real C14 run (`36141430817`) returned `PASS_SCOPED`, but it is **not reused** here and
must not be:

- its frozen changed-path boundary was **empty**, so the rule review reviewed a **review of
  nothing**. That is proved from its own sealed record: `rule_review_scope_sha256 = 843bed61…`
  equals the digest over an empty path list, and does not equal the digest over the two files
  the candidate actually changed.
- the defect is fixed in **PR #253** (`D1_FIXED` / `D2_FIXED` / `D3_FIXED`), and the fix is now
  registered on the default branch. The verification machinery that produced the old verdict is
  therefore no longer the machinery that would produce a new one.

⇒ the previous activation (`V70-R3-C14-01` / `V70-R3-C13-01`, candidate `7db7b2aa5`) stands as a
historical record of a run whose scope was empty. It is closed, not carried forward.

### New frozen candidate

- candidate SHA: `3cd7be752330f377e3446942da4f881df13d183d` (current `main`)
- application tree: `dd815baf0105cce603e9a28b002cfb9d8b95d186`
- root tree: `b71ad60a25e3de6888125183163085b8f54252d9`
- commit subject: `Merge pull request #253 from yuguangzhi3836-glitch/cc/c13-c14-workflow-defect-fixes-20260925`
- committed at: `2026-09-25T22:34:18+08:00`
- this is merge #2 for the C13/C14 line: `REGISTRATION_MERGE_SHA_2 = 3cd7be75…`
  (merge #1 was `7db7b2aa…`, PR #252)

### Round / task identity minted by this activation

- ledger round id: `V70-R3` — unchanged. This is the **second** activation inside the round,
  following the same sequence field the ledger already uses for repeated activations of one cell
  (e.g. C01 appears as `V70-R3-C01-01` and later `V70-R3-C01-03`).
- C14 task id: `V70-R3-C14-02`
- C13 task id: `V70-R3-C13-02`
- scheduler request id: `V70-R3-C13C14-02`
- ledger issue: **#68**
- order: **C14 first**; C13 is dispatched only if C14 reaches `PASS_SCOPED` or a lawful `NOT_APPLICABLE`

### What this record does and does not assert

- It moves the two armed rows onto a new assigned activation for the candidate above.
- It is **not** a verdict: no C13/C14 result exists yet for this SHA.
- It claims no execution, no ACK/start, no liveness, no release authority.
- `FINAL_RELEASE = HOLD` · `HK_DEPLOY = HOLD` · `PRODUCTION = HOLD` are unchanged.
- C01–C12 rows are untouched and no previously passed work is reopened or rerun.

### One fact worth recording again

The candidate's `application/` subtree, `dd815baf0105cce603e9a28b002cfb9d8b95d186`, is again
**byte-identical** to the tree this ledger already carries for `37d9a420…` / `8ffcde66…` /
`7db7b2aa5…`. The change in `3cd7be75…` relative to its first parent is entirely **outside**
`application/` (the two workflow files). The point of this activation is not the application
layer — it is to obtain the first verdict produced by the **fixed** verification machinery.
