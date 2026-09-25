"""Witness layer: CC verification / witness / aggregation and the HK acceptance witness.

This package is the *next* layer above ``control-plane/c13-c14-lite`` (PR #248).
The dependency is one-way and deliberate:

    c13-c14-lite  produces the sealed bundles and the ledger binding
    c13-c14-witness  verifies them, witnesses them, and aggregates

Nothing here runs an AI model, Docker, PostgreSQL or candidate code. Nothing here
can deploy, merge or authorise anything: every record carries
``authorizes_any_action = false``, and an accepted result stops at
``READY_FOR_HUMAN_AUTHORIZATION``.

The observation that shapes the whole layer (measured in PR #248): GitHub returns
``run`` and ``artifact`` *metadata* to a normal credential, including the
GitHub-computed ``artifact.digest``, but the artifact ZIP and the job log both
redirect to a storage endpoint that rejects it. Verification is therefore split
into two honest levels — metadata, and bytes — and a bytes failure is recorded as
``ARTIFACT_BYTES_UNAVAILABLE``, never as a pass.
"""

WITNESS_SCHEMA_VERSION = "go.c13c14.witness.cc_witness.v1"
HK_WITNESS_SCHEMA_VERSION = "go.c13c14.witness.hk_witness.v1"
LEDGER_SCHEMA_VERSION = "go.c13c14.witness.first_seen_ledger.v1"
VERIFICATION_SCHEMA_VERSION = "go.c13c14.witness.verification.v1"
AGGREGATE_SCHEMA_VERSION = "go.c13c14.witness.final_acceptance.v1"
WRITEBACK_SCHEMA_VERSION = "go.c13c14.witness.writeback.v1"

ARTIFACT_METADATA_VERIFIED = "ARTIFACT_METADATA_VERIFIED"
ARTIFACT_BYTES_VERIFIED = "ARTIFACT_BYTES_VERIFIED"
ARTIFACT_BYTES_UNAVAILABLE = "ARTIFACT_BYTES_UNAVAILABLE"

READY_FOR_HUMAN_AUTHORIZATION = "READY_FOR_HUMAN_AUTHORIZATION"

ACCEPTED = "ACCEPTED"
BLOCKED = "BLOCKED"
REJECTED = "REJECTED"
