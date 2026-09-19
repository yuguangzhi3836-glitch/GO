"""Legacy Hong Kong candidate contract -- READ ONLY.

    LEGACY READ ONLY
    DO NOT WRITE
    RETIRE AT T10

Transition phase T1 (`READ_OLD`) of CCV1-82. The three legacy documents below were
introduced by the Hong Kong media-topology line and are still the shape the live
hosts were installed from. The converged baseline has to be able to *read* them so
that history stays interpretable and nothing has to be deleted in one step, but it
must never *produce* them again: after T1 the only authoritative candidate fact is
`go.release-candidate.v1` (see `candidate_fact.py`).

What this module does
---------------------
* recognises the three legacy schemas by their `schema` string;
* validates their field shape so a malformed legacy document is reported rather
  than partially believed;
* produces a `LEGACY_CANDIDATE_VIEW`: the legacy facts, the fields that are *not*
  candidate facts, and the facts a converged candidate needs but a legacy document
  cannot supply.

What it must never do
---------------------
* write, register, extend or sign a legacy document;
* pretend a legacy document is a converged candidate;
* let a legacy digest be compared against a converged digest without an explicit
  kind (that comparison is refused in `candidate_fact.verify_task_candidate_digest`).

`LEGACY_MAPPING_GAP` is reported, never papered over: where a legacy field has no
loss-free converged destination, the gap is named and the value is left in the
legacy view instead of being guessed into the converged fact.
"""
import re

from candidate_fact import CandidateFactError, CandidateDigestKind

LEGACY_READ_ONLY = True
LEGACY_WRITES_ALLOWED = False
RETIRE_AT = "T10"

SCHEMA_V1 = "go.hk-candidate-contract.v1"
SCHEMA_V2 = "go.hk-candidate-contract.v2"
SCHEMA_V3 = "go.hk-candidate-contract.v3"
LEGACY_SCHEMAS = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9][0-9a-z_]{1,79}$")

LEGACY_CANDIDATE_FIELDS = ("repository", "source_commit", "application_git_tree",
                           "source_tree_sha256", "package_sha256", "image_id")

# The field sets the three legacy schemas actually carry. Reproduced here because a
# reader has to know the shape it is reading; the writer of these documents is gone
# from this baseline and must not come back.
_BASE_FIELDS = ("schema", "environment", "profile", "candidate",
                "expected_current_image_id", "baseline_revision", "target_revision")
_V1_FIELDS = frozenset(_BASE_FIELDS + ("rehearsal", "rehearsal_sha256"))
_V2_FIELDS = frozenset((set(_BASE_FIELDS) - {"rehearsal", "rehearsal_sha256"}) | {
    "migration_required", "migration_source_digest",
    "baseline_migration_source_digest", "test_pr_evidence_sha256"})
_V3_FIELDS = frozenset(set(_V2_FIELDS) | {"topology"})

LEGACY_FIELDS = {SCHEMA_V1: _V1_FIELDS, SCHEMA_V2: _V2_FIELDS, SCHEMA_V3: _V3_FIELDS}

KIND_OF_SCHEMA = {SCHEMA_V1: CandidateDigestKind.LEGACY_V1,
                  SCHEMA_V2: CandidateDigestKind.LEGACY_V2,
                  SCHEMA_V3: CandidateDigestKind.LEGACY_V3}

