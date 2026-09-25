# CCV1-144B — witness Ed25519 signing keys, generated on each host

- Task: `CCV1-144B` — install a dedicated C13/C14 Lite witness signing key on CC and HK.
  This is a **signing-key installation authorisation, not a deployment authorisation**.
- Branch: `cc/ccv1-144a-github-witness-credential-20260925` (PR #250), continuing from
  CCV1-144A. The keys are the second half of the witness layer: 144A gave CC and HK the
  ability to *read* GitHub facts, this round gives them the ability to *attest* to them.
- Baseline: PR #247 (design / fact baseline — not merged, not evidence), PR #248 (execution
  backend), PR #249 (witness layer).

## Result

```text
CC_WITNESS_KEY_INSTALLED  = YES      HK_WITNESS_KEY_INSTALLED  = YES
CC_WITNESS_SIGN_VERIFY    = PASS     HK_WITNESS_SIGN_VERIFY    = PASS
CC_HK_KEYS_DISTINCT       = YES      EXISTING_KEY_REUSE       = NO
```

Both keys were generated **on their own host** and neither private half has ever existed
anywhere else. 19 checks passed on CC and 20 on HK (HK ran one extra, the cross-host
comparison), with no failing check on either.

## Custody was read off the hosts, not assumed

| | CC | HK |
|---|---|---|
| key directory | `/etc/go-command-center/keys` | `/etc/go-hk-agent/keys` |
| directory mode | `0700 root:root` | `0700 go-hk-agent:go-hk-agent` |
| unit that reads it | `go-boss-request-bridge.service` | `go-hk-agent.service` |
| that unit runs as | `User=root Group=root` | `User=go-hk-agent Group=go-hk-agent` |
| existing signing key | `task-manifest-signing.pem` = `root:root 0600` | `evidence-signing.pem` = `go-hk-agent:go-hk-agent 0600` |
| existing public key | `.pub` = `root:root 0644` | signing `.pub` = `root:go-hk-agent 0640` |
| **witness private** | **`root:root 0600`** | **`go-hk-agent:go-hk-agent 0600`** |
| **witness public** | **`root:root 0644`** | **`root:go-hk-agent 0640`** |

On both hosts the key directory is `0700`, so only the owning account can traverse it at
all — a consumer running as anyone else could not read a key there even if the file were
world-readable. The new files match the signing keys already present rather than
introducing a second convention.

The names follow the existing `<name>.pem` / `<name>.pub` shape. Neither host had a
`c13-c14-*` file, so there was no collision.

## The two keys, as public facts

```text
CC  /etc/go-command-center/keys/c13-c14-witness-ed25519.pem   0600 root:root
    /etc/go-command-center/keys/c13-c14-witness-ed25519.pub   0644 root:root
    purpose      c13c14-acceptance-witness
    key_id       26ca5651b363c463
    fingerprint  sha256:26ca5651b363c4630ec13b7bb31ee8823e6be997e9c131ceee9e5696a9d4ecee
    public       ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGI0LDpo2QdZ7vq6HK29jDwoXItaSjY5R7X1C7rlmgnf

HK  /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pem         0600 go-hk-agent:go-hk-agent
    /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pub         0640 root:go-hk-agent
    purpose      c13c14-acceptance-witness-hk
    key_id       36458250ffc1b404
    fingerprint  sha256:36458250ffc1b404372be0eebef0c2bf6644672d8c5e8b712290b90bdd4cf0ec
    public       ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGwBqFC7x2JDhn9nF8LrwSbcqCrS0MdaX6QinrNyqhaf
```

`key_id` is the first 16 hex of the SHA-256 over the SPKI DER, which is what
`WitnessKey` computes; `fingerprint` is the same digest in the `sha256:` form the project
has used since CCV1-113/134/135. Both were recomputed independently from the on-disk
public key and agreed with the value derived from the private key.

An incidental confirmation that the convention is right: the fingerprint this round
computes for CC's existing `task-manifest-signing.pub` is
`sha256:6b79da6aa4a61f757a9026e14f4fea07e14f30e075afadde9d765b992c1b722c`, identical to
the value recorded in CCV1-142 — the same number, from a different code path, a week later.

## No reuse of any existing key

Every public key on both hosts was compared. All eight differ from both new keys:

```text
evidence-signing.pub               differs from cc and hk
github-evidence-reader.pub         differs from cc and hk
github-go-pr-resolver.pub          differs from cc and hk
github-go-source-reader.pub        differs from cc and hk
github-tasks-writer.pub            differs from cc and hk
task-manifest-signing-public.pem   differs from cc and hk
task-manifest-signing.pub          differs from cc and hk
task-verify.pub                    differs from cc and hk
```

