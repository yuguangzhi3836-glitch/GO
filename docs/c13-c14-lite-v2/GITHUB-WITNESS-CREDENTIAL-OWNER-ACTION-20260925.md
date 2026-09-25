# Required action — GitHub witness credential for CC and HK

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

The credential must be pasted **on the host**, not sent through chat, not committed,
and not written to a file on the workstation. The installer reads it from stdin, so the
value never appears in `argv`, in shell history or in a log:

```sh
# On GO Command Center (as root)
sudo sh /path/to/control-plane/c13-c14-witness/install-github-witness-credential.sh \
    --host cc --apply
# paste the token, then press Ctrl-D
```

```sh
# On HK-STAGING-01 (as root)
sudo sh /path/to/control-plane/c13-c14-witness/install-github-witness-credential.sh \
    --host hk --apply
# paste the token, then press Ctrl-D
```

Without `--apply` it prints the plan and changes nothing. The script installs exactly
one file, at exactly this custody, and refuses to finish if the result is not exactly
that:

```text
cc  /etc/go-command-center/keys/github-witness-reader.token   root:root        0600
hk  /etc/go-hk-agent/keys/github-witness-reader.token         go-hk-agent:go-hk-agent  0600
```

It does not touch the key directory's permissions, does not restart any service and
does not modify any other credential. The pre-existing
`github-requests-reader.token` on CC is left completely alone: it belongs to another
surface.

Use the **same** token value on both hosts. It is read-only and scoped to one
repository, and using one token keeps the two witnesses' *read* capability identical —
their witness *signing* keys stay separate, which is what independence actually rests
on here.

## 3. Prove it works

Run the witness readback on each host. This is the pass condition for the four
booleans:

```sh
cd <repo>/control-plane/c13-c14-witness
python3 lw_readback.py --host cc --role c14 \
  --candidate-sha ffffffffffffffffffffffffffffffffffffffff \
  --expected-head-sha cec9646d28d0d11175c739cd88ef9a817961da4f \
  --workflow-path .github/workflows/c13-c14-lite-poc.yml \
  --run-id 36110672586 --probe --out /tmp/cc-readback.json
```

```sh
cd <repo>/control-plane/c13-c14-witness
python3 lw_readback.py --host hk --role c14 \
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
