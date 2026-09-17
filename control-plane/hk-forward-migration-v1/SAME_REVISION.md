# Same-revision candidate support

The existing v1 contract remains a forward-migration-only contract. Its format,
rehearsal checks, migration execution and uncertainty fence are unchanged.

The v2 contract (`go.hk-candidate-contract.v2`) describes an explicitly
non-migrating candidate. It is stored in the same content-addressed root-owned
stores and referenced by the same signed Task digest field. It has the common
schema/environment/profile/candidate/current-image/revision fields, replaces
`rehearsal` and `rehearsal_sha256` with:

- `migration_required`: exactly JSON `false`;
- `migration_source_digest` and `baseline_migration_source_digest`: identical
  SHA256 of the complete source graph and Alembic Python/config files;
- `test_pr_evidence_sha256`: canonical digest of the original signed TEST_PR.

Both revisions must be exactly equal. The current image and candidate image are
each checked in isolated, no-network/read-only containers against the same graph
identity. The fixed source-only program does not import the application, connect
to a database or contain a migration command. The current live Alembic revision
is read and checked before cutover; the existing full post-deploy VERIFY checks
the candidate revision. The same-revision executor never loads the migration
execution module. An unresolved previous migration still blocks cutover.

The plan's migration field is false, derived from the validated contract. Package,
source, current-image, candidate-image, signed TEST_PR, signed CANARY and fresh
VERIFY remain required. Caller schemas, signing authority, immutable plans,
root-owned admission, replay protection and the fixed eight-service scope are
unchanged. Contract-bound rollback remains refused; this change makes no new
rollback compatibility claim.

Ordinary VERIFY can use a root-owned baseline version 2, adding only
`candidate_contract_sha256`. That contract must describe the **currently running
image**, not the candidate awaiting deployment. This permits the existing
workspace/revision-aware collector to verify current post-migration images.
Version 1 baselines retain their original legacy semantics.

This source package does not install itself, register a candidate, modify any
authority, publish a Request, or prove a deployment. Controlled installation must
preserve all accepted installed source, revalidate the exact before/after hashes
and module pins, and keep the existing v1 contracts. Candidate facts must be
derived from verified source/artifact/TEST_PR and both image graphs. They are not
deployment plans or approvals. The subsequent formal chain remains CANARY,
fresh VERIFY, authenticated DEPLOY Request, and independent post-deploy VERIFY.

Validation:

```
python -m unittest discover -s control-plane/hk-forward-migration-v1/tests -v
python -m unittest discover -s control-plane/boss-deploy-request-v1/tests -v
```

The tests include real temporary signatures but mocked Docker/database
boundaries. They are not a live installation, live database or load-test result.
