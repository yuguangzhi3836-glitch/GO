## C13 / C14 GATE ACTIVATION — round `V70-R3` — 2026-09-25

Append-only activation record. It is written by the implementation / scheduler
identity (`chenzhenxi1-sudo`) under the standing rule this ledger already carries
on the two armed rows, and it modifies no body text and no historical comment.

> C13 · independent acceptance · `TRIGGER_ARMED` · *Activate only on a new frozen candidate*
> C14 · source/authority gate · `TRIGGER_ARMED` · *Activate only on a new frozen candidate, before C13*

### New frozen candidate

- candidate SHA: `7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5` (current `main`)
- application tree: `dd815baf0105cce603e9a28b002cfb9d8b95d186`
- root tree: `85ab281cfc10375081fe36c96482cf108c56280b`
- commit subject: `Merge pull request #252 from yuguangzhi3836-glitch/cc/c13-c14-production-workflow-registration-20260925`
- committed at: `2026-09-25T21:22:26+08:00`

### Round / task identity minted by this activation

- ledger round id: `V70-R3` — unchanged; this activation stays inside the round already
  recorded here, and follows the same `V70-R3-C<NN>-<SS>` grammar as the C01–C12 rows
- C14 task id: `V70-R3-C14-01`
- C13 task id: `V70-R3-C13-01`
- scheduler request id: `V70-R3-C13C14-01`
- ledger issue: **#68**
- order: **C14 first**; C13 is dispatched only if C14 reaches `PASS_SCOPED` or a lawful `NOT_APPLICABLE`

### What this record does and does not assert

- It moves the two armed rows onto an assigned activation for the candidate above. It is
  **not** a verdict: no C13/C14 result exists yet for this SHA.
- It claims no execution, no ACK/start, no liveness and no release authority.
- `FINAL_RELEASE = HOLD` · `HK_DEPLOY = HOLD` · `PRODUCTION = HOLD` are unchanged.
- C01–C12 rows are untouched and no previously passed work is reopened or rerun.

### One fact worth recording before the verdict arrives

The candidate's `application/` subtree, `dd815baf0105cce603e9a28b002cfb9d8b95d186`, is
**byte-identical** to the application tree this ledger already carries for the earlier
candidate `37d9a420…`. The change surface of `7db7b2aa…` relative to its first parent is
therefore **outside** `application/` (the PR #252 registration commit adds two workflow
files, `+528 / -0`, and nothing else).

Consequence, stated explicitly so the result cannot be over-read either way: the C14 / C13
review of this candidate is a review of a **new frozen commit** whose application layer is
unchanged. Historical `PASS_SCOPED` is **not** transferred to this SHA; the gates are run
again for this candidate, as the standing rule requires.