# --------------------------------------------------------------------------- #
# the mapping table (CCV1-82 section 9) -- explicit, and tested
# --------------------------------------------------------------------------- #
# `action` is one of:
#   MAP                  the legacy value is the converged value
#   MAP_TO_PACKAGE       the legacy value lands inside a converged sub-object
#   NOT_CANDIDATE_FACT   a real fact, but about the plan / evidence / capability
#   GAP                  the converged candidate needs it and legacy cannot supply it
LEGACY_FIELD_MAP = (
    {"legacy": "schema", "converged": "schema", "action": "MAP",
     "note": "the value itself changes: go.hk-candidate-contract.* -> "
             "go.release-candidate.v1"},
    {"legacy": "candidate.repository", "converged": "source_repository",
     "action": "MAP"},
    {"legacy": "candidate.source_commit", "converged": "source_commit",
     "action": "MAP"},
    {"legacy": "candidate.application_git_tree", "converged": "application_tree",
     "action": "MAP"},
    {"legacy": "candidate.source_tree_sha256", "converged": "source_fingerprint",
     "action": "GAP",
     "note": "NOT loss-free. The converged `source_fingerprint` is the repository's "
             "own defined fingerprint over application/; the legacy field is a "
             "sha256 of a source tree produced by the media-topology line. Same "
             "shape, different definition: mapping them would silently redefine the "
             "identity admission checks."},
    {"legacy": "candidate.package_sha256", "converged":
     "artifact_package.package_sha256", "action": "MAP_TO_PACKAGE"},
    {"legacy": "candidate.image_id", "converged": "artifact_digest", "action": "MAP"},
    {"legacy": "expected_current_image_id", "converged": None,
     "action": "NOT_CANDIDATE_FACT", "note": "belongs to the plan"},
    {"legacy": "baseline_revision", "converged": None,
     "action": "NOT_CANDIDATE_FACT", "note": "deployment intent, belongs to the plan"},
    {"legacy": "target_revision", "converged": None,
     "action": "NOT_CANDIDATE_FACT", "note": "deployment intent, belongs to the plan"},
    {"legacy": "rehearsal", "converged": None, "action": "NOT_CANDIDATE_FACT",
     "note": "evidence body; never part of a candidate fact"},
    {"legacy": "rehearsal_sha256", "converged": None,
     "action": "NOT_CANDIDATE_FACT",
     "note": "an implementation checksum, not a candidate identity"},
    {"legacy": "topology", "converged": None, "action": "NOT_CANDIDATE_FACT",
     "note": "future optional capability (WP-3)"},
    {"legacy": "migration_required", "converged": "migration_required",
     "action": "MAP",
     "note": "V1 keeps the field as a PROHIBITED_CONDITION_DECLARATION. v2/v3 "
             "carry it explicitly and demand it be false; v1 has no such field at "
             "all, its schema *is* the migration mode, so a v1 document is read as "
             "declaring the prohibited condition and therefore has no converged "
             "form. There is no legacy migration_head field."},
    {"legacy": "migration_source_digest", "converged": None,
     "action": "NOT_CANDIDATE_FACT", "note": "same-revision proof input, not identity"},
    {"legacy": "baseline_migration_source_digest", "converged": None,
     "action": "NOT_CANDIDATE_FACT", "note": "same-revision proof input, not identity"},
    {"legacy": "test_pr_evidence_sha256", "converged": None,
     "action": "NOT_CANDIDATE_FACT",
     "note": "a digest of an evidence file; the converged fact carries "
             "test_result_identity (a record identity) instead, which legacy cannot "
             "supply -- see the GAP row below"},
    {"legacy": "environment", "converged": None, "action": "NOT_CANDIDATE_FACT",
     "note": "the converged fact is repository-scoped, not environment-scoped"},
    {"legacy": "profile", "converged": None, "action": "NOT_CANDIDATE_FACT",
     "note": "the converged fact carries build_definition.profile, which legacy "
             "does not supply as a build identity"},
    # facts a converged candidate must state that no legacy document carries
    {"legacy": None, "converged": "candidate_id", "action": "GAP",
     "note": "no legacy equivalent"},
    {"legacy": None, "converged": "build_definition", "action": "GAP",
     "note": "no legacy equivalent; legacy names a profile string only"},
    {"legacy": None, "converged": "required_services", "action": "GAP",
     "note": "no legacy equivalent"},
    {"legacy": None, "converged": "test_result_identity", "action": "GAP",
     "note": "legacy carries only test_pr_evidence_sha256, a file digest rather "
             "than the record identity admission binds"},
    {"legacy": None, "converged": "rollback_relation", "action": "GAP",
     "note": "legacy expected_current_image_id states the current image, not the "
             "rollback relation admission requires"},
)

LEGACY_MAPPING_GAPS = tuple(entry["converged"] for entry in LEGACY_FIELD_MAP
                            if entry["action"] == "GAP")


class LegacyContractError(ValueError):
    """The document is not a legacy candidate contract this reader accepts."""


def is_legacy(document):
    return isinstance(document, dict) and document.get("schema") in LEGACY_SCHEMAS


