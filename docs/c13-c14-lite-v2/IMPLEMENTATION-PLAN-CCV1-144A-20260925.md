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
RESULT = WITNESS_GITHUB_READBACK_READY
```

The round opened as `BLOCKED_CREDENTIAL_PERMISSION`, because neither host held a
credential whose repository selection included the repository, and GitHub exposes no API
to create or re-scope one. The two credentials were then created by the account owner and
installed, and the block is gone:

```text
CC_GITHUB_API_CREDENTIAL_READY = YES      HK_GITHUB_API_CREDENTIAL_READY = YES
CC_RUN_METADATA_READ           = YES      HK_RUN_METADATA_READ           = YES
CC_ARTIFACT_METADATA_VERIFIED  = YES      HK_ARTIFACT_METADATA_VERIFIED  = YES
METADATA_WITNESS_READY         = YES      BYTE_LEVEL_WITNESS_READY       = YES
OWNER_ACTION_REQUIRED          = NO       blocked                        = []
CCV1_145_FULL_CHAIN_SIMULATION = READY
```

Both hosts read the same run and the same artifact **independently**, agreed on the
digest, and re-hashed the downloaded bytes to that same digest. What follows documents
how each part was established, including two real defects this round found and fixed.

### The two credentials are distinct

```text
cc  /etc/go-command-center/keys/github-witness-reader.token   root:root                0600  93 B  sha256:bcead04ba2b607cbecdf475881b2eddb
hk  /etc/go-hk-agent/keys/github-witness-reader.token         go-hk-agent:go-hk-agent  0600  93 B  sha256:7f11873b443120d1f7a843590002bd3a
```

Different tokens, so one can be rotated or revoked without touching the other, and
GitHub's per-token `Last used` identifies which host is reading. The fingerprints are
irreversible digests, not the values. Both hosts produced the same artifact digest
(`sha256:6202a664…b256fc`) from their own credential.

### Both hosts, measured in place

| | CC (`iZj6c7k6k01biwlbnwutu5Z`) | HK (`iZj6ccs8t04f1p4d8pe69zZ`) |
|---|---|---|
| `GET /user` | 200 | 200 |
| `GET /repos/yuguangzhi3836-glitch/GO` | 200 | 200 |
| `GET /actions/runs/36110672586` | 200 | 200 |
| `GET /actions/runs/…/artifacts` | 200 | 200 |
| artifact metadata verified | YES | YES |
| bytes available / hashed / verified | YES / YES / YES | YES / YES / YES |
| `refusals` | `[]` | `[]` |
| recomputed sha256 | `sha256:6202a664…b256fc` (4285 B) | identical |

Neither host's result substitutes for the other's: each ran its own readback with its own
credential on its own machine.

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

## 4. On-host readiness, before installation (the opening diagnosis)

This section records what the hosts looked like **before** the credentials existed. Both
were probed in place with a script piped over stdin to `python3 -B -`, so nothing was
written to either host and no service was touched.

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

Two credentials, one per host, created by the credential owner in the GitHub web UI
(no API exists for it) and pasted **in the owner's own terminal**, never through chat,
never in `argv`, never in shell history, never in a log:

```text
cc  /etc/go-command-center/keys/github-witness-reader.token   root:root                0600
hk  /etc/go-hk-agent/keys/github-witness-reader.token         go-hk-agent:go-hk-agent  0600
```

The pre-existing `github-requests-reader.token` on CC was **not touched** — it belongs to
another surface and still has GO outside its repository selection.

Installing the workstation's `gho_…` OAuth token instead was considered and rejected:

- it authenticates as `gho_…`, an OAuth token with **write** access to the repository;
- the task requires a read-only credential with isolated purpose
  (`CREDENTIAL_PURPOSE = "… GitHub Actions readback only"`), and a token that can push
  is not that;
- copying a personal OAuth token onto two servers is credential sprawl, and it would
  make the witness layer's independence depend on Eason's personal session.

### Two defects found and fixed while doing it

**1. The interactive prompt could echo the pasted token.** `read -s` disables echo only
for the duration of the read, so bytes reaching the terminal before the read begins are
already echoed by the line discipline and can persist in scrollback. Fixed by disabling
echo with `stty -echo` **before** the prompt is printed, with a trap to restore it on
`EXIT/INT/TERM`. Testing this properly also required replacing a `script(1)`-based test,
which wrote the input before echo was disabled and therefore measured the harness rather
than the script, with a Python pty driver that waits for the prompt before typing.

**2. The installer accepted a corrupted value.** The first real install on CC stored a
value with a stray `ESC` (0x1b) in front of it — `PREFIX_CLASS = other: b'\x1bgit'` — and
GitHub answered **`401 Bad credentials`**, a message that blames the credential and gives
no hint that the paste was at fault, with nothing visible in the terminal. The installer
had rejected whitespace but not control characters. Now it unwraps bracketed-paste markers,
keeps only the credential alphabet `[A-Za-z0-9_]`, **reports how many characters it
removed**, refuses a value without a known prefix or shorter than 20 characters, reads the
file back to confirm it round-trips, and (with `--verify`, on by default) checks the value
against real GitHub at install time, mapping the result to
`PASS` / `FAIL_CREDENTIAL_REJECTED` / `FAIL_REPOSITORY_OUT_OF_SCOPE` / `SKIPPED_NETWORK`
with a non-zero exit on failure. That check would have caught the ESC byte immediately.

Worth stating plainly: on a `401 Bad credentials`, suspect a paste artefact before
suspecting the credential.

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

## 8. The witness chain driven by real metadata

The C13/C14 *content* is still synthetic (there is no real C13/C14 execution), but the
GitHub facts are the real ones. Both are labelled, so the seam cannot be misread:

```text
REAL_GITHUB_METADATA      = YES
SYNTHETIC_ACCEPTANCE_DATA = YES
  real run          36110672586 completed success
  real run head     cec9646d28d0d11175c739cd88ef9a817961da4f
  real workflow     .github/workflows/c13-c14-lite-poc.yml
  real artifact     10853505252  c13c14-lite-c14-ffffffffffffffffffffffffffffffffffffffff
  real digest       sha256:6202a6647d36083bde6d407b54e69fc19a91e0376370d15374f6ce3694b256fc
  bytes verified    True
