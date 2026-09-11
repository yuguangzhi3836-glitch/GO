# Boss TEST_PR V1 candidate

This directory is a **candidate artifact**, not an update to the archived
Command Center or HK-STAGING runtime snapshots.  It is deliberately kept out
of `command-center/source/` and `hk-staging/source/`: those directories record
the bytes observed on 2026-09-11 and must remain historically accurate.

## Scope

`HK_STAGING_TEST_PR` is an isolated, non-deployment test action.  Its chain is:

```
Boss Request (untrusted PR number)
  -> Command Center resolves refs/pull/<N>/head once
  -> exact 40-character commit SHA in a signed Task
  -> HK fetches that SHA with its own read-only Deploy Key
  -> fixed offline builder + isolated container checks
  -> Signed Evidence
```

The mutable PR ref is used only by Command Center during resolution.  The
formal Task, source fetch, image build, test result, and Evidence all use the
immutable commit SHA.  A PR number never becomes a Git checkout argument on
HK.

## Deliberate safety boundaries

- The only permitted source repository is
  `git@github.com:yuguangzhi3836-glitch/GO.git`.
- The Request permits only a PR number.  It cannot supply a repository, ref,
  commit, build command, Dockerfile, environment, volume, network, or service
  list.
- HK's source-reader key is a distinct, root-owned, read-only deploy key at
  `/etc/go-hk-agent/keys/github-go-source-reader`.  This candidate never uses
  or transfers a Windows/Codex HTTPS credential, cookie, PAT, or credential
  helper.
- The builder Dockerfile and test command are root-owned profile inputs.  The
  build has no network; the test container has no network, no capabilities,
  read-only root filesystem, and no host/runtime volumes.
- This action never calls Compose and never starts, replaces, restarts, or
  inspects the eight HK business services.  `SUCCESS` proves only the stated
  isolated build checks, not application health or deploy readiness.

## Required live installation work (not performed here)

Human operators must separately review, install, hash-pin, and configure the
candidate Command Center bridge, HK agent handler, root-owned builder profile,
public task verification key, evidence signer, and HK read-only Deploy Key.
Adding the public key to GitHub requires human authorization.  Until those
steps and an approved signed Task occur, this code has no execution authority.

## Local verification

Run from this repository root:

```powershell
python -m unittest discover -s control-plane/boss-test-pr-v1/tests -v
```

The tests are simulation-only: they use a fake resolver, signature verifier,
and command runner.  They neither clone GO nor call Docker, GitHub, Command
Center, HK-STAGING, or any credential store.