def read_legacy(document):
    """Validate a legacy contract's shape and return a `LEGACY_CANDIDATE_VIEW`.

    Reading is the only supported operation. A malformed legacy document raises
    rather than being partially believed: a half-read candidate is exactly how the
    two-identity problem started.
    """
    if not isinstance(document, dict):
        raise LegacyContractError("legacy_not_an_object")
    schema = document.get("schema")
    if schema not in LEGACY_SCHEMAS:
        raise LegacyContractError("legacy_schema_unknown")
    expected = LEGACY_FIELDS[schema]
    fields = set(document)
    if fields != expected:
        if expected - fields:
            raise LegacyContractError("legacy_fields_missing:%s"
                                      % ",".join(sorted(expected - fields)))
        raise LegacyContractError("legacy_fields_unknown:%s"
                                  % ",".join(sorted(fields - expected)))

    candidate = document.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != set(LEGACY_CANDIDATE_FIELDS):
        raise LegacyContractError("legacy_candidate_fields")
    for name, pattern in (("source_commit", COMMIT),
                          ("application_git_tree", COMMIT),
                          ("source_tree_sha256", SHA256),
                          ("package_sha256", SHA256),
                          ("image_id", IMAGE)):
        value = candidate.get(name)
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise LegacyContractError("legacy_candidate_identity:%s" % name)
    if candidate.get("repository") != "yuguangzhi3836-glitch/GO":
        raise LegacyContractError("legacy_candidate_repository")
    for name in ("baseline_revision", "target_revision"):
        value = document.get(name)
        if not isinstance(value, str) or REVISION.fullmatch(value) is None:
            raise LegacyContractError("legacy_revision:%s" % name)
    if not isinstance(document.get("expected_current_image_id"), str) \
            or IMAGE.fullmatch(document["expected_current_image_id"]) is None:
        raise LegacyContractError("legacy_expected_current_image")
    if "migration_required" in document and document["migration_required"] is not False \
            and document["migration_required"] is not True:
        raise LegacyContractError("legacy_migration_required")
    if schema == SCHEMA_V1 and not isinstance(document.get("rehearsal"), dict):
        raise LegacyContractError("legacy_rehearsal_missing")
    if schema == SCHEMA_V3 and not isinstance(document.get("topology"), dict):
        raise LegacyContractError("legacy_topology_missing")

    return legacy_view(document)


def legacy_view(document):
    """The explicit boundary object. Not a candidate: a legacy view of one."""
    kind = KIND_OF_SCHEMA[document["schema"]]
    facts = {
        "source_repository": document["candidate"]["repository"],
        "source_commit": document["candidate"]["source_commit"],
        "application_tree": document["candidate"]["application_git_tree"],
        "artifact_digest": document["candidate"]["image_id"],
        "artifact_package": {"package_sha256": document["candidate"]["package_sha256"]},
        "migration_required": document.get("migration_required", True),
    }
    not_candidate_facts = {name: document[name] for name in
                           ("expected_current_image_id", "baseline_revision",
                            "target_revision", "environment", "profile")
                           if name in document}
    for name in ("rehearsal", "rehearsal_sha256", "topology",
                 "migration_source_digest", "baseline_migration_source_digest",
                 "test_pr_evidence_sha256"):
        if name in document:
            not_candidate_facts[name] = document[name]
    return {
        "kind": kind,
        "schema": document["schema"],
        "read_only": LEGACY_READ_ONLY,
        "retire_at": RETIRE_AT,
        "facts": facts,
        "not_candidate_facts": not_candidate_facts,
        "gaps": list(LEGACY_MAPPING_GAPS),
        "source_tree_sha256_not_mapped": document["candidate"]["source_tree_sha256"],
    }


def converged_partial(view):
    """What a legacy view can and cannot contribute to a converged candidate.

    The result is deliberately *not* a converged candidate: five identities a
    converged candidate must state cannot be read from any legacy document, so no
    legacy document can be promoted. Callers must treat `gaps` as a refusal, not as
    a TODO.
    """
    if not isinstance(view, dict) or view.get("kind") not in CandidateDigestKind.LEGACY:
        raise LegacyContractError("legacy_view_required")
    supplied = {name: value for name, value in view["facts"].items()
                if name not in ("artifact_package",)}
    if view["facts"].get("artifact_package", {}).get("package_sha256"):
        supplied["artifact_package"] = dict(view["facts"]["artifact_package"])
    return {
        "schema": "go.release-candidate.v1",
        "supplied": supplied,
        "gaps": list(view["gaps"]),
        "promotable": not view["gaps"],
    }


def assert_legacy_is_read_only():
    """The module's own contract, asserted where a reader can see it."""
    return {"legacy_read_only": LEGACY_READ_ONLY,
            "legacy_writes_allowed": LEGACY_WRITES_ALLOWED,
            "retire_at": RETIRE_AT,
            "legacy_schemas": list(LEGACY_SCHEMAS),
            "legacy_mapping_gaps": list(LEGACY_MAPPING_GAPS)}


__all__ = [
    "CandidateFactError", "LegacyContractError", "LEGACY_FIELD_MAP",
    "LEGACY_MAPPING_GAPS", "LEGACY_SCHEMAS", "LEGACY_READ_ONLY",
    "LEGACY_WRITES_ALLOWED", "RETIRE_AT", "assert_legacy_is_read_only",
    "converged_partial", "is_legacy", "legacy_view", "read_legacy",
]
