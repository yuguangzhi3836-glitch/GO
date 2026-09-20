# PR #227 registration and nationwide hotel-library release gap matrix

- Candidate base: `af1c2d5744aef5212eb139f93b150ec7ae171b38`
- Scope: C registration, B nationwide hotel-library onboarding, and their shared terms/identity boundary.
- Status: **DRAFT / NOT RELEASE-READY**.
- Prohibited actions: no TEST_PR request, CANARY, DEPLOY, Production activation, real PSP, or real supplier connection was requested or performed by this change.

## Completed inside the repository

| Control | Evidence in this candidate |
|---|---|
| Version/hash-bound agreement reading and consent audit | Existing registry, reader APIs, C/B readers, and admission tests |
| Consumer/supplier isolation and draft-only hotel creation | Existing integration tests |
| Nationwide geographic inputs | Existing supplier/onboarding tests |
| Terms drafts cannot enable signup | Existing admission tests |
| No accidental registration opening before verified delivery | New `registration_verification_enabled=False` default, API release-gate disclosure, and `REGISTRATION_VERIFICATION_NOT_READY` server rejection |
| Synthetic tests are not production approval | Test helper marks synthetic verification state explicitly; shipped registry remains DRAFT |

## Release blockers that cannot be completed only in this repository

1. **Verification service:** implement and configure a real phone-or-email verification delivery provider; prove send, receive, expiry, replay rejection, retry/rate-limit, and audit evidence in the isolated target environment. Do not set `registration_verification_enabled=true` merely to bypass this gate.
2. **Legal/operating facts:** final approval of the seven texts, retention/recipient/cross-border facts, actual mailbox handling, and approval evidence. Current bundle remains DRAFT.
3. **Official candidate execution:** create the official signed HK_STAGING_TEST_PR for the exact final candidate head; retain signed task, signed evidence, artifact/build identity, migration result, and JUnit/SHA-256 manifest.
4. **Exact-page acceptance:** the running Staging pages currently serve old forms. On the exact TEST_PR candidate, verify readable full texts, C login, B login, tenant/property isolation, nationwide city creation, draft-only publication, and C/B/mobile journeys.
5. **Post-TEST_PR release chain:** only after all preceding gates pass, follow the separately authorized CANARY -> VERIFY -> DEPLOY -> post-deploy VERIFY process. This document neither requests nor performs that chain.

## Required acceptance record

For each row record: exact candidate SHA, UTC time, isolated environment identity, tester identity, action/result, sanitized evidence reference, and SHA-256 manifest. A browser screenshot alone is insufficient; no real credentials or verification codes belong in Git.

## Deterministic stop rule

Any missing evidence, old page asset, failed verification receipt, tenant boundary failure, or non-DRAFT initial property state is a release blocker. Keep the PR Draft and the runtime registration gate closed.
