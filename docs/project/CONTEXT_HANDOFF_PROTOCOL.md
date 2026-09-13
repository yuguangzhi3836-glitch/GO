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

1. Resolve current `main` SHA.
2. Read previous checkpoint.
3. Enumerate merged/current changes since previous checkpoint.
4. Classify impact by module.
5. Update only state files whose effective truth changed.
6. Review `ACTIVE_DECISIONS.md` for new/superseded decisions.
7. Record unresolved candidate PRs separately; do not import them as current facts.
8. Set the new checkpoint SHA/date.
9. Human review the compressed result.

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

- What is current GO?
- What is actually running?
- What is merely a candidate?
- What are the current active decisions?
- What is unknown or blocked?
- Which recent changes occurred after the last checkpoint?
- Which source/runbook must be read before touching a specific area?

CONTEXT_HANDOFF_PROTOCOL_STATUS=V1_CANDIDATE
