# Published verifier identities — CC V1-01

> Scope: **`CONTROL_STATE_AND_STATUS_ONLY`**. This directory publishes **public
> key material only**. It is a verification aid, never Execution Authority.

This is the formal, auditable publication target for the two verifier identities
the Control Plane depends on. Before CC V1-01 the repository archived *fingerprints
only* (`command-center/audit/20260911/KEY_FINGERPRINTS.txt`,
`hk-staging/audit/20260911/KEY_FINGERPRINTS.txt`), so any projection off the
control bus was capped at `OBSERVED`: a reader could not check a signature, and
therefore could not tell a real Task from a forged one.

## The two identities

| | Task | Evidence |
|---|---|---|
| `identity_id` | `GO-CC-TASK-MANIFEST-SIGNER` | `HK-AGENT-EVIDENCE-SIGNER` |
| Role | signs the Task Manifest | signs the Evidence |
| Held by | Command Center | Hong Kong agent |
| Signature encoding | `hex` | `base64` |
| Algorithm | Ed25519 | Ed25519 |
| SSH SHA256 | `SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns` | `SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw` |
| Published key | `keys/cc-task-manifest-signing.pub` | `keys/hk-evidence-signing.pub` |
| Host source | `/etc/go-command-center/keys/task-manifest-signing.pub` | `/etc/go-hk-agent/keys/evidence-signing.pub` |

The two fingerprints differ, which is the separation requirement: **one key may
never serve both roles.**

## Why the binding is trustworthy

The published keys are not self-asserted. Each one is anchored on both sides:

```text
Task identity
  Command Center  /etc/go-command-center/keys/task-manifest-signing.pub
  Command Center  /etc/go-command-center/deployment-plans-v1/authority.pub   IDENTICAL_KEY
  Hong Kong       /etc/go-hk-agent/keys/task-verify.pub                      IDENTICAL_KEY (archived 2026-09-11)

Evidence identity
  Command Center  /etc/go-command-center/deployment-plans-v1/hk-evidence.pub  IDENTICAL_KEY
  Hong Kong       /etc/go-hk-agent/keys/evidence-signing.pub                  IDENTICAL_KEY (archived 2026-09-11)
```

The signer and the verifier therefore provably hold the same identity: the key the
Command Center signs Tasks with is the key the Hong Kong agent checks them with.

## How these files were obtained

Read-only, once, on demand, with an explicit human go-ahead for the operation:

```text
host      i-j6c7k6k01biwlbnwutu5  (hostname iZj6c7k6k01biwlbnwutu5Z)
method    read-only file read over the Alibaba Cloud Workbench tunnel
retrieved 2026-09-14T14:34:46Z
files     /etc/go-command-center/keys/task-manifest-signing.pub                        (81 B)
          /etc/go-command-center/deployment-plans-v1/authority.pub                     (81 B)
          /etc/go-command-center/deployment-plans-v1/hk-evidence.pub                   (81 B)
```

No write, no service restart, no signing, no deployment, no private key read. Only
the three `*.pub` paths above were read; `/etc/go-command-center/keys/` was never
enumerated for content and no `.pem` and no `*token*` file was touched.

Every retrieved byte was verified twice — once on the host with `sha256sum` and
`ssh-keygen -lf`, once locally by recomputing both fingerprint forms from the raw
bytes — and both agreed with the fingerprints already archived in this repository.

```text
cc-task-manifest-signing.pub   file sha256  7329ad0eff6c38973b0aa5c7481ae9e61d8383dd98f790940c8970eceaaad42c
                               ssh  fp     SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns
hk-evidence-signing.pub        file sha256  3800e9a87b2fe47c2ccdb18209ac35bec0cfe5cc7a1c1ad3927573fe848d7ae3
                               ssh  fp     SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw
```

## What a reader must do with them

```sh
python control-plane/command-center-state-v1/state_projection.py \
  --tasks-repo <go-control-tasks> --evidence-repo <go-control-evidence> \
  --task-verify-key     control-plane/command-center-state-v1/identity/keys/cc-task-manifest-signing.pub \
  --evidence-verify-key control-plane/command-center-state-v1/identity/keys/hk-evidence-signing.pub \
  --verifier-identities control-plane/command-center-state-v1/identity/VERIFIER_IDENTITIES_V1.json \
  --now <ISO8601> --out <dir>
```

`--verifier-identities` defaults to this contract, so the two keys above are the
only keys the projector will accept as those identities.

## The five outcomes the projector must distinguish

```text
correct key              fingerprint matches the contract      BOUND              PROVEN possible
wrong key                fingerprint does not match            IDENTITY_MISMATCH  FAIL_CLOSED
crossed identity         task key offered for the evidence role IDENTITY_MISMATCH FAIL_CLOSED
same key for both roles  both roles resolve to one key         IDENTITY_COLLISION FAIL_CLOSED
no key supplied          nothing to check                      MISSING_KEY        NEVER PROVEN
contract unreadable      the pin cannot be loaded              IDENTITY_UNRESOLVED FAIL_CLOSED
```

A key that is merely *present* is never treated as *correct*. Supplying an
unrecognised key is worse than supplying none: it is reported as an explicit
mismatch rather than degrading quietly to `OBSERVED`.

## What is never published

```text
private keys            NEVER   no .pem, no PKCS#8, no seed, no scalar
tokens and credentials  NEVER   no GitHub token, no deploy key, no password
runtime .env values     NEVER   not in this directory, not in any projection
```

A test asserts that no private key material appears anywhere in this directory.
The exported projection additionally runs a whole-output scan for host paths, so a
published key can never smuggle a workstation path into the derived state.

## Rotation

An identity is never replaced in place. A rotation adds a new entry with a new
`identity_id` and a new fingerprint, marks the old one `SUPERSEDED`, and keeps the
old fingerprint published for as long as Evidence signed under it still exists.
`CURRENT_ROTATION=NONE` at CC V1-01.

## Boundary

```text
SIGNS_ANYTHING              NO
CREATES_OR_PUBLISHES_TASKS  NO
EXECUTES                    NO
REACHES_HONG_KONG           NO
EXECUTION_AUTHORITY         NO
```
