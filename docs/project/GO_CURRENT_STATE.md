# GO CURRENT STATE

> Purpose: canonical human-readable project-state snapshot for new ChatGPT, Codex, WorkBuddy and human handoffs.
>
> This file is **descriptive context, not Execution Authority**. Runtime and deployment authority still comes from current live state, Human Approval, Signed Task, installed artifact, durable previous-state and Signed Evidence where applicable.
>
> New sessions should read this file instead of reconstructing GO by replaying historical pull requests.

## 1. What GO is right now

GO is a multi-domain travel product under active development. The repository contains hotel, flight, rail, ride, rental, attraction, mobile, payment/funds, Command Center, Control Plane, deployment and operational evidence work.

The project is not considered globally complete or production-ready merely because code exists for a capability.

## 2. Current canonical source / runtime facts

- Business application source: `application/`
- Active HK-STAGING business runtime generation: `DEPTH48`
- Runtime definition: `deploy/hk-staging/`
- Current machine-readable runtime pointer: `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`
- Control Plane is a separate axis from the business runtime.
- `deliverables/` and `evidence/` are historical evidence bound to their original commit/scope; they are not current product authority by default.
- Production remains a separately governed scope; no historical PR number alone grants production authority.

## 3. Human / AI responsibility model

- Boss / 余总: product owner and final business-direction decision maker.
- Boss GPT: product exploration/development agent; its branches and PRs are candidates, not automatically canonical.
- Eason / 陈震曦: integration, review, execution coordination and human technical-operations owner.
- Eason's ChatGPT: context, review, task-decomposition and coordination layer; not product owner or deployment authority.
- Codex / WorkBuddy: execution agents under Eason's control.

## 4. Current important project lines

### Hotel / core booking

Hotel booking code currently includes offer/prebook/order/payment/confirmation/after-sales flows, but real production hotel inventory authority and supplier concurrency behavior are not proven by repository code alone.

Do not equate model fields, mocks or simulated connector capabilities with real supplier capability.

### Payment Center

Active discovery PR: `#61` (`payment-center/reality-discovery-01`).

Current direction is **technical reality discovery before new Payment Center implementation**.

Known high-level facts from current main/discovery work:

- current HOTEL native payment flow and newer omnichannel payment/money models coexist;
- real external WeChat Pay / Alipay / card acquiring execution is not yet proven by repository code;
- hotel inventory authority / last-room concurrency remains unproven;
- Payment Center must not introduce a second independent money truth by default;
- live-money authority remains locked unless separately approved.

### Control Plane / Command Center

Control Plane and Business Runtime are separate axes. Current Control Plane procedures must be read from the current runbooks, not reconstructed from old chats or historical shell commands.

### HK-STAGING

HK-STAGING currently runs the DEPTH48 business runtime. For live/runtime questions, use `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` and `deploy/hk-staging/README.md` rather than historical PR numbering.

## 5. What is explicitly NOT safe to infer

Do not infer any of the following from PR count, PR number, DEPTH number, file count or presence of a model/table:

- that a feature is production-ready;
- that a provider integration is real rather than simulated;
- that an AI-generated design is an approved business decision;
- that a newer PR supersedes a reviewed baseline;
- that a mock capability equals supplier/PSP capability;
- that historical evidence describes current runtime;
- that a merged feature automatically has deployment authority.

## 6. Context-compaction rule

GO project continuity must not depend on replaying all historical pull requests.

A new session should normally read, in order:

1. `README.md`
2. `docs/project/OPERATING_CONTEXT.md`
3. `docs/project/GO_CURRENT_STATE.md`
4. `docs/project/ACTIVE_DECISIONS.md`
5. the relevant module state file under `docs/state/`
6. `docs/project/CONTEXT_CHECKPOINT.json`
7. only changes after the recorded checkpoint, unless older history is specifically needed for audit or dispute resolution.

Historical PRs remain evidence. They are not mandatory context once their effective state has been compressed into the current-state layer.

## 7. Updating this file

Update this snapshot only when a reviewed change materially changes current project truth.

Do not copy every PR summary into this file. Keep it short enough for a fresh AI session to load without consuming the majority of its working context.

When a decision changes, preserve history in the decision register and update only the currently-effective statement here.

GO_CURRENT_STATE_STATUS=V1_CANDIDATE
