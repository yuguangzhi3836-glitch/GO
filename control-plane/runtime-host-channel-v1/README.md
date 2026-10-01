# Dedicated Runtime host channel — offline candidate V1

Status: SOURCE_CANDIDATE / NOT_INSTALLED / LIVE_ENROLLMENT_NOT_PROVEN.
This module adds the registration, restricted probe and receipt-validation core for a
separate test-host channel. It does not change the existing six-action HK Bridge,
its deployed allowlist, any credentials, or the Runtime candidate.
The real target and disclosure authorization remain in Draft PR #289 at
`28e185e523631439c38800ed4ed1250816735755`; fixtures here are synthetic.

## Implemented

- Authority-signed, expiring registration binds environment, unique host/agent,
  monotonic generation, immutable candidate, plan/executor digests, evidence-key
  fingerprint and approval reference. Exact fields; duplicate keys rejected.
- Dedicated SQLite registry refuses identity rebinding and generation rollback.
- Proposed `RUNTIME_HOST_PROBE_V1` accepts no parameters, shell, URL, path, service
  selection, deployment or reboot. The name is a proposed protocol constant, NOT
  an existing Boss Request action. Do not publish it to the live request repository.
- Task verification binds to the current registration and independently observed
  host and installed executor digest. Evidence key must match the registered key.
- Durable claim precedes result generation. Task ID and nonce have independent
  uniqueness constraints. A crash after claim is uncertain/CLAIMED, never retried
  automatically. Completed signed bytes are read back without re-executing.
- CC-side receipt verification checks signature, registered key, task/registration
  binding, timestamp, executor and exact PROBE_ONLY / NOT_RUN semantics.

## Trust and integration boundary

`Registry` is an offline library, not a daemon, installer, enrollment API or signer
service. Its trusted inputs must NOT be exposed as Request fields. The clock argument accepts a callable; the trusted live adapter must provide its
clock (never a caller timestamp). Registration and probe validation resample after
lock acquisition. Publishing must separately recheck expiry before transmission. No
live adapter exists in this candidate, so it is not safe to wire directly to live
polling or call it a complete installed channel.

Before installation, an independently reviewed adapter must:

1. Obtain authenticated operator approval and host-bound topology review before
   signing registration. Verify approval_ref resolves to that exact binding; this
   module only validates reference syntax and authority signature.
2. Load pinned public keys and registry state from protected root-owned paths,
   reject symlinks/unsafe ancestors, prove executor bytes and cloud instance identity
   locally, and implement revocation/rotation in the authority's registration flow.
3. Authenticate the GitHub Request author/repository/immutable head, derive task
   fields server-side, persist the exact signed task before publishing through the
   existing Tasks writer; ambiguous publication requires readback, not re-signing.
4. Poll only the new environment using a separate management Agent identity.
   Provision identities using a reviewed bootstrap path; never copy old HK keys.
5. Publish stored receipt bytes through the existing Evidence transport, read them
   back and run verify_evidence. No runtime secrets may enter the Runtime process.
6. Supply a frozen, reviewed host-acceptance installer/fixture before adding an
   installation or fault-injection action. The only action implemented here is a
   read-only identity probe. No source claim can promote it to host acceptance.

Runtime stays private-network/no credentials. The management Agent lives outside
that process boundary. Production, old HK-STAGING, business containers, payment,
provider access and long-term residency remain outside this change.

## Offline validation

Requires Python 3 and cryptography 46.0.0 (already available during this run).

```sh
cd control-plane/runtime-host-channel-v1
python -m unittest -v
```

21 distinct test methods pass, including receipt roundtrip and durable readback, signature rejection,
registration expiry, generation changes, identity rebinding, wrong host/artifact/key,
extra fields, arbitrary commands, task/nonce replay across DB connections, crash
claim preservation and stale/tampered receipts. All keys are ephemeral test keys;
no server commands or external tasks are issued. Threaded concurrent SQLite connections, expiry after lock acquisition, and
root-owned/symlink/unsafe-parent fixture checks pass. Multi-process crash/publish
races, real bootstrap and GitHub transport E2E remain unproven and must be completed before independent acceptance and installation.

## Additional adapter primitives

`adapter.py` provides descriptor-relative protected reads with no symlink traversal
and root/no-group-write validation on every ancestor, plus fixed probe task derivation
from a registration. The caller must be the existing authenticated immutable-PR
Bridge boundary; passing an author string by itself is not authentication. It is
not yet wired into that Bridge. These functions do not sign or publish live tasks.

## 2026-10-01 signing / publishing / polling integration increment

`flow.py` now connects verified registration initialization, trusted-author Request
validation, task derivation/signing, durable outbox, immutable transport, one-pass
Agent polling, stored Evidence publication/readback and CC receipt collection.
`git_transport.py` provides the Git adapter. It uses a separate `runtime-host-v1/`
namespace; it MUST NOT be pointed at live repositories until that namespace and
new protocol are independently reviewed and installed. Legacy HK task JSON/signature
format differs from this envelope, so silently passing it to the existing writer
or old Agent is unsafe and is not implemented.

- Sign once and commit the exact bytes before publication.
- Commit ATTEMPTED before network I/O. A lost acknowledgement reconciles by readback;
  absent or conflicting bytes remain unresolved and are not automatically resent.
- Polling does not execute an already-claimed task again. Completed receipt bytes
  are reused, including after a lost Evidence publication acknowledgement.
- Initialization rejects wrong observed host, executable digest or Evidence key
  before enrolling. It creates no credentials and installs no system services.
- Git uses explicit argv, fixed trusted remote/branch configuration, exact keys,
  no force push, no arbitrary command and no automatic rebase/retry.

Validation now: **33 distinct unittest methods PASS**. The E2E runs both against
in-memory fault-injection transports and two actual temporary local bare Git
repositories (Tasks and Evidence). The latter performs commits, pushes, fresh
clones and readbacks. All host IDs/keys/approvals remain synthetic. Local bare Git
E2E is not real GitHub authentication, CC deployment, cloud initialization or live
host acceptance. No server command or external Task was issued.

### Live installation blockers (still mandatory)

1. A reachable authorized CC management session is not available in this conversation;
   Remote Desktop Commander currently reports only EASON Offline. The new VM's
   Workbench session does not grant access to the existing CC host.
2. Independent review must approve this new protocol/namespace, registration authority,
   Request authentication adapter and separate service identities before installation.
   `authenticated_author` remains an internal trusted argument, NOT a user input.
3. Provision the new host's distinct credentials via an approved bootstrap, bind
   cloud-observed identity and actual executable digest, and resolve approval_ref
   against the exact approved host/plan. None is supplied by this source proposal.
4. Wire the installed immutable-PR reader, root-owned key/DB paths, timer/service,
   transport remotes, revocation behavior and bounded rejection telemetry. The new
   transport exists in source, but those live settings and service units do not.
5. Run real Request → Task → Agent → Evidence E2E before claiming enrollment.
   Full Runtime installation/fault/reboot acceptance remains a separate frozen
   executor/fixture, still NOT_RUN. Current probe can never report that acceptance PASS.

Earlier paragraphs describe earlier increments; this section supersedes their
statements that signing/polling/Git transport source is absent. It does not supersede
NOT_INSTALLED or the pending live integration and host acceptance boundaries.
