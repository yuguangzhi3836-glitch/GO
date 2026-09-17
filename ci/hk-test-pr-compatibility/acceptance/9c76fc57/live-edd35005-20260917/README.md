# Issue 184 — DONE_SCOPED: shared recovery and fresh PR183 TEST_PR

The accepted shared repair PR185 (`9c76fc579383fa2270af90bc67b67a17454d37bd`)
was installed on HK using only its exact `test_pr.py` and `transport.py` bytes.
The source repair had already passed independent C14 then C13; their immutable
records are in the parent archive, commit `1137db08a386e4675a578d00aba4d24053f27de0`.
These live installation and acceptance checks were performed by the primary agent;
they are not represented as additional independent reviews or native GitHub approvals.

Installation backed up both files, checked their known pre-hashes, syntax checked
the approved replacement, briefly paused only the idle agent timer, atomically
replaced both files, checked imports and post-hashes, and restored the timer.
Backup: `/var/backups/HK-CHANGE-20260917T113255Z-issue184`.
Protected files and business-container identities were identical before and after
this installation. The live CC projector does not load the repository failure
schema; its existing failure reader already preserves the new bounded codes.
No CC code, config, identity, Task, ledger or historical Evidence was changed.

The trusted offline uvicorn[standard] dependency probe passed in frozen image
`sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132`.
There was no dependency installation or builder-image change.

## Fresh formal execution

- Request: [go-control-tasks PR52](https://github.com/chenzhenxi1-sudo/go-control-tasks/pull/52),
  head `fafd8ad09aab60145cac623dbb117693ab628ebc`; one Request file, no merge.
- Task: `go-boss-test-pr-183-3a7ec32c646d`, normal Bridge commit
  `d60a2df9860ee8f7c0ae950bd9fca2c45ffa2d6a`; fresh nonce and one attempt.
- Product: unchanged PR183 `edd3500575d2f2b81298cc9273025e0a3b734897`.
- [Original signed Evidence](https://github.com/chenzhenxi1-sudo/go-control-evidence/blob/bce4d64cddef7eed8143e6f65156cc7b73e8a352/evidence/go-boss-test-pr-183-3a7ec32c646d-sZz4iTNGE6hA9XZDrsgEQYqw1JF-bq-U.json):
  `SUCCESS / TEST_PR_OK`, four gates PASS, artifact durability PROVEN.
- Exact original Evidence bytes, with no added final LF:
  SHA256 `ddb645db875fc5f8fc460317055a7476fea98803f2487e21890529f6ea79f5e5`.
- Sealed package: `93f6812337e491d9144d6fb44a52764e9fa82313d2bb08a6373a613e4cdf30bf`,
  115702784 bytes. Read-only host resolution verified its SHA256, trusted owner,
  0600 mode and OCI archive image identity. No docker load was performed.
- Image: `sha256:8f8beb568209393fd74660c226ca7b14b2efe171caf5521645ec6fe4cea56119`.
- CC projection: COMPLETE / PROVEN, both signatures verified, matching Evidence
  digest and exact product source. Host processed ledger: completed, original
  attempt table retains its single claimed row (not rewritten by this repair).

`check_acceptance.py` verifies original Git blob identities, pinned Ed25519
identities, Request/Task/Evidence bindings, artifact identity and receipts.
`SHA256SUMS` covers all sibling archive files except itself. Raw Task and Evidence
files retain their original bytes; derived JSON receipts are clearly named.

## Scope and history

The previous failed Task remains consumed and was not replayed. Its original
exception was absent from signed Evidence, the read-only ledger and bounded
journal. That historical observation gap is explicitly retained; no particular
historical first exception is invented. The installed old source hashes matched
the deterministic profile mismatch, and fresh post-fix execution now succeeds.

The entire work period cannot be called runtime-unchanged. After this TEST_PR,
a separate signed rollback Task completed at 11:57:26Z, followed by additional
control-bus activity. Later container IDs/images differ from installation time.
The separate rollback's Task and Evidence signatures were verified and archived
for reconciliation; this session neither submitted nor executed that rollback.
This archive proves PR183's isolated build acceptance, not that PR183 is running.

PR183 and PR185 remain Draft/open/unmerged. No passed Cell was rerun, product code
edited, real supplier connected, live migration run or business DEPLOY requested
by this repair session. PR183 deployment remains subject to Issue103's exact
candidate admission, recorded DB0133-to-candidate0137 migration requirements and
formal downstream gates. Real supplier certification, Final Release and
Production remain HOLD. This scope does not claim application health or release
approval.
