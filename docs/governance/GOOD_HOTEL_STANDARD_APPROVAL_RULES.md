# Good Hotel Standard approval: existing Owner requirements

This document records the approval/replay requirements already commissioned by the Owner in [work order #520](https://github.com/yuguangzhi3836-glitch/GO/issues/520), created 2026-10-06, against canonical source `00dcf6007fee0513b9ef6184209782d67cad7c0c`. It does not derive authority from PR #525, its implementation, its tests, or an AI review.

## Source wording

> 复现 approve 对SUPERSEDED版本仍可激活和ACTIVE重复审批自我supersede。废止版本不得借旧审批复活；同一已生效批准重放不增加激活/废止事件，不改变有效时间；DRAFT经独立审批者正常生效，maker-checker保留。不得调整一年有效期/到期前30天重评业务规则，不重做 #509。

## Review scope

Apply these requirements to the Good Hotel Standard approval operation: DRAFT approval by an independent approver, replay of the same ACTIVE approval, and attempted approval of a SUPERSEDED version. Preserve the existing maker-checker boundary, activation/retirement event behavior and effective time as specified above. This source does not define new roles, additional lifecycle transitions, or a replacement annual validity/reassessment policy.

This is a separately reviewable transcription of an existing Owner instruction. Until approved and merged into canonical main, it is a proposal and is not an active C14 authority source. Its inclusion does not declare any candidate compliant, erase a previous BLOCKED verdict, authorize another paid review attempt, or authorize merge/deployment/runtime changes. Existing candidate and review identities remain unchanged.
