# PR183 migration admission evidence for Issue103

Change classes: TEST_ONLY, CONTROL_PLANE (read-only admission evidence), MIGRATION
(isolated rehearsal only), DOCUMENTATION.

PR183 remains immutable at `edd3500575d2f2b81298cc9273025e0a3b734897` and has a
successful signed HK TEST_PR from Issue184. It targets Alembic
`0137_hosted_unknown_episode`; HK's latest verified collector baseline is
`0133_flight_change_plan`. Describing this candidate as `migration_required=false`
would be incorrect. `CANDIDATE_PROPOSAL.json` binds the real source, build,
artifact and original signed TEST_PR, and declares migration required. It is a
proposal only and does not replace a canonical or host-owned candidate pointer.

This focused workflow supplies the previously missing PostgreSQL 18.4 forward
migration rehearsal. It checks three immutable checkouts separately: tooling
PR SHA, exact PR183 product SHA, and the canonical DEPTH48 runtime source.
The application tree and complete file fingerprint must match accepted PR183.
Every historical migration must be byte-identical to the deployed source lineage.
A stdlib AST walk requires a single target head and a complete, acyclic graph;
the two 0135 branches and their 0136 merge are both included.

Only a fresh loopback CI database named `go_issue103_isolated` is accepted. The
workflow builds its 0133 baseline, seeds a business flight-plan record, captures
all existing business-table row hashes, upgrades to the exact 0137 target, and
checks old data, status width, new tables, both valid trigram indexes and an
already-at-target no-op. It never stamps or downgrades. Concurrent index creation
can commit separately; this rehearsal does not claim atomic rollback or authorize
blind retries after a live partial failure. Separate supplier-controls storage
remains an explicit activation prerequisite, not a table silently created by this
business migration chain.

The workflow installs only inherited, checksum-verified frozen wheels. It runs no
previously accepted Cell suite and never touches HK, RDS, provider connections,
host configuration, signing material, deploy plans or Production. Its file paths
do not trigger existing application/Cell workflows.

PASS_SCOPED means this exact candidate's isolated migration rehearsal passed.
It does not mean DEPLOY_READY. As observed during this reconciliation:

- CC's host-owned CANARY binding still names the old `6b92050e...` candidate;
- this candidate adds the reviewed migration-capable contract, but it is source
  only and is not installed: the plan requires an exact source/tree/fingerprint,
  exact prestate and target, the complete Alembic graph digest and this PG18.4
  rehearsal's Evidence digest;
- the agent and executor revalidate that closed schema, accept no SQL/command/path,
  require one candidate Alembic head with the exact rehearsed graph digest, verify
  `0133_flight_change_plan` before upgrade and `0137_hosted_unknown_episode` after;
- candidate admission and downstream CANARY/VERIFY/DEPLOY remain HOLD until this
  Draft passes independent review and a separately authorised installation binds
  the admitted candidate. This PR grants no live authority.

The plan must continue to be derived by Command Center. This work introduces no
manual plan, approval record, caller-controlled revision/SQL/command or new
deployment-authority path. PR183, PR185 and this evidence PR remain Draft and
unmerged. Real supplier certification, Final Release and Production remain HOLD.

CI artifacts contain source fingerprints, migration identities, baseline data
hashes, original migration logs, EVIDENCE.json and a self-excluding SHA256SUMS.
