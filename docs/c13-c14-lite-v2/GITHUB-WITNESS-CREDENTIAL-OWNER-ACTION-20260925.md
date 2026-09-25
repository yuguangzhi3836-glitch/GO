# Required action — GitHub witness credential for CC and HK

> **Status: the installer is deployed to both hosts and now self-verifies against GitHub;
> the readback tool is staged at `/tmp/ccv1-144a-tools`. CC is installed and fully green.
> Only the HK paste remains, and it must be done by the credential owner in their own terminal.**

- Task: `CCV1-144A-GITHUB-WITNESS-CREDENTIAL-ENABLEMENT`
- Status: `OWNER_ACTION_REQUIRED = YES`
- Date: 2026-09-25

This document is the exact action list. It is deliberately specific: the credential
cannot be created by an execution agent, because GitHub exposes no API for it
(`GET/POST /user/tokens` → 404, `GET /user/pats` → 404, `GET /user/authorizations` →
404), so it has to be created in the web UI.

Note on who acts: this is a **personal credential of `chenzhenxi1-sudo`**, created and
owned by that account. It is not an Owner-administered resource, and no
administrative permission is involved or requested.

## 1. Create the credential

GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained
tokens** → *Generate new token*.

Fill in exactly this, and nothing more:

```text
Token name        : go-c13c14-witness-reader-v1
Expiration        : choose per your rotation policy (this is a read-only token)

Repository access : Only select repositories  ->  yuguangzhi3836-glitch/GO
                    (do NOT choose "All repositories"; do NOT add any other repo)

Permissions:
  Repository permissions
    Actions       : Read-only
    Contents      : Read-only
    Metadata      : Read-only        (mandatory; GitHub selects it automatically)
```

Everything else stays at **No access**. In particular these must remain untouched:

```text
Administration, Attestations, Codespaces, Commit statuses, Deployments,
Discussions, Environments, Issues, Merge queues, Packages, Pages,
Pull requests, Repository hooks, Secret scanning, Secrets, Security events,
Variables, Workflows, Webhooks, Members, Custom properties
```

That is the whole scope. No `contents: write`, no `issues: write`, no
`pull_requests: write`, no `actions: write`, no `workflows: write`, no `secrets: write`,
no `administration`.

## 2. Install it on each host

The credential must be pasted **on the host**, in **your own terminal**. It must not be
sent through chat, not written to a file on the workstation, and not placed in any
command line (a command line is visible in `ps` and lands in shell history).

The installer has already been placed on both hosts and verified by hash:

```text
/root/go-witness-credential-install.sh   0700 root:root   sha256 390811443902156154c345c61bb532a997f4e6cb8998369061b6f3ad0b0c7719
```

It reads the credential from stdin only, so the value never appears in `argv`, in shell
history or in a log. Run it as your own SSH user (both aliases already log in as `root`,
so `sudo` is not needed):

```sh
ssh go-cc
bash /root/go-witness-credential-install.sh --host cc --apply
# paste the token, then press Enter. Input is NOT echoed.
```

```sh
ssh hk-staging
bash /root/go-witness-credential-install.sh --host hk --apply
# paste the token, then press Enter. Input is NOT echoed.
```

Interactive echo is disabled with `stty -echo` **before** the prompt is printed, and
restored afterwards including on Ctrl-C. `read -s` alone was not enough: it disables
echo only for the duration of the read, so bytes that reach the terminal before the read
begins are already echoed. This was found by driving a real pty and only writing the
value after the prompt had been read back, which is what a human does.

Expected output (the token must not appear anywhere in it):

```text
credential purpose : GO C13/C14 Lite acceptance witness: GitHub Actions readback only
credential scope   : repository yuguangzhi3836-glitch/GO; actions:read contents:read metadata:read
target path        : /etc/go-command-center/keys/github-witness-reader.token
target owner       : root:root
target mode        : 0600
directory perms    : unchanged
services restarted : none
paste the token, then press Enter. Input is NOT echoed:
installed          : /etc/go-command-center/keys/github-witness-reader.token
previous mode      : absent
new mode           : 600
new owner          : root:root
value length       : 93
value round-trips  : YES
token  echoed      : NO
token  committed   : NO
TOKEN_CONTENT_REDACTED=YES
verify  GET /user               : 200
verify  GET /repos/<GO>         : 200
VERIFY             : PASS
```

**`VERIFY : PASS` is the line that matters.** The installer checks the credential against
real GitHub before reporting success, `GET /user` and `GET /repos/yuguangzhi3836-glitch/GO`
must both answer 200, and anything else prints a classified failure and exits non-zero:

