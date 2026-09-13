## Change summary

Describe the intended change and why it is needed.

## Change class

Check every applicable class:

- [ ] PRODUCT_FEATURE
- [ ] PRODUCT_FIX
- [ ] BUILD
- [ ] TOPOLOGY
- [ ] CONTROL_PLANE
- [ ] INFRASTRUCTURE
- [ ] MIGRATION
- [ ] TEST_ONLY
- [ ] DOCUMENTATION

## Source / baseline

- Base branch:
- Base SHA:
- Canonical source root or affected area:
- Candidate/source SHA(s), when applicable:

## Runtime impact

- Runtime mutation required: YES / NO
- HK-STAGING affected: YES / NO
- Production affected: YES / NO
- Database/schema migration required: YES / NO
- Protected services (`redis`, `caddy`) affected: YES / NO

## Deployment topology

- Current topology identity/version:
- Candidate topology identity/version:
- Service roles added/removed/renamed:
- Image families added/removed:
- `TOPOLOGY_CHANGE_REQUIRED`: YES / NO

If topology changes, link the new topology contract and follow `docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`. A normal DEPLOY must not infer or apply topology expansion.

## Validation

List tests, CI runs, source/tree hashes, artifacts, or other evidence actually checked. Do not claim PASS from a workflow that merely collected failing evidence.

## Rollout / rollback

Describe any required rollout, approval, VERIFY, rollback, or external gate. A PR does not itself authorize any runtime operation.

## Security / authority

- [ ] No private keys, signing keys, passwords, tokens, `.env` values, cookies/sessions, or database dumps are included.
- [ ] No caller-controlled expansion of deployment scope is introduced.
- [ ] This change does not treat GitHub, chat history, or AI memory as Execution Authority.
- [ ] Normal work was performed on a branch; `main` was not written directly.

## Merge / execution status

- MERGE_AUTHORIZED: NO unless explicitly approved by the responsible human
- DEPLOYMENT_EXECUTED: NO unless separately authorized and evidenced
- MIGRATION_EXECUTED: NO unless separately authorized and evidenced
- PRODUCTION_ACTION: NO unless separately authorized and evidenced
