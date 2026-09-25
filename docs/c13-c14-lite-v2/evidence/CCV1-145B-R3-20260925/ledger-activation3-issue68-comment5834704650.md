## C13 / C14 GATE RE-ACTIVATION — round `V70-R3`, third activation — 2026-09-25

Append-only record, written by the implementation / scheduler identity (`chenzhenxi1-sudo`)
under the standing rule this ledger carries on the two armed rows. It modifies no body text and
no historical comment, and it does **not** delete or rewrite the two previous activations
(comments `5833230504` and `5834220848`).

> C13 · independent acceptance · `TRIGGER_ARMED` · *Activate only on a new frozen candidate*
> C14 · source/authority gate · `TRIGGER_ARMED` · *Activate only on a new frozen candidate, before C13*

### Why a third activation, and why neither previous C14 result is reused

- Activation **#1** (candidate `7db7b2aa5…`, `V70-R3-C14-01` / `V70-R3-C13-01`) produced
  `PASS_SCOPED` run `36141430817`. **Not reused**: its frozen changed-path boundary was **empty**,
  proved from its own sealed record — `rule_review_scope_sha256 = 843bed61…` equals the digest over
  an empty path list and not the digest over the two paths the candidate actually changed. The
  verdict was a review of nothing.
- Activation **#2** (candidate `3cd7be75…`, `V70-R3-C14-02` / `V70-R3-C13-02`) produced run
  `36148838395`, which returned `BLOCKED` and then **failed at the seal**, leaving **no artifact at
  all**. **Not reused**, and there is nothing to reuse: no sealed record exists for that activation.
  The run did confirm, in the runner's own environment dump, that D-1 and D-2 were fixed
  (`LITE_SCOPE_SHA256` `843bed61…` → `1356d60f…`; `LITE_WORKFLOW_SHA` `8889221c…` → `0ffea233…`).
- The reason that run could not be sealed is defect **D-4**: the seal demanded a `failure_class`
  from every `FAIL`/`BLOCKED`, while only the provider-failure path can produce one and the opinion
  schema lets the model return those verdicts itself. A model-authored `BLOCKED` was therefore
  unsealable, and because the opinion had not yet been published the reviewer's reasoning was
  destroyed with the run. Fixed in **PR #254** (merged).

⇒ Neither prior activation is closed on evidence. Both stand as historical records; this
activation starts a fresh one against the machinery that now includes the D-4 fix.

### New frozen candidate

- candidate SHA: `64715d308954049eb6675d81196d7f4cd853199b` (current `main`)
- application tree: `dd815baf0105cce603e9a28b002cfb9d8b95d186`
- root tree: `d6b4e801d792ef7448fd1808632abe41170cd86b`
- commit subject: `Merge pull request #254 from yuguangzhi3836-glitch/cc/c13-c14-workflow-defect-fixes-20260925`
- committed at: `2026-09-25T23:07:13+08:00`
- this is merge #3 for the C13/C14 line: `PR254_MERGE_SHA = 64715d30…`
  (merge #1 `7db7b2aa…` = PR #252 registration; merge #2 `3cd7be75…` = PR #253 D-1/D-2 fix)
- the pinned execution ref both workflows now carry is
  `48c2386d2dfc4d2e1e8c914dc7c7376af6bd1eb4`

### Round / task identity minted by this activation

- ledger round id: `V70-R3` — unchanged. This is the **third** activation inside the round,
  following the same sequence field the ledger already uses for repeated activations of one cell
  (e.g. C01 appears as `V70-R3-C01-01` and later `V70-R3-C01-03`).
- C14 task id: `V70-R3-C14-03`
- C13 task id: `V70-R3-C13-03`
- scheduler request id: `V70-R3-C13C14-03`
- ledger issue: **#68**
- order: **C14 first**; C13 is dispatched only if C14 reaches `PASS_SCOPED` or a lawful
  `NOT_APPLICABLE`. C13 has still never been dispatched.

### What this record does and does not assert

- It moves the two armed rows onto a new assigned activation for the candidate above.
- It is **not** a verdict: no C13/C14 result exists yet for this SHA.
- It claims no execution, no ACK/start, no liveness, no release authority.
- `FINAL_RELEASE = HOLD` · `HK_DEPLOY = HOLD` · `PRODUCTION = HOLD` are unchanged.
- C01–C12 rows are untouched and no previously passed work is reopened or rerun.

### One fact worth recording again

The candidate's `application/` subtree, `dd815baf0105cce603e9a28b002cfb9d8b95d186`, is **again**
byte-identical to the tree this ledger already carries for `37d9a420…` / `8ffcde66…` /
`7db7b2aa5…` / `3cd7be75…`. The change in `64715d30…` relative to its first parent is entirely
**outside** `application/` (the two workflow files). The point of this activation is not the
application layer — it is to obtain the first verdict produced by machinery that carries all of
D-1, D-2, D-3 and D-4.
