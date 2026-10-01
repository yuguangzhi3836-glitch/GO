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
service. Its trusted inputs must NOT be exposed as Request fields. The current
clock argument is a deterministic evaluation instant for offline tests; the live
adapter must resample it after any lock wait and before signing/publishing. No
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

16 tests pass, including receipt roundtrip and durable readback, signature rejection,
registration expiry, generation changes, identity rebinding, wrong host/artifact/key,
extra fields, arbitrary commands, task/nonce replay across DB connections, crash
claim preservation and stale/tampered receipts. All keys are ephemeral test keys;
no server commands or external tasks are issued. Concurrent process races, live
clock sampling, protected-path checks, bootstrap and GitHub transport E2E remain
unproven and must be completed before independent acceptance and installation.
