# CCV1-144A — GitHub witness credential enablement

- Task: `CCV1-144A-GITHUB-WITNESS-CREDENTIAL-ENABLEMENT`
- Branch: `cc/ccv1-144a-github-witness-credential-20260925`, **stacked on**
  `cc/ccv1-144-cc-hk-witness-20260925` (PR #249), which is itself stacked on PR #248.
  The stack is deliberate: this round's readback tool consumes the witness layer, and
  this PR's diff is only credential plumbing, templates, docs and tests.
- Inputs: PR #247 (design / fact baseline — not merged, not evidence), PR #248
  (GitHub execution backend), PR #249 (CC/HK witness layer — implemented, not
  installed). A synthetic lifecycle is never a real C13/C14 PASS.

## Result

```text
RESULT = BLOCKED_CREDENTIAL_PERMISSION
```

Everything that does not require a new GitHub credential is done and proven. The one
remaining item is a **repository grant that only a human can make**, because GitHub
exposes no API to create or re-scope a credential (evidence below).

## 1. CC's existing credential: why it 404s

`/etc/go-command-center/keys/github-requests-reader.token` — fine-grained PAT
(`github_pat_11CGTTNFQ…`), 93 bytes, `0600`, `root:root`.

| Read | HTTP |
|---|---|
| `GET /user` | **200** — authenticates as `chenzhenxi1-sudo` |
| `GET /repos/yuguangzhi3836-glitch/GO` | **404** |
| `GET /repos/.../actions/permissions` | 404 |
| `GET /repos/.../actions/runs/36110672586` | 404 |
| `GET /repos/.../actions/runs/.../artifacts` | 404 |
| `GET /repos/.../actions/artifacts/10853200109` | 404 |
| `GET /user/repos` | **200, exactly 1 repository: `chenzhenxi1-sudo/go-control-tasks`** |

So the 404 is **not** a missing `Actions` permission. A fine-grained PAT has to name
the repositories it applies to, and this one was created for the control-tasks bus.
`yuguangzhi3836-glitch/GO` is outside its selection, and GitHub answers 404 rather than
403 for a repository a credential cannot see.

`x-oauth-scopes` is empty on every response, which is expected: that header describes
classic scopes and fine-grained PATs do not have them.

## 2. HK's existing credential: there is none

`/etc/go-hk-agent/keys/` contains six files, all SSH keys or Ed25519 signing keys:

```text
evidence-signing.pem       Ed25519 PKCS8      (deployment evidence signing)
evidence-signing.pub
evidence-write             SSH private key
github-go-source-reader    SSH private key    (git clone only — NOT an API token)
github-go-source-reader.pub
tasks-read                 SSH private key
task-verify.pub
```

No GitHub REST credential. `github-go-source-reader` is an SSH clone key and cannot
call the API; treating it as one would be a category error.

## 3. The artifact-bytes misdiagnosis, and the fix

Both PR #248 and CCV1-144 recorded that the storage endpoint "refuses the credential".
That was wrong, and the experiment that showed it is worth keeping:

| Step | Result |
|---|---|
| `urlopen(zip_url)` with `Authorization` (the original code, and the POC workflow) | **401**, body `<Error><Code>InvalidAuthenticationInfo</Code>` — the error comes from **Azure Blob Storage**, not from GitHub |
| `GET zip_url` with redirects disabled | **302**, `Location` host category = `storage-endpoint`, query contains `sig=` |
| `GET <signed URL>` with **no** `Authorization` header | **200**, 4285 bytes, `PK` magic, sha256 = `6202a6647d36083bde6d407b54e69fc19a91e0376370d15374f6ce3694b256fc` |
| GitHub's recorded `artifact.digest` | `sha256:6202a6647d36083bde6d407b54e69fc19a91e0376370d15374f6ce3694b256fc` |

Two conclusions:

1. **The bytes are retrievable.** The single-step `urlopen` was forwarding the GitHub
   token to Azure, which then tried to interpret it as an Azure credential.
2. **`artifact.digest` is the sha256 of the artifact zip blob.** This is now measured,
   not assumed, so the comparison is exact rather than "probably the same semantics".

`lite_artifact_fetch.py` implements the two-step fetch and refuses to send
`Authorization` to the redirect target. `test_lw_artifact_fetch` contains a
**counter-test** that performs the naive one-step download against a local server which
mimics Azure's behaviour, and asserts it fails with 401 — so if this code is ever
"simplified" back, the suite goes red with the reason.

### The four artifact states

Collapsing these into one `ARTIFACT_VERIFIED` is how "we could not download it"
becomes "verified". They are kept separate everywhere.

```text
ARTIFACT_METADATA_VERIFIED   the API's own metadata agrees with the claim
ARTIFACT_BYTES_AVAILABLE     the zip was actually received
ARTIFACT_BYTES_HASHED        a digest was computed over those bytes
ARTIFACT_BYTES_VERIFIED      that digest equals the claimed one
```

Measured on the real POC run `36110672586` from the workstation:

```text
ARTIFACT_METADATA_VERIFIED = YES
ARTIFACT_BYTES_AVAILABLE   = YES
ARTIFACT_BYTES_HASHED      = YES
ARTIFACT_BYTES_VERIFIED    = YES
redirect host category     = storage-endpoint
refusals                   = []
```

That run used the **workstation's** credential, and the record says so
(`executed_from.host_class = workstation`). It proves the transport and the
verification path. It is **not** evidence that CC or HK can do it, and this round
does not claim otherwise.

