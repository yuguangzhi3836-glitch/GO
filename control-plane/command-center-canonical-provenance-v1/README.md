# command-center-canonical-provenance-v1

`CANONICAL_SOURCE_INVARIANT` — the proof that a deployment's bytes belong to canonical `main`.
CCV1-82 CONTRACT SPEC section 7; implemented as CCV1-88 (WP-6).

## What it answers

> Bytes that have not passed CANONICAL_PROVENANCE must not be deployed; and a drift
> discovered after a deployment must be findable by the next Evidence.

One question, in six steps, in this order, stopping at the first failure:

| # | step | refuses with |
|---|---|---|
| 1 | `commit_is_canonical` — the commit is on the ancestor chain of `main` | `E_COMMIT_NOT_CANONICAL` |
| 2 | `application_tree_matches` — the declared tree is that commit's tree at the declared path | `E_TREE_MISMATCH` |
| 3 | `artifact_matches_the_signed_result` — the candidate's artifact is what the signed TEST_PR built | `E_ARTIFACT_MISMATCH` |
| 4 | `installed_identity_is_the_authorized_commit` — the host runs the authorised commit | `E_INSTALL_DRIFT` |
| 5 | `installed_modules_are_the_commit_blobs` — every module's sha256 is the commit's blob | `E_INSTALL_DRIFT` |
| 6 | `disk_blobs_match_the_commit` — a checkout's bytes are the commit's objects | `E_BLOB_DRIFT` |

Steps 5 and 6 compare **every** file and report the complete list. An operator told "one of
your modules is wrong" has to diff the whole tree; one told which module disagrees does not.

A refusal also carries a **condition**, so five stable codes can describe several situations
without any becoming invisible: `UNRESOLVABLE`, `PROVENANCE_BROKEN` (section 7.1 — the bytes
are real, they are just not main's), `DRIFT`, `NOT_THE_AUTHORIZED_COMMIT`.

## The four compositions

Named after what a caller *has*, so a proof cannot be asked for from the wrong inputs:

| phase | used by | steps |
|---|---|---|
| `PRE_DEPLOY` | a candidate about to be deployed | 1, 2, 3 |
| `INSTALL_SOURCE` | an installer about to record a source identity | 1, 2, 5 |
| `POST_DEPLOY` | an installation claiming to run an authorised deployment | 1, 2, 4, 5 |
| `CHECKOUT` | a build or staging step, about its own tree | 1, 6 |

Every verdict carries all six steps. A step outside the composition is `NOT_EVALUATED` with
`not_part_of_this_proof`, never omitted — an omitted step and a passing step look the same to
a reader scanning for gaps. A step an input was *missing* for does not exist: an absent input
raises, because a proof that reports `PASS` with a step it never evaluated is a proof of
nothing.

## How to run it

```
python command-center/go-canonical-provenance candidate \
    --repository <clone> --candidate docs/canonical-baseline/CURRENT_CANDIDATE.json \
    --test-pr-evidence <signed TEST_PR evidence> --out <dir>

python command-center/go-canonical-provenance install-source \
    --repository <clone> --source-commit <40-hex> --source-tree <40-hex> \
    --runtime-dir hk-staging/source/executor/runtime --out <dir>

python command-center/go-canonical-provenance installation \
    --repository <clone> --authorized-commit <40-hex> \
    --installed-identity <evidence block> --modules <install fact> --out <dir>

python command-center/go-canonical-provenance checkout \
    --repository <clone> --commit <40-hex> --file docs/x.json=docs/x.json

python command-center/go-canonical-provenance selftest
```

Exit codes: `0` the verdict matched `--expect`; `3` it did not; `2` the request could not be
answered as asked. `--expect ANY` records a refusal without pretending it did not happen.

## Two boundaries, stated rather than implied

**It never fetches.** The reference is an input: `origin/main` as the clone has it. A stale
clone therefore produces a verdict about a stale commit — and the verdict records which commit
that was, as `canonical_commit`, next to `canonical_ref`. That is the difference between a
proof that is wrong and a proof that is auditable.

**It runs one program.** `git_repository.py` reaches a repository through a closed list of
read-only plumbing subcommands (`ALLOWED_SUBCOMMANDS`) with a closed list of option arguments
(`ALLOWED_FLAGS`). `fetch`, `clone`, `ls-remote`, `push`, `update-ref`, `config` and the rest
raise before a process starts; `--no-replace-objects` is passed to every invocation, because a
replace ref makes one commit answer for another. `run_checks.py` narrows the same surface from
the other side: it permits no program other than git.

The configuration git reads is *not* narrowed. `GIT_CONFIG_NOSYSTEM=1` was tried as hardening
and removed the `core.autocrlf=true` that PortableGit sets in its system config, so the clean
filter stopped running and every CRLF file in the repository was reported as drift. Changing
which configuration is read does not make a proof stricter, it makes it a proof of something
else. The consequence is inherited rather than hidden: a filter is a program, and a repository
whose configuration defines one gets the same footing it already has for `git status`.

## Where it is wired

* **The installer seam (live).** `hk-staging/install/hk_install_facts.py` records a
  `source_commit` and a `source_tree`, and its own header deferred the question of whether
  that commit is on `main` to WP-6. `--canonical-proof` is now required, checked **before the
  first write of any kind**, and bound to the exact commit, tree and module hashes that
  installation is about to record — recomputed from the files themselves. A proof that does
  not hold leaves nothing behind. `verify-canonical-source.sh` produces the proof where the
  repository is; no new key and no new signature are involved.
* **CI (live).** `.github/workflows/command-center-canonical-provenance-v1.yml` runs the
  isolated checks, the built-in checks, the WP-5 installer suite, and the proof **on the real
  repository**: the published candidate, a file that is its blob, a file that is not, and the
  commit the live Hong Kong runtime corresponds to.

**Not wired: the CC pre-deployment gate.** SPEC section 12 orders `T3 CANONICAL_ALIGN` before
the six-step proof becomes enforceable on the live path, because the bytes the live Hong Kong
runtime corresponds to (`9b932745…`) are not on `main` — measured, not assumed. A hard gate
there today would refuse every deployment, which is a policy decision, not a proof. The proof
itself runs today and is reported: `WP6_CC_PRE_DEPLOY_ENFORCEMENT_BLOCKED_BY_T3=YES`.

## What it is not

It deploys nothing, publishes nothing, signs nothing, activates nothing, and holds no key.
`AUTHORITY` says so in the machine-readable form and the contract pins every entry: the only
two true entries are that it may read the repository and the facts it is handed.

## Isolation

`run_checks.py` forbids the network, forbids the runtime credential paths, and permits no
program other than git; git-only subprocess access is the one deviation from the sibling
components' `subprocess = FORBIDDEN`, and it is stated in `summary.json` as `GIT_ONLY`.