```text
FAIL_CREDENTIAL_REJECTED        GitHub answered 401 - the value is wrong or expired
FAIL_REPOSITORY_OUT_OF_SCOPE    /user is 200 but the repository is 404 - the token's
                                repository selection does not include GO
SKIPPED_NETWORK                 the host could not reach api.github.com; re-run or
                                verify separately
```

This check exists because the first real install produced a silent `401`. What happened:
the terminal injected a stray `ESC` byte in front of the pasted value, so the file held
`\x1bgithub_pat_…` and GitHub answered `Bad credentials`. Nothing in the terminal showed
it. The installer now removes bracketed-paste markers and any byte outside the credential
alphabet `[A-Za-z0-9_]`, **reports how many characters it removed**, refuses anything that
is not a known credential shape, and reads the file back to confirm the value round-trips.

If you ever see this line, the value was salvaged rather than stored raw — check it:

```text
note: removed N non-credential character(s) injected by the terminal
```

`--no-verify` skips the GitHub check (used only in offline sandboxes).

Also refused, each without writing anything: an empty value, a value spanning multiple
lines, a value that does not start with a known GitHub credential prefix, and a value
shorter than 20 characters. The script installs exactly one file, at exactly this custody,
and refuses to finish if the result is not exactly that:

```text
cc  /etc/go-command-center/keys/github-witness-reader.token   root:root                0600
hk  /etc/go-hk-agent/keys/github-witness-reader.token         go-hk-agent:go-hk-agent  0600
```

It does not touch the key directory's permissions, does not restart any service and does
not modify any other credential. The pre-existing `github-requests-reader.token` on CC is
left completely alone: it belongs to another surface.

Use one token value per host. Both are read-only and scoped to one repository, so the two
witnesses' *read* capability is identical; their witness *signing* keys stay separate,
which is what independence actually rests on here.

`/root/go-witness-credential-install.sh` may be removed once both installs are done; it
contains no secret.

## 3. Prove it works

The readback tool is staged on both hosts at `/tmp/ccv1-144a-tools` (six files, no
dependencies outside the standard library) so that the check can run **on the host**,
from the host's own credential, rather than from this workstation. Run it on each host:

```sh
cd /tmp && PYTHONDONTWRITEBYTECODE=1 python3 -B \
  /tmp/ccv1-144a-tools/control-plane/c13-c14-witness/lw_readback.py \
  --host cc --role c14 \
  --candidate-sha ffffffffffffffffffffffffffffffffffffffff \
  --expected-head-sha cec9646d28d0d11175c739cd88ef9a817961da4f \
  --workflow-path .github/workflows/c13-c14-lite-poc.yml \
  --run-id 36110672586 --probe --out /tmp/cc-readback.json
```

```sh
cd /tmp && PYTHONDONTWRITEBYTECODE=1 python3 -B \
  /tmp/ccv1-144a-tools/control-plane/c13-c14-witness/lw_readback.py \
  --host hk --role c14 \
  --candidate-sha ffffffffffffffffffffffffffffffffffffffff \
  --expected-head-sha cec9646d28d0d11175c739cd88ef9a817961da4f \
  --workflow-path .github/workflows/c13-c14-lite-poc.yml \
  --run-id 36110672586 --probe --out /tmp/hk-readback.json
```

Expected on both: exit 0, and

```text
artifact_metadata_verified = true
artifact_bytes_available   = true
artifact_bytes_hashed      = true
artifact_bytes_verified    = true
refusals                   = []
```

Those parameters target an existing, harmless POC run of the `POC_ONLY` workflow
(run `36110672586`, artifact `c13c14-lite-c14-ffff…`, digest
`sha256:6202a6647d36083bde6d407b54e69fc19a91e0376370d15374f6ce3694b256fc`), so the
result can be compared against a known-good value. If the artifact has expired by the
time you run it, use any later run of the same workflow and record which one.

⚠ The tool writes its record to `/tmp`, and that record contains only public facts (run
id, artifact id, digest, recomputed sha256) plus a redacted credential summary. It never
prints the credential and never writes the signed download URL.

## 4. What this does and does not unlock

```text
unlocks   CC and HK can each independently read the run and artifact metadata, and
          re-hash the artifact bytes, for a C13/C14 execution
does not  authorise deployment; does not install a witness signing key; does not
          give the reviewer any write scope
```

The witness **signing** keys are a separate, still-unauthorised step
(`CC_WITNESS_KEY_INSTALLED = NO`, `HK_WITNESS_KEY_INSTALLED = NO`).

## 5. If you would rather not create a second credential

The alternative is to widen the existing `github-requests-reader.token` to include
`yuguangzhi3836-glitch/GO` with the same three read permissions. That is functionally
equivalent but couples the witness layer to a credential named for another purpose, so
a separate token is preferred. Either way the scope is the same three read
permissions, and either way the change is made in the web UI.
