# GO MODULE STATE

This directory contains compact **current-state cards** for major GO modules.

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

Older PRs remain audit evidence and should be consulted only when a current fact needs provenance or when investigating a conflict.

## Initial module cards

- `HOTEL.md`
- `PAYMENT.md`
- `CONTROL_PLANE.md`
- `PRODUCT_VERTICALS.md`

Additional cards should be created only when a module has enough independent state to justify its own startup context.
