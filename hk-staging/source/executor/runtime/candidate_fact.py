"""RELEASE_CANDIDATE_V1_CONVERGED -- the single candidate fact authority.

Owner: `control-plane/command-center-candidate-admission-v1`.

This module is the ONE implementation of four things, so that no other component
re-implements them (CCV1-82 CONTRACT SPEC section 5 -- "do not copy json.dumps +
sha256 into more than one component"):

1. the canonical byte form of a converged candidate fact;
2. `candidate_contract_sha256` -- the cross-component candidate digest;
3. the converged field set;
4. the digest *kind* of a candidate document (converged, or one of the legacy
   Hong Kong candidate contracts that are still readable during the transition).

It deliberately knows nothing about deployment plans, migrations, media topology,
execution windows, launcher modules or Hong Kong state. It answers exactly one
question: **what is this candidate?**

Scope note (CCV1-82 section 6 -- "do not include"): the digest covers the candidate
facts and nothing else. It must not cover a rehearsal body, a topology
implementation hash, a launcher module hash, a runtime pin, an execution window or
a deployment mode. Anything of that sort that a legacy document carries is handled
by `legacy_candidate_contract.py` and never reaches this digest.
"""
import hashlib
import json
import re

SCHEMA = "go.release-candidate.v1"
CONTRACT_NAME = "RELEASE_CANDIDATE_V1_CONVERGED"

# The identities a candidate must state about itself. This tuple is the single
# source of the field set: the admission component and the contract schema both
# follow it (a test pins the schema's `required` list to this tuple).
CONVERGED_REQUIRED_FIELDS = (
    "schema", "candidate_id", "source_repository", "source_commit",
    "application_tree", "source_fingerprint", "migration_head",
    "migration_required", "build_definition", "artifact_digest",
    "required_services", "test_result_identity", "rollback_relation",
)
# `artifact_package` is optional so a candidate written before the sealed store
# existed stays readable; its absence is reported, never guessed at.
CONVERGED_OPTIONAL_FIELDS = ("artifact_package",)

CANDIDATE_REPOSITORY = "yuguangzhi3836-glitch/GO"

MIGRATION_REQUIRED_VALUE = False

# The two stable public migration refusal codes (CCV1-82 CONTRACT SPEC section 10,
# implemented by CCV1-84 WP-2).  They are stable contract, not implementation
# detail: request-visibility classifies them and a Boss reads them back.
#
# The pair is deliberately two codes and not one.  "This candidate needs a
# database migration" and "this candidate's migration graph cannot be shown to be
# the one the environment supports" are different refusals with different owner
# actions, and collapsing them would erase the difference at the one place where
# it is cheapest to see.
E_DATABASE_MIGRATION_REQUIRED = "E_DATABASE_MIGRATION_REQUIRED"
E_DATABASE_MIGRATION_GRAPH_MISMATCH = "E_DATABASE_MIGRATION_GRAPH_MISMATCH"

# Tokens this component used before the convergence.  Nothing emits them any more;
# they are kept so that an admission document written earlier stays readable and
# classifiable instead of degrading into an unknown string.  Read old, write new.
LEGACY_MIGRATION_REASON_ALIAS = {
    "candidate_migration_required": E_DATABASE_MIGRATION_REQUIRED,
    "candidate_migration_head": E_DATABASE_MIGRATION_GRAPH_MISMATCH,
}


def public_migration_reason(reason):
    """The stable public code for a legacy migration refusal token, or the token."""
    return LEGACY_MIGRATION_REASON_ALIAS.get(reason, reason)


# --------------------------------------------------------------------------- #
# what the canonical candidate pointer publishes
# --------------------------------------------------------------------------- #
# `docs/canonical-baseline/CURRENT_CANDIDATE.json` carries the converged fact under
# `release_candidate_v1`, and it carries this digest beside it.  The Command Center's
# plan derivation reads that field rather than recomputing the digest, because the one
# implementation of the digest belongs to this component -- a second implementation in
# the derivation would be a second thing to keep in step.  Naming the field here means
# the admission side that publishes the pointer does not have to decide the spelling,
# and the derivation does not have to know how the value was produced.
POINTER_DIGEST_FIELD = "candidate_contract_sha256"


def pointer_digest_field(candidate):
    """The value the pointer must publish for this converged candidate.

    The producer calls this and writes the result beside the fact it is about; a
    producer that reimplements it, or writes a digest of anything else, defeats the
    point of the field.
    """
    return {POINTER_DIGEST_FIELD: candidate_contract_sha256(candidate)}

SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class CandidateFactError(ValueError):
    """The document is not a candidate fact this system may digest."""