The comparison reads **public keys only**. `task-verify.pub` on HK carries the same
fingerprint as CC's `task-manifest-signing.pub`, which is correct and expected — it is
the public half HK needs in order to verify Tasks signed by CC — and it is not a witness
key either way.

Requested cross-checks:

```text
CC witness != HK witness           OK
CC witness != CC Task key          OK
HK witness != HK Evidence key      OK
CC witness != HK Evidence key      OK      (added for symmetry)
HK witness != CC Task key          OK      (added for symmetry)
```

## The verification battery

Run on each host, against that host's own key:

```text
algorithm verification      cryptography sees Ed25519PrivateKey; openssl -text_pub and
                            asn1parse on the derived SPKI both report ED25519
public key derivation       the private half derives the public half on disk, and
                            openssl's own derivation agrees with cryptography's
key_id / fingerprint        recomputed from the on-disk public key, matches
local sign -> verify        WitnessKey.from_private_pem loads the file and signs a fixed
                            payload; WitnessKey.verify accepts it
modified payload -> failure WitnessKey.verify rejects it; openssl pkeyutl also rejects it
modified signature -> failure WitnessKey.verify rejects it
no reuse                    compared against every other public key on the host
```

The signature test uses `WitnessKey.from_private_pem` — the exact loader the witness will
use — and the same signature is then handed to `openssl pkeyutl -verify -rawin`. Two
independent implementations agreeing is a different statement from one implementation
agreeing with itself.

`openssl` is only ever given **public** material. `asn1parse` on a private key prints the
key bytes as a hex dump, so the algorithm OID is read from the SPKI that openssl derives
from the private key, not from the private key itself. The check was written wrong the
first time for a related reason: `asn1parse` resolves a known OID to its **name**
(`ED25519`), not to `1.3.101.112`, so the original grep could never match.

## Two defects found while building the tools

**The installer could leave a key with the wrong custody.** `chown` to a non-existent
user fails *after* the private key is already on disk, and "fix the ownership afterwards"
is exactly how a key ends up briefly readable by more accounts than intended. The
sandbox caught this the first time it ran against the HK layout (where `go-hk-agent` does
not exist in WSL). The installer now verifies that both the owner user and the owner
group exist **before** generating anything.

**The permission check had to be gated, not relaxed.** POSIX mode bits do not exist on a
Windows workstation, where `st_mode` reports `0o666` for a new file. A relaxed check
would have made the battery report a key as safe for the wrong reason. The custody checks
are skipped with a recorded reason off-POSIX, and the test asserts that they are skipped
rather than passed.

The battery is covered by 13 unit tests (12 pass on this workstation, 1 skips with a
reason) plus an end-to-end WSL run against both host layouts, including two counter-tests:
re-running the installer over an existing key is refused, and a mismatched public key on
disk fails the battery with exactly that check named.

## Nothing was restarted

No `systemctl start|stop|restart` was issued, and `NRestarts=0` for both consuming units:

```text
cc  go-boss-request-bridge.service   Type=oneshot, driven by go-boss-request-bridge.timer
                                     on a ~75 s period (20:09:23, 20:10:38, 20:11:53, 20:13:07)
hk  go-hk-agent.service              Type=oneshot, driven by go-hk-agent.timer on a 60 s period
```

Both are timer-driven oneshot units, so the run counts in the journal during this window
are their own schedule, not restarts — and, usefully, it means each will pick the new key
up on its next scheduled run with no restart required. Neither key is read by anything
yet: the witness runtime is not installed.

## Boundaries

```text
NO deploy, NO merge, NO database change, NO C13/C14 redesign
NO Owner PR touched, NO HK executor modified, NO service restarted
NO private key in chat, stdout, stderr, Git, an Issue, an artifact or the other host
NO reuse of the Task signing key, the HK evidence key, an SSH key, a GitHub PAT or any
   deployment/evidence key
```

The private halves were written directly to their final paths with their final
permissions by `openssl genpkey`, were never printed or echoed, and were never copied
between hosts. The reports this round produced contain a key id, a fingerprint, a public
key, a purpose and paths — a scan of the JSON confirms no `PRIVATE KEY` block is present.
`SECRET_LEAK_SCAN` over the whole repository: **PASS**, 6049 files, 0 gate hits.

Left in place for rotation: `/root/install-witness-signing-key.sh` on both hosts (0700,
contains no secret). Both hosts' `/tmp` scratch directories were removed; the keys remain.

## What this does not do

The witness key is installed but unused. Nothing has been signed with it, because the
runtime that builds a witness record is not deployed — that is CCV1-145's business, along
with the first end-to-end chain that produces a `FINAL_ROOT` from a real candidate. Any
candidate accepted under C13/C14 to date is still synthetic, and `PR #247` is still a
design baseline rather than evidence.