## 4. On-host readiness, measured

Both hosts were probed in place with a script piped over stdin to `python3 -B -`, so
nothing was written to either host and no service was touched.

| Host | Credential | `user` | `repository` | `run` | Blocked by |
|---|---|---|---|---|---|
| CC (`iZj6c7k6k01biwlbnwutu5Z`) | existing PAT | 200 | 404 | 404 | `credential_repository_scope` |
| HK (`iZj6ccs8t04f1p4d8pe69zZ`) | none | — | — | — | `no_github_api_credential_on_host` |

Network transport **is** available from both hosts, which is why the only missing piece
is the grant:

| Endpoint | CC | HK |
|---|---|---|
| `https://api.github.com` | 200 | 200 |
| `https://productionresultssa0.blob.core.windows.net` | 400 (TLS OK — the endpoint's own answer to a bare GET) | 400 (TLS OK) |
| `https://objects.githubusercontent.com` | 404 (TLS OK) | 404 (TLS OK) |

## 5. Why this cannot be automated

An agent cannot create or re-scope the credential, and this is now evidence rather than
an assumption:

```text
GET  /user/tokens          -> 404   (no such API)
GET  /user/pats            -> 404   (no such API)
POST /user/tokens          -> 404   (no such API)
GET  /user/authorizations  -> 404   (the classic OAuth-token surface is gone)
GET  /user/installations   -> 403   (requires a GitHub App token)
```

Fine-grained PAT creation and repository selection are **web-UI-only**. There is no
route that an execution agent can take, short of using someone's browser session, which
would be impersonation and is out of the question.

Note also that the credential in question belongs to `chenzhenxi1-sudo` — so the action
below is taken by the **token's owner**, not by a third party.

## 6. What was installed this round

**Nothing.** No credential exists yet to install, and installing the workstation's
OAuth token instead was considered and rejected:

- it authenticates as `gho_…`, an OAuth token with **write** access to the repository;
- the task requires a read-only credential with isolated purpose
  (`CREDENTIAL_PURPOSE = "… GitHub Actions readback only"`), and a token that can push
  is not that;
- copying a personal OAuth token onto two servers is credential sprawl, and it would
  make the witness layer's independence depend on Eason's personal session.

So the four pass booleans stay false, honestly, and `OWNER_ACTION_REQUIRED = YES`.

## 7. What is ready, and verified

```text
control-plane/c13-c14-lite/
  lite_artifact_fetch.py        two-step fetch; classifies every failure; never logs the signed URL
  lite_readback.py              now uses it, and records the four byte states

control-plane/c13-c14-witness/
  lw_credential.py              purpose, minimal scope, forbidden scopes, custody, redaction, install plan
  lw_readback.py                the readback a witness host runs, plus the five-endpoint capability probe
  lw_readiness.py               folds per-host probes into the round verdict (machine-checked)
  lw_secret_scan.py             SECRET_LEAK_SCAN
  install-github-witness-credential.sh   reads the credential from stdin only; refuses empty/whitespace/multiline
  templates/github-witness-reader.token.example
```

Verification, all local:

| Check | Result |
|---|---|
| witness suite | **136 tests, OK** |
| backend suite (#248) | **93 tests, OK** |
| payload/secret scan | see `SECRET_LEAK_SCAN` in the round report |
| install script | end-to-end in a WSL sandbox: every refusal path fires, `--dry-run` writes nothing, `--apply` yields `0600 root:root`, value byte-identical to stdin, no leftovers |
| real GitHub readback | run `36110672586`, all four states YES, digest equal |
| schemas / workflow checks | `stale=[]`, `PASS` |

### A time bomb found and fixed on the way

The backend suite was **red before this round touched it** — 3 failures and 53 errors,
identically on PR #248's head and PR #249's head. Cause: `lite_fixtures.NOW` was a
frozen `2026-09-25T08:00:00Z`, and contracts carry `expires_at = now + 55min`, so once
wall-clock passed 08:55 UTC every fixture correctly refused with
`candidate_request_expired`. The tests were asserting against a constant instead of
against the artifact under test.

Fixed properly rather than re-dated:

- fixture builders resolve `now` at **call time**;
- the two expiry tests derive their "one second too late" instant from the **contract's
  own `expires_at`**, so they cannot rot again;
- the subprocess workflow test computes its dispatch timestamps relative to now;
- a new test builds a contract and validates it with no explicit `now`, so a frozen
  default cannot silently return.

Had this not been fixed, every subsequent round would have started red for a reason
unrelated to its own work.

## 8. Required action (see the companion document)

`GITHUB-WITNESS-CREDENTIAL-OWNER-ACTION-20260925.md` states exactly what to create, for
whom, and with which permissions — including the list of permissions that must **not**
be granted. It is deliberately specific enough to be followed without interpretation.

## 9. Boundaries

```text
NO HSM, KMS, WIF, Registration Authority, new ECS, third-party service
NO C13/C14 redesign, no parallel scheduler, no new cell or task registry
NO production deploy, no service restart, no database mutation
NO HK executor modification, no owner PR touched, no historical fact rewritten
NO secret in Git, logs, issues, artifacts or any handoff text
```

Touches this round: CC read-only probe; HK read-only probe; one WSL sandbox for the
install-script test (cleaned up). No file was created on CC or HK. No key was
generated, installed or copied. Subject to the one grant above, nothing is left that
this round is permitted to automate.
