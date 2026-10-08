> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](../../README.md) · AI（英文）[`AGENTS.md`](../../AGENTS.md)。
> Current entry points: [`README.md`](../../README.md) (Chinese, humans) and [`AGENTS.md`](../../AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# GO MODULE STATE

This directory contains compact **current-state cards** for major GO modules.

Current baseline for all cards: canonical `main@8ffcde66d36c1bbf849218529ef015f6e81725af` (refreshed 2026-09-14). Each card states its own baseline; if a card's baseline is older than the checkpoint in [`docs/project/CONTEXT_CHECKPOINT.json`](../project/CONTEXT_CHECKPOINT.json), treat the card as stale and refresh it.

These files are not historical changelogs. Their purpose is to answer a fresh-session question quickly:

> What is true now, what is only a candidate, and what is still unknown/blocked?

## Rules

Each module state should separate:

- `CURRENT MAIN FACTS`
- `ACTIVE CANDIDATES`
- `UNKNOWN / HOLD / BLOCKERS`
- `EVIDENCE / ENTRYPOINTS`

Do not promote an open PR into current truth.

Do not paste full historical PR chronology here.

A card refresh is a documentation change. It must not modify application source, CI bindings, migrations, evidence or runtime state, and it must not restate a repository identity as a live runtime identity (or vice versa).

Older PRs remain audit evidence and should be consulted only when a current fact needs provenance or when investigating a conflict.

## Initial module cards

- `HOTEL.md`
- `PAYMENT.md`
- `CONTROL_PLANE.md`
- `PRODUCT_VERTICALS.md`

Additional cards should be created only when a module has enough independent state to justify its own startup context.
