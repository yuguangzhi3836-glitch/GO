# GO CONTEXT HANDOFF PROTOCOL

## Goal

A fresh ChatGPT, Codex, WorkBuddy or human reviewer must be able to understand the current GO project without replaying hundreds of historical pull requests or depending on prior chat memory.

## Startup sequence

Read in this order:

1. `README.md`
2. `docs/project/OPERATING_CONTEXT.md`
3. `docs/project/GO_CURRENT_STATE.md`
4. `docs/project/ACTIVE_DECISIONS.md`
5. the relevant file(s) under `docs/state/`
6. `docs/project/CONTEXT_CHECKPOINT.json`
7. inspect repository changes after the checkpoint only, unless a specific historical question requires older evidence.

For HK runtime work, also read the current runtime pointer/runbook required by `AGENTS.md`.

Note the division of labour between these entrypoints: `OPERATING_CONTEXT.md` answers *who does what* and carries the live-runtime quick reference; `GO_CURRENT_STATE.md` answers *what is true now* for both repository source and live runtime; `ACTIVE_DECISIONS.md` answers *what has been decided*; `docs/state/*` answers *what is true for one module*; the checkpoint answers *what not to re-read*.

## Core rule

`sync GO` does **not** mean `read PR #1 through the latest PR`.

It means:

- load the current-state snapshot;
- load currently active decisions;
- load the relevant module state;
- compare current main against the checkpoint;
- inspect only the delta since that checkpoint;
- update the snapshot only after review.

## Context truth classes

Every important statement should be treated as one of:

- `CURRENT_MAIN_FACT` — supported by accepted/current main or current canonical runtime evidence.
- `ACTIVE_DECISION` — currently effective human/project decision.
- `ACTIVE_CANDIDATE` — open PR/branch/proposal; not canonical yet.
- `HISTORICAL` — superseded/archive/evidence for audit.
- `UNKNOWN` — insufficient evidence.
- `HOLD` — explicitly not effective/authorized.

AI must not silently promote `ACTIVE_CANDIDATE`, `HISTORICAL`, `UNKNOWN` or `HOLD` into `CURRENT_MAIN_FACT`.

## Checkpoint rule

A context checkpoint means:

> all accepted project truth up to `checkpoint_main_sha` has been compressed into the current-state layer, subject to the limitations recorded in the checkpoint.

**`checkpoint_main_sha` always names canonical `main`.** It never names the branch head or merge commit of the context PR that wrote it. The context PR is an `ACTIVE_CANDIDATE` until it is merged; its own commits are not project truth.

Two further bindings are mandatory:

- the checkpoint must also carry the verified `main:application` tree, file count, source fingerprint and the **repository** migration head at that SHA;
- the **live** database revision and the live runtime generation are recorded separately, because they are not the same object as the repository head.

After a checkpoint is reviewed and accepted, historical PRs before it are normally consulted only for:

- provenance/audit;
- conflict investigation;
- rollback/lineage questions;
- explicit user request;
- evidence missing from the current-state layer.

## When to create a new checkpoint

Create/update a checkpoint when one or more occur:

- roughly 10–20 materially relevant PRs since the last checkpoint;
- a major module reaches a new accepted baseline;
- runtime generation changes;
- a major business decision set changes;
- context files are becoming materially stale;
- before archiving/moving to a substantially new project phase.

PR count is a trigger for review, not proof that all PRs are relevant.

## Checkpoint update process

1. Fetch and resolve the **actual current** canonical `main` SHA. Never assume a previously quoted SHA is still current.
2. Read the previous checkpoint.
3. Enumerate merged/current changes since previous checkpoint.
4. Recompute `main:application` tree hash, file count and source fingerprint from the repository.
5. Recompute the Alembic head from source; separately restate the confirmed live database revision.
6. Re-read release/gate fields from the canonical CI manifests, not from PR prose.
7. Classify impact by module.
8. Update only state files whose effective truth changed.
9. Review `ACTIVE_DECISIONS.md` for new/superseded decisions.
10. Record unresolved candidate PRs separately; do not import them as current facts.
11. Set the new checkpoint SHA/date and the refresh timestamp.
12. Human review the compressed result.

## Context refresh boundary

A context refresh is a **documentation/governance** change. It may:

- refresh current facts to a newer canonical `main`;
- append decisions and mark supersession;
- rebind the checkpoint;
- correct internally inconsistent current-state wording.

It may **not**:

- modify application business source, tests, CI bindings, migrations, evidence or packaging;
- rewrite the runtime pointer, or claim the runtime pointer was refreshed because the context layer was;
- execute a migration, deploy, cut over a runtime or touch Production;
- resolve an open PR, or promote an open PR's internal claims into current truth;
- delete or rewrite previous decision history.

## Decision-change rule

When a new human decision conflicts with an earlier one:

- never erase the old decision;
- mark replacement relationship;
- determine whether existing orders/data/runtime are affected or only future behavior;
- perform impact analysis before implementation;
- update current-state wording only after the new decision becomes effective.

## Candidate PR rule

An open PR can be mentioned in a module state file under `Active candidates`, but it cannot change the `Current accepted state` section until accepted into the relevant baseline.

This rule specifically prevents an unconstrained AI agent from changing project reality merely by generating many PRs.

## Size rule

State files are summaries, not archives.

Prefer:

- current effective facts;
- important unknowns/holds;
- active candidate links;
- pointers to deeper evidence.

Avoid copying full PR bodies, code diffs, long chat transcripts or historical chronology into startup context.

## New-session expected output

After following this protocol, a new AI should be able to answer:

- What is the current canonical `main`?
- Where is the current business source, and what is its tree identity?
- What is the current **repository** migration head, and what is the **live** database revision?
- How does the live HK runtime relate to repository source right now?
- What are the Control Plane and the Business Runtime, and why must they not be inferred from one another?
- Which statements are `CURRENT_MAIN_FACT`?
- Which newer PRs are only `ACTIVE_CANDIDATE`, and what exactly does that forbid?
- Is Final Release / HK deploy / Production authorized right now?
- Which recent changes occurred after the last checkpoint?
- Where should genuinely new work be started from, instead of re-reading PR #1 onward?
- Which source/runbook must be read before touching a specific area?

If any of these cannot be answered from the entrypoints alone, the current-state layer is incomplete and must be corrected — not worked around by reading more PRs.

CONTEXT_HANDOFF_PROTOCOL_STATUS=REFRESHED_AT_MAIN_8ffcde66