# --------------------------------------------------------------------------- #
# canonical bytes -- the one implementation
# --------------------------------------------------------------------------- #
def canonical_bytes(value):
    """The canonical JSON byte form.

    `sort_keys=True` makes the result independent of dictionary insertion order,
    `separators=(",", ":")` makes it independent of pretty-printing and
    whitespace, `allow_nan=False` refuses the non-JSON constants that would
    otherwise produce bytes no other implementation can read back, and the
    explicit `utf-8` encoding makes it independent of the host locale.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_candidate_bytes(candidate):
    """Canonical bytes of a validated converged candidate fact."""
    return canonical_bytes(validate_converged(candidate))


def candidate_contract_sha256(candidate):
    """The cross-component candidate digest.

    The value of this digest is the only thing that proves "these two components
    are talking about the same candidate". It is defined over the converged
    candidate fact alone.
    """
    return hashlib.sha256(canonical_candidate_bytes(candidate)).hexdigest()


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def validate_converged(candidate):
    """The structural rule of the converged fact, or `CandidateFactError`.

    This is the cheap structural gate that must agree with
    `contracts/release_candidate_v1.schema.json`. It does not re-check the
    semantic bindings (artifact against the signed TEST_PR result, source against
    the repository): those belong to admission, which is the component that owns
    the evidence.
    """
    if not isinstance(candidate, dict):
        raise CandidateFactError("candidate_not_an_object")
    fields = set(candidate)
    required = set(CONVERGED_REQUIRED_FIELDS)
    allowed = required | set(CONVERGED_OPTIONAL_FIELDS)
    if not required <= fields:
        missing = sorted(required - fields)
        raise CandidateFactError("candidate_fields_missing:%s" % ",".join(missing))
    if fields - allowed:
        unknown = sorted(fields - allowed)
        raise CandidateFactError("candidate_fields_unknown:%s" % ",".join(unknown))
    if candidate["schema"] != SCHEMA:
        raise CandidateFactError("candidate_schema_not_converged")
    # V1 rule (CCV1-82 section 2.3).  `migration_required` is a
    # PROHIBITED_CONDITION_DECLARATION, not a mode switch: it must be present so
    # that "this candidate needs no migration" is a declaration rather than a
    # missing field, and it must be False because V1 does not execute migrations.
    # A candidate that declares the prohibited condition has no digest.
    obliged = candidate["migration_required"]
    if obliged is not MIGRATION_REQUIRED_VALUE:
        # WP-2 convergence: the fact layer and the admission layer report the same
        # stable public code for this refusal, so a caller cannot tell which layer
        # noticed first and cannot match on two spellings of one condition.
        raise CandidateFactError(E_DATABASE_MIGRATION_REQUIRED)
    digest = candidate.get("artifact_digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise CandidateFactError("candidate_artifact_digest")
    if not SHA256.fullmatch(digest[len("sha256:"):] or ""):
        raise CandidateFactError("candidate_artifact_digest")
    return candidate


# --------------------------------------------------------------------------- #
# digest kind -- internal only, never a public Task field
# --------------------------------------------------------------------------- #
class CandidateDigestKind:
    """Which document family a digest was computed over.

    This exists so that a legacy digest can never be mistaken for a converged
    digest. It is an internal discriminator: it must not appear in the public
    Task or Evidence contract (CCV1-82 section 10).
    """

    CONVERGED = "CONVERGED"
    LEGACY_V1 = "LEGACY_V1"
    LEGACY_V2 = "LEGACY_V2"
    LEGACY_V3 = "LEGACY_V3"

    ALL = (CONVERGED, LEGACY_V1, LEGACY_V2, LEGACY_V3)
    LEGACY = (LEGACY_V1, LEGACY_V2, LEGACY_V3)


LEGACY_SCHEMA_TO_KIND = {
    "go.hk-candidate-contract.v1": CandidateDigestKind.LEGACY_V1,
    "go.hk-candidate-contract.v2": CandidateDigestKind.LEGACY_V2,
    "go.hk-candidate-contract.v3": CandidateDigestKind.LEGACY_V3,
}


def classify_document(document):
    """The digest kind of a candidate document, or `CandidateFactError`.

    Only the `schema` string decides. Nothing is inferred from which files exist.
    """
    if not isinstance(document, dict):
        raise CandidateFactError("candidate_not_an_object")
    schema = document.get("schema")
    if schema == SCHEMA:
        return CandidateDigestKind.CONVERGED
    kind = LEGACY_SCHEMA_TO_KIND.get(schema)
    if kind is None:
        raise CandidateFactError("candidate_schema_unknown")
    return kind


# --------------------------------------------------------------------------- #
# the Hong Kong side check
# --------------------------------------------------------------------------- #
def verify_task_candidate_digest(parameters, candidate):
    """Does the Task's candidate digest match this converged candidate fact?

    This is the Hong Kong side of the digest check, kept in the same module as
    the canonical implementation so that both hosts verify the identical rule.
    It is a pure function: the caller has already read the candidate document
    from its own root-owned store.

    Digest confusion is refused by construction: a legacy document is not
    digestible here at all, because its own digest is computed over a different
    byte form. A legacy digest therefore cannot be presented as a converged one
    even if the hex string is well formed.
    """
    if not isinstance(parameters, dict):
        raise CandidateFactError("parameters_not_an_object")
    presented = parameters.get("candidate_contract_sha256")
    if not isinstance(presented, str) or not SHA256.fullmatch(presented):
        raise CandidateFactError("candidate_digest_absent")
    kind = classify_document(candidate)
    if kind != CandidateDigestKind.CONVERGED:
        raise CandidateFactError("candidate_digest_legacy_not_converged:%s" % kind)
    expected = candidate_contract_sha256(candidate)
    if presented != expected:
        raise CandidateFactError("candidate_digest_mismatch")
    return {"kind": kind, "candidate_contract_sha256": expected}


def legacy_document_digest(document):
    """The digest of a legacy candidate contract, tagged with its own kind.

    Transition-only (T1 / READ_OLD). The returned kind makes the difference
    explicit at every call site, so no caller can silently compare a legacy
    digest against a converged one. Nothing in the new authoritative path may
    call this.
    """
    kind = classify_document(document)
    if kind == CandidateDigestKind.CONVERGED:
        raise CandidateFactError("legacy_digest_called_on_converged_document")
    return {"kind": kind, "legacy_document_sha256": hashlib.sha256(
        canonical_bytes(document)).hexdigest()}