```

Feeding that through `FirstSeenLedger`:

```text
observe(real metadata + synthetic roots)          -> FIRST_SEEN
observe(identical again)                          -> UNCHANGED
observe(same identity, rewritten c14_root)        -> CONFLICT
observe(same identity, rewritten artifact digest) -> CONFLICT
```

The ledger key is the execution identity, so a rewritten root or digest under the same
identity is a conflict rather than a new entry — which is the property that makes
"first seen" mean anything.

The round verdict, computed from the measured on-host probes rather than written by
hand:

```text
BEFORE INSTALL   RESULT = BLOCKED_CREDENTIAL_PERMISSION
                 blocked: cc -> credential_repository_scope
                          hk -> no_github_api_credential_on_host
AFTER INSTALL    RESULT = WITNESS_GITHUB_READBACK_READY
                 METADATA_WITNESS_READY = true
                 BYTE_LEVEL_WITNESS_READY = true  (from both hosts, not the workstation)
                 CCV1_145_FULL_CHAIN_SIMULATION = READY
                 blocked = []
```

`BYTE_LEVEL_WITNESS_READY = true` here means the *mechanism* works end to end; it does
not mean the two hosts can do it yet. The verdict's per-host booleans are the ones that
matter for the next round, and they are false.

## 9. Required action — completed (see the companion document)

`GITHUB-WITNESS-CREDENTIAL-OWNER-ACTION-20260925.md` states exactly what to create, for
whom, and with which permissions — including the list of permissions that must **not**
be granted. It is deliberately specific enough to be followed without interpretation.

## 10. Boundaries

```text
NO HSM, KMS, WIF, Registration Authority, new ECS, third-party service
NO C13/C14 redesign, no parallel scheduler, no new cell or task registry
NO production deploy, no service restart, no database mutation
NO HK executor modification, no owner PR touched, no historical fact rewritten
NO secret in Git, logs, issues, artifacts or any handoff text
```

What this round actually touched on the two hosts:

| Action | CC | HK |
|---|---|---|
| read-only probe (before install) | yes | yes |
| `/root/go-witness-credential-install.sh` placed, 0700 root:root | yes | yes |
| one credential installed at 0600 | yes | yes |
| readback run in `/tmp` from a staged, stdlib-only toolset | yes | yes |
| service restarted / unit touched | **no** | **no** |
| any other credential touched | **no** | **no** |
| key directory permissions changed | **no** | **no** |

The credential values were handled only by the installer (reading stdin) and by the
readback tool (reading the file in-process on the host). Neither value appears in any
document, commit, artifact, log or message; the only thing recorded about them is an
irreversible fingerprint and a length. `/root/go-witness-credential-install.sh` contains
no secret and may be removed once rotation is no longer expected.

Also cleaned up: the staged `/tmp/ccv1-144a-tools` directory and the `/tmp` readback
records on both hosts, and the WSL sandbox used for install-script testing. What is left
behind on purpose: the two credentials, and (optionally) the installer.

`CC_WITNESS_KEY_INSTALLED = NO` and `HK_WITNESS_KEY_INSTALLED = NO` are unchanged — the
witness **signing** keys are a separate, still-unauthorised step, and this round only
granted the *read* capability.
