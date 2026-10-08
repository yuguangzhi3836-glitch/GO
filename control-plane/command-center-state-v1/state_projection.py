#!/usr/bin/env python3
"""GO Command Center control-state projection — CONTROL_STATE_V1.

Scope: CONTROL_STATE_AND_STATUS_ONLY.

Read-only, offline, deterministic projection of the GitHub-native Control Plane.
It answers one question: *given only the control bus, what is the current control
state?*  It never invents an answer.  Every leaf is an assertion carrying a state
from {PROVEN, OBSERVED, PENDING, HOLD, FAILED, UNKNOWN} plus the evidence
references that produced it.  Absence of evidence is reported as UNKNOWN, never
as success.

Identity discipline
-------------------
Signed Tasks and Signed Evidence are verified with **different** verifier
identities:

  * the Command Center task-manifest signing key  (``--task-verify-key``)
  * the Hong Kong agent evidence signing key      (``--evidence-verify-key``)

A Task must never validate against the evidence key and Evidence must never
validate against the task key.  If both public keys turn out to be the same key,
the projection refuses to claim PROVEN for anything and records a
VERIFIER_IDENTITY_COLLISION anomaly.

Runtime discipline
------------------
There is no repository pointer any more: the one that existed was retired on
2026-10-08, because a declaration inside a repository is never the truth about what
is running on Hong Kong.  ``repository_runtime_pointer`` is therefore always
UNKNOWN, and ``runtime_verification`` is read out of ``live_verified_runtime`` --
the newest signed VERIFY Evidence -- reporting MATCH / NOT_RECENTLY_VERIFIED /
UNKNOWN.  DRIFT stays in the enum but is unreachable: there is nothing declared for
a live runtime to drift from.

Portability
-----------
The derived output contains no workstation path, no temp directory and no local
absolute path.  Sources are identified by repository, ref, commit SHA, artifact
id and repository-relative path only, so two different machines projecting the
same inputs produce a semantically equivalent, stable document.

Authority
---------
The output is a DERIVED, NON-AUTHORITATIVE view.  The Signed Task is the only
Execution Authority and the Signed Evidence is the only proof.  This file is
never hand-edited and is always rebuildable.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

SCHEMA_VERSION = "1"
CONTRACT_STATE = "CURRENT_CONTROL_STATE"
CONTRACT_STATUS = "CONTROL_STATUS_V1"
CONTRACT_SCOPE = "CONTROL_STATE_AND_STATUS_ONLY"

STATE_PROVEN = "PROVEN"
STATE_OBSERVED = "OBSERVED"
STATE_PENDING = "PENDING"
STATE_HOLD = "HOLD"
STATE_FAILED = "FAILED"
STATE_UNKNOWN = "UNKNOWN"

RUNTIME_MATCH = "MATCH"
RUNTIME_DRIFT = "DRIFT"
RUNTIME_NOT_RECENTLY_VERIFIED = "NOT_RECENTLY_VERIFIED"
RUNTIME_UNKNOWN = "UNKNOWN"

AUTHORITY = "DERIVED_NON_AUTHORITATIVE"

# Liveness freshness. The probe interval and the freshness window are not the
# same number: a probe that is issued exactly on schedule still has to travel
# GitHub -> Bridge -> Hong Kong -> Evidence -> Projection before it can be read
# here, so a window equal to the interval declares the agent stale for the whole
# time its own evidence is in flight. The grace is transport slack, not a second
# way to infer liveness: ONLINE still requires signature-verified Evidence.
#   age <= LIVENESS_FRESHNESS_WINDOW_SECONDS -> PROVEN
#   age >  LIVENESS_FRESHNESS_WINDOW_SECONDS -> UNKNOWN, never PROVEN
LIVENESS_PROBE_INTERVAL_SECONDS = 1800
LIVENESS_TRANSPORT_GRACE_SECONDS = 600
LIVENESS_FRESHNESS_WINDOW_SECONDS = (LIVENESS_PROBE_INTERVAL_SECONDS
                                     + LIVENESS_TRANSPORT_GRACE_SECONDS)
LIVENESS_MAX_PROBES_PER_24H = 48

TASKS_REPOSITORY = "chenzhenxi1-sudo/go-control-tasks"
EVIDENCE_REPOSITORY = "chenzhenxi1-sudo/go-control-evidence"
GO_REPOSITORY = "yuguangzhi3836-glitch/GO"
# The retired `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` pointer lived here. It was
# removed on 2026-10-08: a repository file claiming to be "the single authoritative pointer
# for the runtime actually running on HK-STAGING" could not be kept true, and its drift is
# precisely what made a verified deployment look wrong. A runtime's identity is now
# established from signed live Evidence, never from a repository declaration.
CANONICAL_CANDIDATE_POINTER = "docs/canonical-baseline/CURRENT_CANDIDATE.json"

TASK_VERIFIER_IDENTITY = "GO Command Center task-manifest signer"
EVIDENCE_VERIFIER_IDENTITY = "Hong Kong agent evidence signer"

# The published verifier identity contract (CC V1-01). A verifier key is only
# trusted when its fingerprint matches the published identity; a key that merely
# loads is never treated as the right key.
IDENTITY_CONTRACT_NAME = "VERIFIER_IDENTITIES_V1"
IDENTITY_CONTRACT_RELPATH = "identity/VERIFIER_IDENTITIES_V1.json"
ROLE_TASK = "TASK"
ROLE_EVIDENCE = "EVIDENCE"

BINDING_BOUND = "BOUND"
BINDING_MISSING_KEY = "MISSING_KEY"
BINDING_KEY_UNREADABLE = "KEY_UNREADABLE"
BINDING_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
BINDING_IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
BINDING_IDENTITY_COLLISION = "IDENTITY_COLLISION"

# Every binding other than BOUND is fail-closed: it may never yield PROVEN.
FAIL_CLOSED_BINDINGS = (BINDING_MISSING_KEY, BINDING_KEY_UNREADABLE,
                        BINDING_IDENTITY_MISMATCH, BINDING_IDENTITY_UNRESOLVED,
                        BINDING_IDENTITY_COLLISION)


def default_identity_contract_path():
    """The published contract, resolved relative to this file, not the cwd."""
    return pathlib.Path(__file__).resolve().parent / IDENTITY_CONTRACT_RELPATH

# Every action the Control Plane can execute.
KNOWN_CAPABILITIES = (
    "CONTROL_PLANE_HEALTH",
    "HK_STAGING_VERIFY",
    "HK_STAGING_TEST_PR",
    "HK_STAGING_DEPLOY",
    "HK_STAGING_CANARY",
    "HK_STAGING_ROLLBACK",
)
# Who can express an action as a Request. The human / ChatGPT channel and the
# platform's own automated producer are different classes of caller. Conflating
# them would either mis-report a real liveness Request as forbidden or promote a
# read-only probe into a human execution right, so the source class is carried
# explicitly rather than inferred from the action name.
HUMAN_REQUEST_ACTIONS = ("HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", "HK_STAGING_DEPLOY",
                         "HK_STAGING_CANARY", "HK_STAGING_ROLLBACK")
PLATFORM_REQUEST_ACTIONS = ("CONTROL_PLANE_HEALTH",)
# What the channel can create *right now*, per class. There is no deploy switch,
# so DEPLOY is present here exactly as this repository's own channel contract lists
# it: all six actions are declared with `deployment_authorization: "request"`, and
# the authenticated DEPLOY Request is
# itself the authorisation. Absence from this set is a claim that the action is
# refused by the contract, so a stale constant here reads to a connector as
# "you may not deploy" -- which is the one answer this projection must never
# invent. CANARY is present because a canary is the evidence a deployment plan
# must cite, so it has to be obtainable before a plan can exist at all; ROLLBACK
# is present because it is the undo of a deployment and takes the same authority
# it does. Neither chooses its own target: the canary's images come from the
# root-owned canary authority, and the rollback target is the newest deployment
# the Bridge itself published, which the executor re-hashes and re-reads before
# it acts. The platform producer drives a read-only probe on a timer, so HEALTH
# is present too -- as a platform action, never as a human right.
ENABLED_HUMAN_REQUEST_ACTIONS = ("HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", "HK_STAGING_DEPLOY",
                                 "HK_STAGING_CANARY", "HK_STAGING_ROLLBACK")
ENABLED_PLATFORM_REQUEST_ACTIONS = ("CONTROL_PLANE_HEALTH",)
ENABLED_REQUEST_ACTIONS = (ENABLED_HUMAN_REQUEST_ACTIONS
                           + ENABLED_PLATFORM_REQUEST_ACTIONS)
REQUEST_ACTION_SOURCE_CLASS = {
    "HK_STAGING_VERIFY": "HUMAN_REQUEST",
    "HK_STAGING_TEST_PR": "HUMAN_REQUEST",
    "HK_STAGING_DEPLOY": "HUMAN_REQUEST",
    "HK_STAGING_CANARY": "HUMAN_REQUEST",
    "HK_STAGING_ROLLBACK": "HUMAN_REQUEST",
    "CONTROL_PLANE_HEALTH": "PLATFORM_AUTOMATION",
}
# What a platform action is allowed to be. These are constants copied from the
# channel and Task contracts, never derived from a Request: a Request that could
# change them would make the platform class a way to carry parameters.
PLATFORM_ACTION_PROPERTIES = {
    "CONTROL_PLANE_HEALTH": {"source_class": "PLATFORM_AUTOMATION",
                             "parameters": {}, "read_only": True,
                             "human_deploy_authority": False},
}
CAPABILITY_CLASSIFICATION = {
    "HK_STAGING_VERIFY": "SUPPORTED_PROVEN",
    "HK_STAGING_TEST_PR": "SUPPORTED_PROVEN",
    # Proven and requestable: it ran end to end on HK-STAGING-01, and since the
    # 2026-09-17 redesign there is no switch to open -- the authenticated Request
    # is the authorisation. It is deliberately NOT classified as disabled: a
    # classification is read as an answer about what may be requested.
    "HK_STAGING_DEPLOY": "SUPPORTED_PROVEN",
    # Requestable without a switch: a canary mutates no business runtime, and it has
    # to exist before a deployment plan can be registered at all.
    "HK_STAGING_CANARY": "CAPABILITY_PRESENT_REQUESTABLE",
    # Requestable from the channel revision that added the action. The classification
    # says what can be expressed, not whether a particular rollback is meaningful: that
    # is decided on the host, against the deployment record, at execution time.
    "HK_STAGING_ROLLBACK": "CAPABILITY_PRESENT_REQUESTABLE",
    # Proven, but only for the platform class: it says nothing about whether a
    # human may request it, and it confers no execution right on anyone.
    "CONTROL_PLANE_HEALTH": "SUPPORTED_PROVEN_PLATFORM_ONLY",
}

TASK_REQUIRED = {"schema_version", "task_id", "environment", "action_id", "issued_at",
                 "expires_at", "nonce", "parameters", "authority", "signature"}
EVIDENCE_COMMON = {"schema_version", "task_id", "nonce", "action_id", "environment",
                   "status", "started_at", "signature"}
REQUEST_REQUIRED = {"schema_version", "request_id", "action_id", "environment", "requested_at"}


# Shapes this Control Plane is still able to READ, but which are no longer what it
# would accept from a fresh Task.  They are exact, named and closed -- never a
# wildcard -- and they exist because the 2026-09-16 sealed-artifact re-contract
# renamed the candidate delivery identity: the old name carried a registry digest
# that had to end in the image id, which no real candidate could ever satisfy.
#
# A Task in one of these shapes predates the rename.  It stays readable and keeps
# its Evidence, and it is marked SUPERSEDED rather than held, because holding it
# would silently erase real historical proof.  A generated Task is never written
# in these shapes: the deploy entry and the Hong Kong executor only emit the
# current one.
SUPERSEDED_PARAMETERS = {
    "HK_STAGING_CANARY": ({"release_id", "candidate_image_id", "candidate_repo_digest",
                           "expected_current_image_id"},),
    "HK_STAGING_DEPLOY": ({"release_id", "candidate_image_id", "candidate_repo_digest",
                           "expected_current_image_id", "canary_evidence_id",
                           "approval_id"},
                          # The shape CCV1-85 replaced: the same six facts without the
                          # candidate's content address. Nothing generates it any more, and
                          # historical deployments keep their place in the projection with
                          # an explicit marker rather than being dropped or re-read as
                          # current.
                          {"release_id", "candidate_image_id", "candidate_package_sha256",
                           "expected_current_image_id", "canary_evidence_id", "approval_id"},),
}

ACTION_PARAMETERS = {
    "CONTROL_PLANE_HEALTH": set(),
    "HK_STAGING_VERIFY": {"release_id", "candidate_image_id", "expected_current_image_id"},
    "HK_STAGING_CANARY": {"release_id", "candidate_image_id", "candidate_package_sha256",
                          "expected_current_image_id"},
    "HK_STAGING_DEPLOY": {"release_id", "candidate_image_id", "candidate_package_sha256",
                          "expected_current_image_id", "canary_evidence_id", "approval_id",
                          "candidate_contract_sha256"},
    "HK_STAGING_ROLLBACK": {"release_id", "source_deploy_task_id", "approval_id"},
    "HK_STAGING_TEST_PR": {"builder_profile", "source"},
}
ACTION_RESULT = {
    "HK_STAGING_VERIFY": "VERIFY_OK",
    "HK_STAGING_CANARY": "CANARY_OK",
    "HK_STAGING_DEPLOY": "DEPLOY_OK",
    "HK_STAGING_ROLLBACK": "ROLLBACK_OK",
    "HK_STAGING_TEST_PR": "TEST_PR_OK",
    "CONTROL_PLANE_HEALTH": None,
}
REQUEST_EXTRA_FIELDS = {
    "HK_STAGING_VERIFY": set(),
    "HK_STAGING_TEST_PR": {"pr_number"},
    # A deploy carries the five common fields and nothing else, exactly like the
    # canary and the rollback. A plan_id used to name a plan a human had written;
    # the plan is derived by the Command Center now, so a caller-chosen name would
    # only be a caller-chosen deployment. The exact-set comparison below refuses a
    # Request that still carries one.
    "HK_STAGING_DEPLOY": set(),
    # The canary carries exactly what VERIFY carries: the five common fields. The
    # candidate image, its sealed package and the expected current image come from
    # the Command Center's own root-owned canary authority, so there is no field
    # here a request could use to steer one.
    "HK_STAGING_CANARY": set(),
    # A rollback carries the five common fields too, and no more. The deployment to undo
    # is the newest one the Bridge published -- its own record of its own act -- so there
    # is no field here a request could use to choose a target, an image or a service.
    "HK_STAGING_ROLLBACK": set(),
    # The platform probe carries nothing beyond the five common fields. Until
    # this entry existed the projector refused a real CONTROL_PLANE_HEALTH
    # Request as request_action_unknown and reported it REQUEST_UNREADABLE,
    # which read as "chat asked for something it may not ask for" when in fact
    # the platform's own producer had asked correctly.
    "CONTROL_PLANE_HEALTH": set(),
}

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RELEASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
INSTANCE_RE = re.compile(r"^(?:i[-Zz]?)?([0-9a-z]{16,20})[Zz]?$")

# Anything that would make the derived document machine-specific.
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\]|/home/|/Users/|/var/folders/|AppData)")


def normalize_instance(value):
    """Map the three observed spellings of one Alibaba instance id to one form.

    ``i-j6ccs8t04f1p4d8pe69z`` (workbench), ``iZj6ccs8t04f1p4d8pe69zZ`` (uname
    nodename inside the guest) and the bare ``j6ccs8t04f1p4d8pe69z`` all denote
    the same machine, so liveness can be bound to the runtime host.
    """
    if not isinstance(value, str):
        return None
    match = INSTANCE_RE.fullmatch(value.strip())
    return "i-" + match.group(1) if match else None


LIFECYCLE_REQUEST = {"REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED",
                     "REQUEST_DUPLICATE", "REQUEST_REPLAY_REJECTED", "UNKNOWN"}
LIFECYCLE_TASK = {"TASK_SIGNED", "TASK_PUBLISHED", "HK_AGENT_PICKED_UP", "EXECUTION_STARTED",
                  "EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED", "COMPLETE", "TASK_EXPIRED",
                  "TASK_NOT_PICKED_UP", "EXECUTION_FAILED", "EVIDENCE_INVALID",
                  "EVIDENCE_TIMEOUT", "REPLAY_REJECTED", "POLICY_HOLD"}

# ---- CC V1-05: Bridge Request facts -------------------------------------- #
# The closed Request fact vocabulary, exported read-only from the Bridge by
# control-plane/command-center-request-visibility-v1. A Request fact says what
# the Bridge did with a Request; it is never a permission.
REQUEST_FACT_KINDS = ("REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED",
                      "REQUEST_DUPLICATE", "REQUEST_REPLAY_REJECTED")
# Highest first. An acceptance outranks every negative, and every negative is a
# negative: a duplicate or a replay may never be read as a success.
REQUEST_FACT_RANK = {"REQUEST_VALIDATED": 4, "REQUEST_DUPLICATE": 3,
                     "REQUEST_REPLAY_REJECTED": 2, "REQUEST_REJECTED": 1,
                     "REQUEST_CREATED": 0}
REQUEST_FACT_CLASSES = {"INVALID_REQUEST", "NOT_ALLOWED", "UNRESOLVABLE", "CONFLICT",
                        "AMBIGUOUS", "DUPLICATE", "REPLAY", "UNCLASSIFIED_REJECT"}
REQUEST_FACT_REASON_ORIGINS = {"BRIDGE_REJECT_TOKEN", "BRIDGE_POLL_STATUS",
                               "BRIDGE_LEDGER_STATE"}
REQUEST_FACT_TIME_SOURCES = {"POLL_JOURNAL", "TASK_ISSUED_AT", "REQUEST_REQUESTED_AT"}
REQUEST_FACT_AUTHORITY_KEYS = ("is_execution_authority", "grants_execution", "can_create_task",
                               "can_sign", "holds_private_key", "may_authorize_retry",
                               "may_authorize_replay", "may_edit_a_request")
REQUEST_FACT_REQUIRED = {"schema_version", "fact_id", "kind", "request_id", "action_id",
                         "environment", "nonce", "semantic_id", "first_observed_at",
                         "time_source", "submission", "source", "reason", "binding", "authority"}
# Facts written before the semantic identity existed are still on the bus and are
# still read: their instant is observed_at and they carry no semantic_id. A fact
# must match exactly one of the two shapes.
LEGACY_REQUEST_FACT_REQUIRED = (REQUEST_FACT_REQUIRED - {"semantic_id", "first_observed_at"}
                                | {"observed_at"})
# What a semantic identity is made of, and therefore what two facts have to agree
# on to be the same business fact. The observation instant, where it came from,
# and which submission it happened to be keyed by are all deliberately excluded.
REQUEST_FACT_IDENTITY_KEYS = ("kind", "request_id", "action_id", "environment", "nonce",
                              "source", "reason", "binding")
REQUEST_FACT_ID_EXCLUDED = ("fact_id", "first_observed_at", "time_source")
REQUEST_FACT_BINDING_KEYS = {"claimed", "task_id", "task_sha256", "task_commit",
                             "proof_required", "proof"}
REQUEST_FACT_REASON_KEYS = {"applicable", "code", "class", "origin", "preserved_verbatim"}
REQUEST_FACT_SOURCE_KEYS = {"repository", "ref", "head_sha", "path", "request_sha256"}
REQUEST_FACT_ID_RE = re.compile(r"^request-fact-[0-9a-f]{32}$")
REQUEST_FACT_PROOF = "TASK_SIGNATURE_AND_DIGEST_PREFIX"
# The Bridge derives a Task identity from sha256(request_id) and the projection
# verifies that link itself rather than believing the fact.
REQUEST_TASK_DIGEST_LINK = 12
REQUEST_FACTS_DIRNAME = "facts"
REQUEST_FACT_INDEX_NAME = "INDEX.json"
# The closed reasons a Request did not become a Task.
#
# NOT_SETTLED_BY_BRIDGE and NO_BRIDGE_FACT_OBSERVED are separate states on
# purpose. They used to be one: the exporter never minted REQUEST_CREATED, so a
# Request the Bridge had spoken about but not settled was indistinguishable from
# one no Bridge record mentioned at all. Now that the in-flight state is reported
# as a fact, the two answers stay apart -- "the Bridge is still working on it" is
# not the same answer as "nothing was ever observed".
REQUEST_FATE_STATES = ("BECAME_A_TASK", "ACCEPTANCE_CLAIMED_BUT_UNPROVEN", "REFUSED",
                       "DUPLICATE_REQUEST_ID", "REPLAYED_SUBMISSION",
                       "NOT_SETTLED_BY_BRIDGE",
                       "NO_BRIDGE_FACT_OBSERVED", "REQUEST_NOT_ON_THE_BUS")
REQUEST_FATE_BY_KIND = {"REQUEST_VALIDATED": "BECAME_A_TASK",
                        "REQUEST_REJECTED": "REFUSED",
                        "REQUEST_DUPLICATE": "DUPLICATE_REQUEST_ID",
                        "REQUEST_REPLAY_REJECTED": "REPLAYED_SUBMISSION",
                        "REQUEST_CREATED": "NOT_SETTLED_BY_BRIDGE"}

# ---- CC V1-06: the read-only Deploy Readiness verdict --------------------- #
# A separate component answers "can we deploy now, and why not" from the derived
# state plus an optional operator-supplied bundle of live-host facts. This
# projection only carries the verdict it produced; it never evaluates readiness
# itself and it never turns a verdict into an authorisation.
DEPLOY_READINESS_CONTRACT = "DEPLOY_READINESS_V1"
DEPLOY_READINESS_DOCUMENT = ("control-plane/command-center-deploy-readiness-v1/"
                             "DEPLOY_READINESS.json")
DEPLOY_READY_VALUES = ("YES", "NO", "UNKNOWN")
DEPLOY_READINESS_GATES = ("APPROVED_CANDIDATE", "SOURCE_BINDING", "PACKAGE_BINDING",
                          "DEPLOYMENT_PLAN", "HUMAN_APPROVAL", "TEST_PR", "VERIFY",
                          "CURRENT_RUNTIME", "LIVE_DEPLOY_MODE", "DEPLOYMENT_AUTHORIZATION",
                          "CANARY", "BRIDGE_ACCEPTANCE")
# RELEASE_GATES is deliberately absent: the four product-release declarations were
# removed from the deploy contract on 2026-09-17, so an evaluator that still reported
# one would be reporting on product acceptance rather than deployability. The fact one
# of them named is now the sealed TEST_PR, which the deploy gate checks.
# The evaluator has no advisory gates left either: treating CANARY and RELEASE_GATES as
# advisory let it report YES while the live Bridge would deterministically refuse
# the same plan. Every gate blocks. If the evaluator ever reintroduces an advisory
# gate this tuple is what has to move with it, and DeployReadinessContractTests
# reads the evaluator's own source and fails until it does.
DEPLOY_READINESS_ADVISORY_GATES = ()
DEPLOY_READINESS_MANDATORY = DEPLOY_READINESS_GATES
DEPLOY_READINESS_GATE_STATES = ("PASS", "FAIL", "UNKNOWN")
# The verdict block may carry exactly these boundary flags, all false except the
# one that says it only reads what it was handed.
DEPLOY_READINESS_BOUNDARY = {
    "is_execution_authority": False, "can_create_task": False, "can_publish_task": False,
    "can_grant_the_deployment_authorization": False, "holds_private_key": False,
    "signs_anything": False,
    "accepts_caller_supplied_parameters": False, "touches_production": False,
    "may_read_live_command_center_state": True, "is_a_deploy_approval": False,
}


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value):
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp_not_string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive_timestamp")
    return parsed.astimezone(dt.timezone.utc)


def candidate_digest_binding(task, evidence):
    """Whether the Evidence names the candidate its Task named -- CCV1-85 (WP-4A).

    A DEPLOY Task under the current contract states the digest of the candidate it is
    about, and the executor that ran it reports back the digest it loaded and recomputed
    from the candidate fact. The Command Center cannot recompute that value itself -- the
    digest has one implementation and it belongs to candidate admission -- but it can
    refuse the contradiction, which is the part that keeps the plan, the Task and the
    Evidence from drifting apart as three separate claims.

    Legacy is keyed on the **Task**, not on the Evidence. A historical DEPLOY Task
    predates the field entirely, so its Evidence is read without one -- that is
    `LEGACY_EVIDENCE_READ_COMPAT`, and it is bounded by the Task's own contract rather
    than by a list of agent versions that would have to be maintained forever. A Task
    that states a digest, and Evidence that omits or contradicts one, is not a legacy
    record: it is a disagreement, and it is refused.
    """
    if task.get("action_id") != "HK_STAGING_DEPLOY":
        return True
    parameters = task.get("parameters")
    claimed = parameters.get("candidate_contract_sha256") if isinstance(parameters, dict) else None
    if claimed is None:
        return True
    stated = evidence.get("candidate_contract_sha256")
    return (isinstance(stated, str) and stated == claimed
            and SHA256_RE.fullmatch(stated) is not None)


def assertion(state, value, reason, evidence=None):
    if state == STATE_UNKNOWN:
        value = None
    return {"state": state, "value": value, "reason": reason,
            "evidence": sorted({e for e in (evidence or []) if e})}


def unknown(reason, evidence=None):
    return assertion(STATE_UNKNOWN, None, reason, evidence)


def read_json(path):
    raw = pathlib.Path(path).read_bytes()
    return json.loads(raw.decode("utf-8"))


# --------------------------------------------------------------------------- #
# signature verification — two separate identities
# --------------------------------------------------------------------------- #
class IdentityContract:
    """The published verifier identity contract (VERIFIER_IDENTITIES_V1).

    The contract pins one Ed25519 fingerprint per role. A supplied key is trusted
    only when its fingerprint equals that pin, so "the key loaded" and "the key is
    the published identity" stop being the same claim.

    A contract that is missing, unreadable, malformed or that publishes one key for
    both roles resolves nothing, and an unresolvable pin is fail-closed.
    """

    def __init__(self, path):
        self.source = str(path) if path else None
        self.available = False
        self.reason = None
        self.by_role = {}
        self.name = None
        # The reported location is repository-relative, so a caller-supplied
        # absolute path can never leak a workstation path into the projection.
        try:
            published = (pathlib.Path(self.source).resolve()
                         == default_identity_contract_path().resolve())
        except Exception:  # noqa: BLE001
            published = False
        self.published = published
        self.reported_path = (IDENTITY_CONTRACT_RELPATH if published
                              else "<caller-supplied contract>")
        if not self.source:
            self.reason = "no identity contract was supplied"
            return
        try:
            document = read_json(self.source)
        except Exception as exc:  # noqa: BLE001
            self.reason = "identity contract unreadable: %s" % type(exc).__name__
            return
        if not isinstance(document, dict) or document.get("contract") != IDENTITY_CONTRACT_NAME:
            self.reason = "not a %s contract" % IDENTITY_CONTRACT_NAME
            return
        entries = document.get("identities")
        if not isinstance(entries, list) or not entries:
            self.reason = "identity contract carries no identities"
            return
        for entry in entries:
            if isinstance(entry, dict) and entry.get("role") in (ROLE_TASK, ROLE_EVIDENCE):
                self.by_role.setdefault(entry["role"], entry)
        if set(self.by_role) != {ROLE_TASK, ROLE_EVIDENCE}:
            self.reason = ("identity contract must define exactly one TASK and one EVIDENCE "
                           "identity")
            self.by_role = {}
            return
        task_pin = self.by_role[ROLE_TASK].get("public_key_ssh_sha256")
        evidence_pin = self.by_role[ROLE_EVIDENCE].get("public_key_ssh_sha256")
        if not task_pin or not evidence_pin:
            self.reason = "identity contract does not pin a fingerprint for both roles"
            self.by_role = {}
            return
        if task_pin == evidence_pin:
            self.reason = "identity contract publishes one key for both roles"
            self.by_role = {}
            return
        self.name = document.get("contract")
        self.available = True

    def expected(self, role):
        entry = self.by_role.get(role)
        if not entry:
            return None
        return {"identity_id": entry.get("identity_id"),
                "display_name": entry.get("display_name"),
                "encoding": entry.get("signature_encoding"),
                "ssh_sha256": entry.get("public_key_ssh_sha256"),
                "raw_sha256": entry.get("public_key_raw_sha256"),
                "public_key_path": entry.get("public_key_path"),
                "host_source_path": entry.get("host_source_path"),
                "status": entry.get("status")}

    def describe(self):
        return {"contract": IDENTITY_CONTRACT_NAME,
                "path": self.reported_path,
                "is_the_published_contract": self.published,
                "state": "LOADED" if self.available else "UNRESOLVED",
                "reason": self.reason,
                "publishes_private_keys": False}


class Verifier:
    """One Ed25519 verifier identity.

    Reports NOT_PERFORMED rather than assuming success when no key is supplied.
    ``encoding`` is carried per artifact: tasks are hex, evidence is base64.

    ``expected`` is the published identity pin from IdentityContract. It is what
    separates the four cases the projection must never confuse:

      no key supplied                 MISSING_KEY         fail-closed
      key supplied, does not load     KEY_UNREADABLE      fail-closed
      key loaded, pin does not match  IDENTITY_MISMATCH   fail-closed
      no usable pin                   IDENTITY_UNRESOLVED fail-closed
      key loaded and pin matches      BOUND               PROVEN possible
    """

    def __init__(self, key_path, identity, encoding, expected=None):
        self.identity = identity
        self.encoding = encoding
        self.expected = expected or None
        self.key = None
        self.fingerprint = None
        self.ssh_fingerprint = None
        self.key_sha256 = None
        self.available = False
        self.disabled = False
        self.identity_id = (self.expected or {}).get("identity_id")
        if not key_path:
            self.binding = BINDING_MISSING_KEY
            self.binding_reason = "no key was supplied, so no signature can be checked"
            return
        if not self.expected or not self.expected.get("ssh_sha256"):
            self.binding = BINDING_IDENTITY_UNRESOLVED
            self.binding_reason = ("no published identity pin is available to bind this key to, "
                                   "so a valid signature would still not establish the identity")
        else:
            self.binding = None
            self.binding_reason = None
        try:
            from cryptography.hazmat.primitives import serialization
            raw = pathlib.Path(key_path).read_bytes()
            if raw.startswith(b"ssh-"):
                self.key = serialization.load_ssh_public_key(raw)
            else:
                self.key = serialization.load_pem_public_key(raw)
            raw_public = self.key.public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
            self.fingerprint = hashlib.sha256(raw_public).hexdigest()
            # The SSH fingerprint is taken over the ssh wire blob, which is what
            # ssh-keygen and the archived audit files report.
            prefix = b"ssh-ed25519"
            blob = (len(prefix).to_bytes(4, "big") + prefix
                    + len(raw_public).to_bytes(4, "big") + raw_public)
            self.ssh_fingerprint = "SHA256:" + base64.b64encode(
                hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
            self.key_sha256 = self.fingerprint
            self.available = True
        except Exception as exc:  # noqa: BLE001 - fail closed, report why
            self.key = None
            self.available = False
            self.fingerprint = "unavailable:%s" % type(exc).__name__
            self.binding = BINDING_KEY_UNREADABLE
            self.binding_reason = "the key file could not be loaded as an Ed25519 public key"
            return
        if self.binding is None:
            if self.ssh_fingerprint == self.expected.get("ssh_sha256"):
                self.binding = BINDING_BOUND
                self.binding_reason = None
            else:
                self.binding = BINDING_IDENTITY_MISMATCH
                self.binding_reason = ("the supplied key is not the published identity: expected "
                                       "%s, observed %s" % (self.expected.get("ssh_sha256"),
                                                            self.ssh_fingerprint))

    @property
    def fail_closed(self):
        return self.binding in FAIL_CLOSED_BINDINGS

    def disabled_copy(self):
        """The same identity reported, but with no ability to claim verification."""
        clone = Verifier(None, self.identity, self.encoding, expected=self.expected)
        clone.binding = self.binding
        clone.binding_reason = self.binding_reason
        clone.ssh_fingerprint = self.ssh_fingerprint
        clone.key_sha256 = self.key_sha256
        clone.fingerprint = self.fingerprint
        clone.disabled = True
        return clone

    def verify(self, obj, encoding=None):
        """Return True / False / None (None = could not be performed)."""
        if not self.available:
            return None
        encoding = encoding or self.encoding
        signature = obj.get("signature")
        if not isinstance(signature, str):
            return False
        try:
            import base64
            if encoding == "hex":
                if not re.fullmatch(r"[0-9a-f]{128}", signature):
                    return False
                raw = bytes.fromhex(signature)
            else:
                raw = base64.b64decode(signature.encode("ascii"), validate=True)
            if len(raw) != 64:
                return False
            # Internal annotations added during normalisation are never part of
            # the signed canonical form.
            unsigned = {k: v for k, v in obj.items()
                        if k != "signature" and not k.startswith("_")}
            self.key.verify(raw, canonical(unsigned))
            return True
        except Exception:  # noqa: BLE001
            return False

    def describe(self):
        return {"identity": self.identity,
                "identity_id": self.identity_id,
                "encoding": self.encoding,
                "key_fingerprint": self.fingerprint,
                "ssh_sha256_fingerprint": self.ssh_fingerprint,
                "expected_ssh_sha256_fingerprint": (self.expected or {}).get("ssh_sha256"),
                "identity_binding": self.binding,
                "identity_binding_reason": self.binding_reason,
                "signature_verification": "PERFORMED" if self.available else "NOT_PERFORMED"}


def separated(task_verifier, evidence_verifier, loaded):
    """Enforce that the two verifier identities are genuinely different keys."""
    if not (task_verifier.available and evidence_verifier.available):
        return True
    if task_verifier.fingerprint == evidence_verifier.fingerprint:
        loaded.anomaly("VERIFIER_IDENTITY_COLLISION",
                       "the task verifier and the evidence verifier resolve to the same public "
                       "key; the two signing identities must be distinct, so no PROVEN claim is "
                       "made in this run", task_verifier.fingerprint)
        return False
    return True


def bind_identities(task_verifier, evidence_verifier, loaded):
    """Fail closed on any verifier that is not the published identity.

    A verifier whose binding is not BOUND is disabled, so it cannot return True
    and therefore cannot produce PROVEN. The binding itself is still reported, so
    "wrong key" is never quietly downgraded to "no key".
    """
    task_ok = task_verifier.binding == BINDING_BOUND
    evidence_ok = evidence_verifier.binding == BINDING_BOUND

    for role, verifier in (("task", task_verifier), ("evidence", evidence_verifier)):
        if verifier.binding == BINDING_IDENTITY_MISMATCH:
            loaded.anomaly("VERIFIER_IDENTITY_MISMATCH",
                           "the %s verifier key is not the published identity: %s"
                           % (role, verifier.binding_reason), verifier.ssh_fingerprint)
        elif verifier.binding == BINDING_IDENTITY_UNRESOLVED:
            loaded.anomaly("VERIFIER_IDENTITY_UNRESOLVED",
                           "the %s verifier could not be bound to a published identity: %s"
                           % (role, verifier.binding_reason))
        elif verifier.binding == BINDING_KEY_UNREADABLE:
            loaded.anomaly("VERIFIER_KEY_UNREADABLE",
                           "the %s verifier key could not be loaded" % role)
    return task_ok, evidence_ok


# --------------------------------------------------------------------------- #
# schema validation
# --------------------------------------------------------------------------- #
class Malformed(Exception):
    pass


def validate_task(task):
    """Validate the immutable core strictly; report parameter-contract drift."""
    if not isinstance(task, dict) or set(task) != TASK_REQUIRED:
        raise Malformed("task_fields")
    if task["schema_version"] != "1":
        raise Malformed("task_schema_version")
    if not TASK_ID_RE.fullmatch(task["task_id"] or ""):
        raise Malformed("task_id")
    if not NONCE_RE.fullmatch(task["nonce"] or ""):
        raise Malformed("task_nonce")
    if task["authority"] != "GO-COMMAND-CENTER":
        raise Malformed("task_authority")
    action = task["action_id"]
    if action not in ACTION_PARAMETERS:
        raise Malformed("task_action_unknown")
    if task["environment"] != "HK-STAGING-01":
        raise Malformed("task_environment")
    parse_time(task["issued_at"])
    parse_time(task["expires_at"])
    if not isinstance(task["parameters"], dict):
        raise Malformed("task_parameters")
    # Historical Tasks may predate the current parameter contract. They stay in
    # the projection with an explicit drift marker instead of being dropped, so
    # the state is never silently incomplete.
    current = set(task["parameters"]) == ACTION_PARAMETERS[action]
    superseded = set(task["parameters"]) in SUPERSEDED_PARAMETERS.get(action, ())
    task["_parameter_contract"] = ("CURRENT" if current
                                   else "SUPERSEDED" if superseded
                                   else "LEGACY_OR_UNKNOWN")
    if current and action == "HK_STAGING_TEST_PR":
        source = task["parameters"]["source"]
        if (task["parameters"]["builder_profile"] != "go-application-python-v1"
                or not isinstance(source, dict)
                or set(source) != {"repository", "pr_number", "commit_sha"}
                or not COMMIT_RE.fullmatch(source["commit_sha"])):
            raise Malformed("task_test_pr_source")
    if current and action == "HK_STAGING_DEPLOY" \
            and not IMAGE_RE.fullmatch(task["parameters"]["candidate_image_id"]):
        raise Malformed("task_candidate_image")
    return task


def normalize_evidence(evidence):
    """Normalise the two published Evidence generations onto one shape."""
    if not isinstance(evidence, dict):
        raise Malformed("evidence_not_object")
    generation = "v2" if "completed_at" in evidence else ("v1" if "finished_at" in evidence else None)
    if generation is None:
        raise Malformed("evidence_timestamp")
    missing = EVIDENCE_COMMON - set(evidence)
    if missing:
        raise Malformed("evidence_fields")
    if evidence["schema_version"] != "1":
        raise Malformed("evidence_schema_version")
    if evidence["action_id"] not in ACTION_PARAMETERS:
        raise Malformed("evidence_action_unknown")
    parse_time(evidence["started_at"])
    terminal = evidence["completed_at"] if generation == "v2" else evidence["finished_at"]
    parse_time(terminal)
    out = dict(evidence)
    out["_generation"] = generation
    out["_completed_at"] = terminal
    return out


def failure_detail(evidence):
    """The closed failure block of a non-success record, plus the contract's own
    answer to "does this authorize a retry".

    The artifact is never trusted on that point.  A failure record authorizes
    nothing, so the projection states ``retry_permitted`` false from the contract
    and reports separately what the artifact claimed; a claim to the contrary is
    recorded and given no effect.
    """
    block = evidence.get("failure")
    detail = {"retry_permitted": False,
              "replay_authorized": False,
              "authorizes_any_action": False,
              "artifact_claimed_retry_permitted": bool(evidence.get("retry_permitted")),
              "artifact_claimed_replay_authorized": bool(evidence.get("replay_authorized")),
              "artifact_claimed_authorizes_any_action": bool(evidence.get("authorizes_any_action"))}
    if isinstance(block, dict):
        for key in ("kind", "stage", "reason_code"):
            if isinstance(block.get(key), str):
                detail[key] = block[key]
        if isinstance(block.get("attempt_number"), int):
            detail["attempt_number"] = block["attempt_number"]
        for key in ("attempt_budget_exhausted", "execution_attempted"):
            if isinstance(block.get(key), bool):
                detail[key] = block[key]
    return detail


def validate_request(request):
    if not isinstance(request, dict):
        raise Malformed("request_not_object")
    action = request.get("action_id")
    if action not in REQUEST_EXTRA_FIELDS:
        raise Malformed("request_action_unknown")
    if set(request) != REQUEST_REQUIRED | REQUEST_EXTRA_FIELDS[action]:
        raise Malformed("request_fields")
    if request["schema_version"] != "1":
        raise Malformed("request_schema_version")
    if not isinstance(request["request_id"], str) or not re.fullmatch(
            r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$", request["request_id"]):
        raise Malformed("request_id")
    if request["environment"] != "HK-STAGING-01":
        raise Malformed("request_environment")
    parse_time(request["requested_at"])
    if action == "HK_STAGING_TEST_PR" and not re.fullmatch(r"^[1-9][0-9]{0,8}$", request["pr_number"]):
        raise Malformed("request_pr_number")
    return request


def validate_request_fact(payload):
    """A Bridge Request fact, validated fail-closed.

    An untrusted fact must not be able to change an answer, so anything that is
    structurally wrong is refused outright and anything that claims authority is
    refused as a lie about what a fact is. Recomputing the fact id is what makes
    a hand-edited fact detectable: the id covers the whole body.
    """
    if not isinstance(payload, dict):
        raise Malformed("request_fact_not_object")
    legacy = "semantic_id" not in payload
    if set(payload) != (LEGACY_REQUEST_FACT_REQUIRED if legacy else REQUEST_FACT_REQUIRED):
        raise Malformed("request_fact_fields")
    if not isinstance(payload["fact_id"], str) or not REQUEST_FACT_ID_RE.fullmatch(payload["fact_id"]):
        raise Malformed("request_fact_id")
    identity = digest({name: payload[name] for name in REQUEST_FACT_IDENTITY_KEYS})
    if legacy:
        # Its id covers the whole body, and its identity is derived here so the
        # two shapes can be deduplicated against each other.
        recomputed = "request-fact-" + digest({k: v for k, v in payload.items()
                                              if k != "fact_id"})[:32]
    else:
        recomputed = "request-fact-" + digest(
            {k: v for k, v in payload.items() if k not in REQUEST_FACT_ID_EXCLUDED})[:32]
    if recomputed != payload["fact_id"]:
        # Checked first because it is the general claim: any edit to the body
        # breaks it, including an edit to a field the identity covers.
        raise Malformed("request_fact_tampered")
    if not legacy and payload["semantic_id"] != identity:
        # The id was recomputed, so the body is self-consistent, and yet the
        # identity it declares is not the identity of what it says. That is a
        # forged identity rather than a forged body, and it is refused as such.
        raise Malformed("request_fact_semantic_id")
    if payload["schema_version"] != "1":
        raise Malformed("request_fact_schema_version")
    if payload["kind"] not in REQUEST_FACT_KINDS:
        raise Malformed("request_fact_kind")
    if not isinstance(payload["request_id"], str) or not re.fullmatch(
            r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$", payload["request_id"]):
        raise Malformed("request_fact_request_id")
    if payload["action_id"] not in REQUEST_EXTRA_FIELDS:
        raise Malformed("request_fact_action")
    if payload["environment"] != "HK-STAGING-01":
        raise Malformed("request_fact_environment")
    if payload["nonce"] is not None and not isinstance(payload["nonce"], str):
        raise Malformed("request_fact_nonce")
    instant = payload["first_observed_at"] if not legacy else payload["observed_at"]
    parse_time(instant)
    if payload["time_source"] not in REQUEST_FACT_TIME_SOURCES:
        raise Malformed("request_fact_time_source")
    submission = payload["submission"]
    if not isinstance(submission, dict) or set(submission) != {"pr_number", "head_sha",
                                                               "submission_key"}:
        raise Malformed("request_fact_submission")
    if (not re.fullmatch(r"^[1-9][0-9]{0,8}$", str(submission["pr_number"]))
            or not COMMIT_RE.fullmatch(str(submission["head_sha"]))
            or submission["submission_key"] != "%s:%s" % (submission["pr_number"],
                                                           submission["head_sha"])):
        raise Malformed("request_fact_submission")
    source = payload["source"]
    if source is not None:
        if not isinstance(source, dict) or set(source) != REQUEST_FACT_SOURCE_KEYS:
            raise Malformed("request_fact_source")
        if not isinstance(source["path"], str) or not source["path"].startswith("requests/"):
            raise Malformed("request_fact_source")
    reason = payload["reason"]
    if not isinstance(reason, dict) or set(reason) != REQUEST_FACT_REASON_KEYS:
        raise Malformed("request_fact_reason")
    if not isinstance(reason["applicable"], bool):
        raise Malformed("request_fact_reason")
    if reason["applicable"]:
        if (not isinstance(reason["code"], str) or not reason["code"]
                or reason["class"] not in REQUEST_FACT_CLASSES
                or reason["origin"] not in REQUEST_FACT_REASON_ORIGINS
                or reason["preserved_verbatim"] is not True):
            raise Malformed("request_fact_reason")
    elif (reason["code"], reason["class"], reason["origin"]) != (None, None, None):
        raise Malformed("request_fact_reason")
    binding = payload["binding"]
    if not isinstance(binding, dict) or set(binding) - {"note"} != REQUEST_FACT_BINDING_KEYS:
        raise Malformed("request_fact_binding")
    if not isinstance(binding["claimed"], bool) or not isinstance(binding["proof_required"], bool):
        raise Malformed("request_fact_binding")
    if binding["proof"] not in (REQUEST_FACT_PROOF, "NOT_APPLICABLE"):
        raise Malformed("request_fact_binding")
    if payload["kind"] == "REQUEST_VALIDATED":
        # The only positive fact. It must declare that it needs proof and must
        # name the Task it claims, or it is refused rather than believed.
        if (binding["claimed"] is not True or binding["proof_required"] is not True
                or binding["proof"] != REQUEST_FACT_PROOF
                or not isinstance(binding["task_id"], str) or not binding["task_id"]):
            raise Malformed("request_fact_binding")
    elif (binding["claimed"] is not False or binding["proof_required"] is not False
          or binding["proof"] != "NOT_APPLICABLE" or binding["task_id"] is not None):
        raise Malformed("request_fact_binding")
    authority = payload["authority"]
    if not isinstance(authority, dict) or set(authority) != set(REQUEST_FACT_AUTHORITY_KEYS):
        raise Malformed("request_fact_authority_fields")
    if any(value is not False for value in authority.values()):
        # A fact that claims any authority is not a fact.
        raise Malformed("request_fact_claims_authority")
    # One shape for every consumer below: the validated fact always carries
    # first_observed_at and the identity it will be deduplicated by, and says
    # which rule its id was checked under, so a legacy fact is visibly legacy
    # rather than silently indistinguishable.
    payload.pop("observed_at", None)
    payload["first_observed_at"] = instant
    payload["_semantic_id"] = identity
    payload["_identity_rule"] = "LEGACY_TIMESTAMP" if legacy else "SEMANTIC"
    return payload


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
class Loaded:
    def __init__(self):
        self.tasks = []            # (file name, task)
        self.evidence = []         # (file name, evidence)
        self.requests = []         # (ref, head_sha, file name, request)
        self.request_facts = []    # validated Bridge Request facts, one per semantic identity
        self.request_facts_collapsed = 0   # observations the semantic dedup folded away
        self.request_fact_rules = {}       # identity rule -> how many facts arrived under it
        self.request_fact_index = None   # the exporter's submission-level index, if supplied
        self.deploy_readiness = None     # the evaluator's verdict, if supplied
        self.anomalies = []        # {kind, detail, ref}

    def anomaly(self, kind, detail, ref=None):
        self.anomalies.append({"kind": kind, "detail": detail, "ref": ref})


def load_tasks(root, loaded):
    folder = pathlib.Path(root) / "tasks"
    if not folder.is_dir():
        loaded.anomaly("TASKS_DIRECTORY_MISSING", "%s/tasks" % TASKS_REPOSITORY)
        return
    for path in sorted(folder.glob("*.json")):
        try:
            loaded.tasks.append((path.name, validate_task(read_json(path))))
        except (Malformed, ValueError, OSError, UnicodeError) as exc:
            loaded.anomaly("TASK_UNREADABLE", "%s" % exc, path.name)


def load_evidence(root, loaded):
    folder = pathlib.Path(root) / "evidence"
    if not folder.is_dir():
        loaded.anomaly("EVIDENCE_DIRECTORY_MISSING", "%s/evidence" % EVIDENCE_REPOSITORY)
        return
    for path in sorted(folder.glob("*.json")):
        try:
            loaded.evidence.append((path.name, normalize_evidence(read_json(path))))
        except (Malformed, ValueError, OSError, UnicodeError) as exc:
            loaded.anomaly("EVIDENCE_UNREADABLE", "%s" % exc, path.name)


def load_requests(root, loaded):
    if not root:
        return
    folder = pathlib.Path(root)
    if not folder.is_dir():
        loaded.anomaly("REQUESTS_DIRECTORY_MISSING",
                       "collected Request files were not supplied")
        return
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            payload = read_json(path)
        except (OSError, UnicodeError, ValueError) as exc:
            loaded.anomaly("REQUEST_UNREADABLE", "%s" % exc, path.name)
            continue
        ref, head = None, None
        if isinstance(payload, dict) and "request" in payload:
            ref = payload.get("ref")
            head = payload.get("head_sha")
            payload = payload["request"]
        try:
            loaded.requests.append((ref, head, path.name, validate_request(payload)))
        except (Malformed, ValueError) as exc:
            loaded.anomaly("REQUEST_UNREADABLE", "%s" % exc, path.name)


def dedup_request_facts(facts):
    """One fact per semantic identity, chosen deterministically.

    Facts written before the semantic identity existed are still on the bus, so an
    outcome observed across that change has both shapes present and the store has
    one file per observation of it. They are one business fact, not several: the
    projection keeps the earliest observation of each identity, and reports how
    many it collapsed so the reduction is visible instead of silent. Nothing is
    deleted -- the bus still carries every observation as a record.
    """
    grouped = {}
    for fact in facts:
        grouped.setdefault(fact["_semantic_id"], []).append(fact)
    kept, collapsed, rules = [], 0, {}
    for identity in sorted(grouped):
        members = sorted(grouped[identity],
                         key=lambda f: (f["first_observed_at"], f["fact_id"]))
        chosen = dict(members[0])
        chosen["_observations_on_bus"] = len(members)
        chosen["_collapsed_fact_ids"] = [member["fact_id"] for member in members[1:]]
        chosen["_identity_rules"] = sorted({member["_identity_rule"] for member in members})
        collapsed += len(members) - 1
        for rule in chosen["_identity_rules"]:
            rules[rule] = rules.get(rule, 0) + 1
        kept.append(chosen)
    return kept, collapsed, rules


def load_request_facts(root, loaded):
    """Read the exported Bridge facts. Nothing here is trusted on its own word.

    The folder is the export root produced read-only by
    ``control-plane/command-center-request-visibility-v1``. A fact that is
    malformed, tampered with, or that claims any authority is refused and given
    no effect; the facts/INDEX.json is optional and only ever adds
    submission-level observations, which cannot elevate anything.
    """
    if not root:
        return
    folder = pathlib.Path(root)
    if not folder.is_dir():
        loaded.anomaly("REQUEST_FACTS_DIRECTORY_MISSING",
                       "collected Bridge Request facts were not supplied")
        return
    facts = folder / REQUEST_FACTS_DIRNAME
    if not facts.is_dir():
        loaded.anomaly("REQUEST_FACTS_DIRECTORY_MISSING", "%s/facts" % root)
    else:
        for path in sorted(facts.glob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                loaded.request_facts.append(validate_request_fact(read_json(path)))
            except (Malformed, ValueError, OSError, UnicodeError) as exc:
                loaded.anomaly("REQUEST_FACT_UNREADABLE", "%s" % exc, path.name)
        loaded.request_facts, loaded.request_facts_collapsed, loaded.request_fact_rules = (
            dedup_request_facts(loaded.request_facts))
    index_path = folder / REQUEST_FACT_INDEX_NAME
    if index_path.is_file():
        try:
            index = read_json(index_path)
            submissions = index["submissions"] if isinstance(index, dict) else None
            if not isinstance(submissions, list):
                raise Malformed("request_fact_index_submissions")
            cleaned = []
            for item in submissions:
                if (isinstance(item, dict) and isinstance(item.get("submission_key"), str)
                        and isinstance(item.get("bridge_status"), str)
                        and isinstance(item.get("fact_emitted"), bool)
                        and (item.get("reason") is None or isinstance(item.get("reason"), str))
                        and (item.get("reason_class") is None
                             or item["reason_class"] in REQUEST_FACT_CLASSES)):
                    cleaned.append({"submission_key": item["submission_key"],
                                    "pr_number": item.get("pr_number"),
                                    "head_sha": item.get("head_sha"),
                                    "bridge_status": item["bridge_status"],
                                    "reason_code": item.get("reason"),
                                    "reason_class": item.get("reason_class"),
                                    "fact_emitted": item["fact_emitted"]})
                else:
                    loaded.anomaly("REQUEST_FACT_INDEX_UNREADABLE",
                                   "submission entry is not usable", index_path.name)
            loaded.request_fact_index = {"submissions": sorted(
                cleaned, key=lambda s: s["submission_key"])}
        except (Malformed, ValueError, OSError, UnicodeError, KeyError) as exc:
            loaded.anomaly("REQUEST_FACT_INDEX_UNREADABLE", "%s" % exc, index_path.name)


def load_deploy_readiness(path, loaded):
    """Read the verdict the read-only evaluator produced, fail-closed.

    Only whitelisted fields are carried across, and a verdict that claims any
    authority is refused: a readiness document is an observation, and one that
    says otherwise is not a document this projection will quote.
    """
    if not path:
        return
    try:
        document = read_json(path)
        if not isinstance(document, dict) or document.get("contract") != DEPLOY_READINESS_CONTRACT:
            raise Malformed("deploy_readiness_contract")
        verdict = document.get("verdict")
        if not isinstance(verdict, dict) or verdict.get("deploy_ready") not in DEPLOY_READY_VALUES:
            raise Malformed("deploy_readiness_verdict")
        boundary = document.get("authority_boundary")
        if not isinstance(boundary, dict) or set(boundary) != set(DEPLOY_READINESS_BOUNDARY):
            raise Malformed("deploy_readiness_authority_fields")
        for key, expected in DEPLOY_READINESS_BOUNDARY.items():
            if boundary[key] is not expected:
                # A readiness verdict that claims it may deploy something is not
                # a readiness verdict.
                raise Malformed("deploy_readiness_claims_authority:%s" % key)
        gates = []
        for entry in document.get("gates") or []:
            if (not isinstance(entry, dict) or entry.get("gate") not in DEPLOY_READINESS_GATES
                    or entry.get("state") not in DEPLOY_READINESS_GATE_STATES):
                raise Malformed("deploy_readiness_gate")
            gates.append({"gate": entry["gate"], "mandatory": bool(entry.get("mandatory")),
                          "state": entry["state"], "reason": str(entry.get("reason") or "")})
        if {g["gate"] for g in gates} != set(DEPLOY_READINESS_GATES):
            raise Malformed("deploy_readiness_gate_set")
        loaded.deploy_readiness = {
            "deploy_ready": verdict["deploy_ready"],
            "reason": str(verdict.get("reason") or ""),
            "as_of": document.get("as_of"),
            "failed": [str(name) for name in verdict.get("failed") or []],
            "unknown": [str(name) for name in verdict.get("unknown") or []],
            "blocking_gates": [str(entry.get("gate")) for entry in
                               (document.get("blocking_reasons") or []) if isinstance(entry, dict)],
            "gates": sorted(gates, key=lambda g: DEPLOY_READINESS_GATES.index(g["gate"])),
        }
    except (Malformed, ValueError, OSError, UnicodeError) as exc:
        loaded.anomaly("DEPLOY_READINESS_UNREADABLE", "%s" % exc, pathlib.Path(path).name)


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def request_binding_context(loaded, tasks, task_verifier):
    """What the projection knows about the Tasks a Request could have produced.

    The Bridge names a Task; this is the independent side of the check, built
    from the signed Tasks actually on the control bus and from whether the
    Command Center task verifier really is the published identity.
    """
    context = {}
    for name, task in loaded.tasks:
        body = {k: v for k, v in task.items() if not k.startswith("_")}
        entry = context.setdefault(task["task_id"], {"ambiguous": False})
        if entry.get("task_sha256") not in (None, digest(body)):
            # One Task identity, two different signed bodies: no single binding
            # can be established, so the binding is refused rather than picked.
            entry["ambiguous"] = True
        entry["task_sha256"] = digest(body)
        entry["action_id"] = task["action_id"]
        entry["source_path"] = "tasks/" + name
    for record in tasks:
        entry = context.get(record["task_id"])
        if entry is not None:
            entry["signature_verified"] = record["task_signature_verified"]
            entry["lifecycle"] = record["lifecycle"]
    for entry in context.values():
        entry["verifier_binding"] = task_verifier.binding
    return context


def evaluate_request_binding(fact, context):
    """Corroborate an acceptance claim against the signed Task. Never assume it.

    An acceptance means Command Center signed a Task for this Request, so the
    proof needs both halves: the named Task's own signature must verify, and the
    verifier that checked it must be the identity published in the contract. A
    key that merely loads is not the right key, and no key at all proves nothing.

    Returns (proof_state, detail). Only REQUEST_FACT_PROOF lets a Request be
    reported as validated; anything else keeps it at REQUEST_CREATED.
    """
    if fact["kind"] != "REQUEST_VALIDATED":
        return "NOT_APPLICABLE", "this fact is not an acceptance claim"
    task_id = fact["binding"]["task_id"]
    entry = context.get(task_id)
    if entry is None:
        return "NOT_ESTABLISHED", "the Task this fact names is not on the control bus"
    if entry["ambiguous"]:
        return "NOT_ESTABLISHED", "two different signed Tasks share this task_id"
    suffix = hashlib.sha256(fact["request_id"].encode()).hexdigest()[:REQUEST_TASK_DIGEST_LINK]
    if not task_id.endswith("-" + suffix):
        return "NOT_ESTABLISHED", ("the task_id does not carry the digest of this request_id, so "
                                   "this Task did not come from this Request")
    if entry["action_id"] != fact["action_id"]:
        return "NOT_ESTABLISHED", "the named Task performs a different action"
    if fact["binding"]["task_sha256"] != entry["task_sha256"]:
        return "NOT_ESTABLISHED", "the claimed task_sha256 does not describe the Task on the bus"
    if entry.get("verifier_binding") != BINDING_BOUND:
        return "NOT_ESTABLISHED", ("the Command Center task verifier is not bound to the published "
                                   "identity contract, so the signature is not an identity claim")
    if entry.get("signature_verified") is not True:
        return "NOT_ESTABLISHED", ("the named Task's signature did not verify against the published "
                                   "Command Center task identity")
    return REQUEST_FACT_PROOF, "the signed Task exists, carries this request identity and verifies"


def request_records(loaded, binding_context):
    """Project every Request with the strongest fact that can actually be proven.

    Three rules the projection must never break: an acceptance is only reported
    when the signed Task corroborates it; a duplicate or a replay is never a
    success; and a Request with no Bridge fact stays CREATED instead of being
    guessed into an acceptance.
    """
    by_request = {}
    for fact in loaded.request_facts:
        by_request.setdefault(fact["request_id"], []).append(fact)
    for facts in by_request.values():
        facts.sort(key=lambda f: (f["first_observed_at"], f["fact_id"]))

    seen_fact_ids = set()
    out = []
    seen = {}
    for ref, head, source, request in loaded.requests:
        duplicate = request["request_id"] in seen
        if duplicate:
            loaded.anomaly("REQUEST_ID_REUSED", "request_id", request["request_id"])
        seen[request["request_id"]] = True
        action = request["action_id"]
        requestable = action in ENABLED_REQUEST_ACTIONS
        facts = [f for f in by_request.get(request["request_id"], [])
                 if f["action_id"] == action]
        projected, chosen = [], None
        for fact in facts:
            proof, detail = evaluate_request_binding(fact, binding_context)
            seen_fact_ids.add(fact["fact_id"])
            projected.append({"fact_id": fact["fact_id"], "kind": fact["kind"],
                              "first_observed_at": fact["first_observed_at"],
                              "identity_rule": fact["_identity_rule"],
                              "observations_on_bus": fact["_observations_on_bus"],
                              "identity_rules": fact["_identity_rules"],
                              "collapsed_fact_ids": fact["_collapsed_fact_ids"],
                              "time_source": fact["time_source"],
                              "submission": fact["submission"],
                              "reason": fact["reason"],
                              "binding": {"task_id": fact["binding"]["task_id"],
                                          "task_sha256": fact["binding"]["task_sha256"],
                                          "task_commit": fact["binding"]["task_commit"],
                                          "proof_required": fact["binding"]["proof_required"],
                                          "proof_state": proof, "proof_detail": detail},
                              "effective": proof != "NOT_ESTABLISHED"})
            if proof == "NOT_ESTABLISHED":
                loaded.anomaly("REQUEST_BINDING_UNPROVEN", detail, fact["fact_id"])
        for fact in projected:
            if not fact["effective"]:
                continue
            if chosen is None or REQUEST_FACT_RANK[fact["kind"]] > REQUEST_FACT_RANK[chosen["kind"]]:
                chosen = fact
        unproven = [f for f in projected
                    if f["kind"] == "REQUEST_VALIDATED" and not f["effective"]]
        if chosen is None:
            lifecycle, lifecycle_source = "REQUEST_CREATED", "CONTROL_BUS_ONLY"
            if unproven:
                # A claim was made and could not be corroborated. The claim is
                # reported, with the reason it failed, instead of being replaced
                # by a bland "nothing seen".
                binding = dict(unproven[-1]["binding"])
                binding["proof_required"] = True
            else:
                binding = {"task_id": None, "task_sha256": None, "task_commit": None,
                           "proof_required": False, "proof_state": "NOT_APPLICABLE",
                           "proof_detail": ("no Bridge fact has been observed for this Request; its "
                                            "existence on the control bus is all that is established")}
        else:
            lifecycle, lifecycle_source = chosen["kind"], "BRIDGE_FACT"
            binding = chosen["binding"]
        if lifecycle == "REQUEST_VALIDATED":
            fate = {"state": "BECAME_A_TASK", "reason_code": None, "reason_class": None}
        elif unproven and lifecycle == "REQUEST_CREATED":
            fate = {"state": "ACCEPTANCE_CLAIMED_BUT_UNPROVEN",
                    "reason_code": None, "reason_class": None}
        elif chosen is None:
            fate = {"state": "NO_BRIDGE_FACT_OBSERVED", "reason_code": None, "reason_class": None}
        else:
            fate = {"state": REQUEST_FATE_BY_KIND[lifecycle],
                    "reason_code": chosen["reason"]["code"],
                    "reason_class": chosen["reason"]["class"]}
        out.append({
            "schema_version": "1",
            "request_id": request["request_id"],
            "action_id": action,
            "environment": request["environment"],
            "requested_at": request["requested_at"],
            "target": {k: request[k] for k in sorted(set(request) - REQUEST_REQUIRED)},
            "request_sha256": digest(request),
            "source": {"repository": TASKS_REPOSITORY, "ref": ref,
                       "head_sha": head, "path": "requests/" + source},
            "requestable_by_current_channel": requestable,
            "request_source_class": REQUEST_ACTION_SOURCE_CLASS.get(action, "UNKNOWN"),
            "capability_classification": CAPABILITY_CLASSIFICATION.get(action, "UNKNOWN"),
            "holding_execution_authority": False,
            "lifecycle": lifecycle,
            "lifecycle_source": lifecycle_source,
            "lifecycle_note": ("reported from a Bridge fact only when the signed Task corroborates "
                               "an acceptance; otherwise from the Request file alone"),
            "why_not_a_task": fate,
            "binding": binding,
            "facts": projected,
            "duplicate_request_id": duplicate,
        })

    # A fact whose Request was never collected still says something, but it
    # cannot be attached to a Request, so it is reported as UNKNOWN rather than
    # being dropped or attributed to a Request that does not exist.
    for request_id in sorted(by_request):
        if request_id in seen:
            continue
        for fact in by_request[request_id]:
            seen_fact_ids.add(fact["fact_id"])
        loaded.anomaly("REQUEST_FACT_WITHOUT_REQUEST",
                       "a Bridge fact names a Request that is not on the control bus")
        out.append({
            "schema_version": "1",
            "request_id": request_id,
            "action_id": by_request[request_id][0]["action_id"],
            "environment": "HK-STAGING-01",
            "requested_at": None,
            "target": {},
            "request_sha256": None,
            "source": None,
            "requestable_by_current_channel": None,
            "capability_classification": CAPABILITY_CLASSIFICATION.get(
                by_request[request_id][0]["action_id"], "UNKNOWN"),
            "holding_execution_authority": False,
            "lifecycle": "UNKNOWN",
            "lifecycle_source": "BRIDGE_FACT_WITHOUT_REQUEST",
            "lifecycle_note": ("the Bridge spoke about this Request but its Request file was not "
                               "collected, so no control-bus identity exists to bind"),
            "why_not_a_task": {"state": "REQUEST_NOT_ON_THE_BUS", "reason_code": None,
                               "reason_class": None},
            "binding": {"task_id": None, "task_sha256": None, "task_commit": None,
                        "proof_required": False, "proof_state": "NOT_APPLICABLE",
                        "proof_detail": "the Request file was not collected"},
            "facts": [{"fact_id": fact["fact_id"], "kind": fact["kind"],
                       "first_observed_at": fact["first_observed_at"],
                       "time_source": fact["time_source"],
                       "identity_rule": fact["_identity_rule"],
                       "submission": fact["submission"], "reason": fact["reason"],
                       "binding": {"task_id": fact["binding"]["task_id"],
                                   "task_sha256": fact["binding"]["task_sha256"],
                                   "task_commit": fact["binding"]["task_commit"],
                                   "proof_required": fact["binding"]["proof_required"],
                                   "proof_state": ("NOT_APPLICABLE" if fact["kind"] != "REQUEST_VALIDATED"
                                                   else evaluate_request_binding(fact, binding_context)[0]),
                                   "proof_detail": ("no Request file to bind"
                                                    if fact["kind"] != "REQUEST_VALIDATED"
                                                    else evaluate_request_binding(fact, binding_context)[1])},
                       "effective": fact["kind"] != "REQUEST_VALIDATED"}
                      for fact in by_request[request_id]],
            "duplicate_request_id": False,
        })
    return out


def request_visibility(loaded, requests, facts_source):
    """The bounded answer to "what happened to the Requests?", never a verdict."""
    by_lifecycle = {}
    for entry in requests:
        by_lifecycle[entry["lifecycle"]] = by_lifecycle.get(entry["lifecycle"], 0) + 1
    rejected, negatives, unproven = [], [], []
    for entry in requests:
        for fact in entry["facts"]:
            if fact["kind"] == "REQUEST_VALIDATED" and fact["binding"]["proof_state"] == "NOT_ESTABLISHED":
                unproven.append({"request_id": entry["request_id"], "fact_id": fact["fact_id"],
                                 "submission": fact["submission"],
                                 "claimed_task_id": fact["binding"]["task_id"],
                                 "proof_detail": fact["binding"]["proof_detail"]})
            if fact["kind"] in ("REQUEST_DUPLICATE", "REQUEST_REPLAY_REJECTED"):
                negatives.append({"request_id": entry["request_id"], "fact_id": fact["fact_id"],
                                  "kind": fact["kind"], "first_observed_at": fact["first_observed_at"],
                                  "submission": fact["submission"],
                                  "reason_code": fact["reason"]["code"],
                                  "reason_class": fact["reason"]["class"],
                                  "counted_as_success": False})
            if fact["reason"]["applicable"]:
                rejected.append({"request_id": entry["request_id"], "fact_id": fact["fact_id"],
                                 "kind": fact["kind"], "first_observed_at": fact["first_observed_at"],
                                 "submission": fact["submission"],
                                 "reason_code": fact["reason"]["code"],
                                 "reason_class": fact["reason"]["class"],
                                 "reason_origin": fact["reason"]["origin"]})
    index = loaded.request_fact_index
    unbound = [s for s in (index or {}).get("submissions", []) if not s["fact_emitted"]]
    return {
        "facts_source": facts_source,
        "facts_collected": len(loaded.request_facts),
        "fact_observations_folded_into_a_semantic_fact": loaded.request_facts_collapsed,
        "facts_by_identity_rule": dict(sorted(loaded.request_fact_rules.items())),
        "submission_index_collected": index is not None,
        "submissions_observed": len((index or {}).get("submissions", [])),
        "by_lifecycle": dict(sorted(by_lifecycle.items())),
        "rejected_or_refused": sorted(rejected,
                                      key=lambda r: (r["first_observed_at"], r["fact_id"])),
        "duplicate_or_replay": sorted(negatives,
                                      key=lambda r: (r["first_observed_at"], r["fact_id"])),
        "acceptance_claims_without_a_signed_task": sorted(
            unproven, key=lambda r: r["fact_id"]),
        "submissions_without_a_request_identity": sorted(unbound, key=lambda s: s["submission_key"]),
        "why_not_a_task": {
            "answer_field": "requests[].why_not_a_task",
            "closed_states": list(REQUEST_FATE_STATES),
            "note": ("a Request that did not become a Task is answered from the closed state and, "
                     "where one exists, the Bridge's own reason code, preserved verbatim"),
        },
        "acceptance_requires_a_signed_task": True,
        "rejection_reasons_are_published": True,
        "duplicate_or_replay_counted_as_success": False,
        "facts_are_execution_authority": False,
        "bridge_fact_export_installed": False,
        "note": ("the Bridge's durable ledger holds the accepted half; every refusal reason is "
                 "printed by the Bridge and journalled by the operator, so this layer can only "
                 "report refusal reasons once that journal is installed. Until then a Request with "
                 "no settled fact stays REQUEST_CREATED, which is what the control bus shows"),
    }


def task_records(loaded, task_verifier, evidence_verifier, at, stale_seconds):
    by_nonce, by_id = {}, {}
    evidence_by_key = {}
    for name, item in loaded.evidence:
        evidence_by_key.setdefault((item["task_id"], item["nonce"]), []).append((name, item))

    for name, task in loaded.tasks:
        by_id.setdefault(task["task_id"], []).append(name)
        by_nonce.setdefault(task["nonce"], []).append(name)
    for task_id, names in sorted(by_id.items()):
        if len(names) > 1:
            loaded.anomaly("TASK_ID_REUSED", "duplicate task_id", task_id)
    for nonce, names in sorted(by_nonce.items()):
        if len(names) > 1:
            loaded.anomaly("REPLAY_REJECTED", "nonce reused across tasks", nonce)

    records = []
    for name, task in sorted(loaded.tasks, key=lambda pair: pair[1]["issued_at"]):
        refs = []
        signature = task_verifier.verify(task, "hex")
        entry = {
            "task_id": task["task_id"],
            "nonce": task["nonce"],
            "action_id": task["action_id"],
            "environment": task["environment"],
            "authority": task["authority"],
            "issued_at": task["issued_at"],
            "expires_at": task["expires_at"],
            "parameters": task["parameters"],
            "task_sha256": digest({k: v for k, v in task.items() if k != "signature"}),
            "source": {"repository": TASKS_REPOSITORY, "path": "tasks/" + name},
            "task_signature_verified": signature,
            "task_verifier_identity": TASK_VERIFIER_IDENTITY,
            "parameter_contract": task.get("_parameter_contract", "CURRENT"),
        }
        expires = parse_time(task["expires_at"])
        candidates = evidence_by_key.get((task["task_id"], task["nonce"]), [])
        conflicting = False
        if len(candidates) > 1:
            digests = {digest({k: v for k, v in item.items() if not k.startswith("_")})
                       for _, item in candidates}
            entry["evidence_count"] = len(candidates)
            if len(digests) > 1:
                # Two distinct signed records for one Task identity.  No single
                # outcome can be established, so this fails closed below.
                conflicting = True
                entry["evidence_conflict"] = True
                loaded.anomaly("EVIDENCE_CONFLICT",
                               "multiple distinct Evidence records for one signed task",
                               task["task_id"])
        if signature is False:
            entry.update({"lifecycle": "POLICY_HOLD",
                          "assertion": assertion(STATE_FAILED, "TASK_SIGNATURE_INVALID",
                                                 "the task signature does not verify against the "
                                                 "Command Center task verifier identity", refs)})
            records.append(entry)
            continue
        if entry["parameter_contract"] == "LEGACY_OR_UNKNOWN":
            loaded.anomaly("TASK_PARAMETER_CONTRACT_DRIFT",
                           "observed parameters %s are not the current %s contract"
                           % (sorted(task["parameters"]), task["action_id"]), task["task_id"])
            entry.update({"lifecycle": "POLICY_HOLD",
                          "assertion": unknown(
                              "this Task predates the current Control Plane parameter contract; it "
                              "is preserved for lineage but cannot be evaluated or counted as proof",
                              refs)})
            records.append(entry)
            continue
        if not candidates:
            if at >= expires:
                entry.update({
                    "lifecycle": "TASK_EXPIRED",
                    "assertion": assertion(STATE_OBSERVED, "TASK_EXPIRED",
                                           "expires_at passed with no signed Evidence for this task",
                                           refs),
                    "hk_agent_picked_up": unknown(
                        "no Evidence exists for this Task. Since CC V1-02 an authenticated Task "
                        "whose claimed attempt fails publishes a signed failure record, so absence "
                        "indicates the attempt was never claimed — but that cannot be asserted for "
                        "Tasks that predate the capability, and the agent ledger is still not on the "
                        "control bus", refs),
                })
            else:
                entry.update({
                    "lifecycle": "TASK_PUBLISHED",
                    "assertion": assertion(STATE_OBSERVED, "TASK_PUBLISHED",
                                           "signed task published and still inside its validity "
                                           "window", refs),
                    "hk_agent_picked_up": unknown("no Evidence published yet", refs),
                })
            records.append(entry)
            continue

        ev_name, ev = sorted(candidates, key=lambda pair: pair[1]["_completed_at"])[0]
        refs = sorted({name, ev_name})
        ev_signature = evidence_verifier.verify(ev, "base64")
        completed = parse_time(ev["_completed_at"])
        started = parse_time(ev["started_at"])
        # The health payload sits at executor_result in the current agent and at
        # result in the legacy generation; both are read-only observations.
        payload = ev.get("executor_result")
        if not isinstance(payload, dict):
            payload = ev.get("result") if isinstance(ev.get("result"), dict) else None
        entry["evidence"] = {
            "source": {"repository": EVIDENCE_REPOSITORY,
                       "path": "evidence/" + ev_name},
            "completed_at": ev["_completed_at"],
            "generation": ev["_generation"],
            "status": ev["status"],
            "executor_result": ev.get("executor_result") if isinstance(ev.get("executor_result"), str)
            else (ev.get("result") if isinstance(ev.get("result"), str) else None),
            "signature_verified": ev_signature,
            "verifier_identity": EVIDENCE_VERIFIER_IDENTITY,
            "evidence_sha256": digest({k: v for k, v in ev.items() if not k.startswith("_")}),
        }
        if payload:
            entry["liveness_payload"] = {
                "hostname": payload.get("hostname"),
                "agent_version": payload.get("agent_version"),
                "tasks_repo_connectivity": payload.get("tasks_repo_connectivity"),
                "evidence_repo_connectivity": payload.get("evidence_repo_connectivity"),
            }
        for key in ("built_image_id", "source_pr_number", "source_commit_sha",
                    "task_canonical_sha256", "deploy_record_id", "deploy_record_sha256",
                    "rollback_record_id", "candidate_contract_sha256"):
            if isinstance(ev.get(key), str):
                entry["evidence"][key] = ev[key]
        if isinstance(ev.get("agent_version"), str):
            entry["evidence"]["agent_version"] = ev["agent_version"]
        entry["execution_started"] = assertion(
            STATE_PROVEN if ev_signature else STATE_OBSERVED, ev["started_at"],
            "the Evidence carries started_at for this task/nonce", refs)

        verified = ev_signature is True
        if ev_signature is False:
            entry.update({"lifecycle": "EVIDENCE_INVALID",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_SIGNATURE_INVALID",
                                                 "the Evidence signature does not verify against the "
                                                 "Hong Kong evidence verifier identity", refs)})
        elif started > completed:
            entry.update({"lifecycle": "EVIDENCE_INVALID",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_TIME_ORDER",
                                                 "started_at is after completed_at", refs)})
        elif not candidate_digest_binding(task, ev):
            entry.update({"lifecycle": "EVIDENCE_INVALID",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_CANDIDATE_DIGEST_BINDING",
                                                 "the Evidence does not name the candidate its Task "
                                                 "named, so the execution cannot be attributed to the "
                                                 "candidate it claims", refs)})
        elif ev["status"] != "SUCCESS":
            # CC V1-02: a signed non-success status is the failure answer, and it
            # stays the answer even outside the validity window, because a failure
            # is recorded when the attempt stopped and that may legitimately be
            # after expires_at.  Only a claimed success can time out.
            detail = failure_detail(ev)
            described = ", ".join("%s=%s" % (key, detail[key])
                                  for key in ("kind", "stage", "reason_code") if key in detail)
            if detail["artifact_claimed_retry_permitted"] or \
                    detail["artifact_claimed_replay_authorized"] or \
                    detail["artifact_claimed_authorizes_any_action"]:
                loaded.anomaly("FAILURE_EVIDENCE_AUTHORIZATION_CLAIM",
                               "a failure record claims an authorization; the contract says a failure "
                               "record authorizes nothing, and the claim is given no effect",
                               task["task_id"])
            entry.update({"lifecycle": "EXECUTION_FAILED",
                          "assertion": assertion(
                              STATE_FAILED, ev["status"],
                              "the signed Evidence reports a non-success status%s"
                              % (": " + described if described else ""), refs),
                          "failure": detail})
        elif completed > expires:
            entry.update({"lifecycle": "EVIDENCE_TIMEOUT",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_AFTER_EXPIRY",
                                                 "Evidence completed_at is outside the task validity "
                                                 "window", refs)})
        else:
            expected = ACTION_RESULT.get(task["action_id"])
            result = ev.get("executor_result") if isinstance(ev.get("executor_result"), str) else None
            mismatch = bool(expected) and result != expected
            task_established = signature is True
            if conflicting:
                # Fail closed.  One Task identity cannot have two outcomes.
                entry.update({"lifecycle": "EVIDENCE_VERIFIED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EVIDENCE_CONFLICT",
                                  "two distinct signed Evidence records exist for one Task identity, "
                                  "so no single outcome can be established and no claim stronger than "
                                  "OBSERVED is made", refs)})
            elif mismatch and verified:
                entry.update({"lifecycle": "EXECUTION_FAILED",
                              "assertion": assertion(STATE_FAILED, "EXECUTOR_RESULT_MISMATCH",
                                                     "executor_result %r does not equal the frozen "
                                                     "terminal result %r" % (result, expected), refs)})
            elif mismatch:
                entry.update({"lifecycle": "EVIDENCE_PUBLISHED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EXECUTOR_RESULT_MISMATCH",
                                  "Evidence reports %r instead of the frozen terminal result %r, but "
                                  "the evidence signature was not verified, so OBSERVED is the "
                                  "strongest honest claim" % (result, expected), refs)})
            elif verified and task_established:
                entry.update({"lifecycle": "COMPLETE",
                              "assertion": assertion(STATE_PROVEN, expected or "HEALTH_OK",
                                                     "Evidence verified against the Hong Kong evidence "
                                                     "verifier identity, its Task verified against the "
                                                     "Command Center task verifier identity, and it "
                                                     "reports the frozen terminal result", refs)})
            elif verified:
                entry.update({"lifecycle": "EVIDENCE_VERIFIED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EVIDENCE_VERIFIED",
                                  "the Evidence verifies against the Hong Kong evidence identity, but "
                                  "no Command Center task verifier key was supplied, so the Task this "
                                  "Evidence claims to answer was never established and COMPLETE "
                                  "cannot be claimed", refs)})
            else:
                entry.update({"lifecycle": "EVIDENCE_PUBLISHED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EVIDENCE_PUBLISHED",
                                  "Evidence is published and reports %r, but no evidence verifier "
                                  "key was supplied, so OBSERVED is the strongest honest claim"
                                  % (result or "no result"), refs)})
        if at - completed > dt.timedelta(seconds=stale_seconds):
            entry["staleness"] = assertion(STATE_OBSERVED, "STALE",
                                           "the newest Evidence for this task is older than the "
                                           "configured freshness window", refs)
        records.append(entry)
    return records


def lifecycle_counts(tasks):
    counts = {}
    for task in tasks:
        counts[task["lifecycle"]] = counts.get(task["lifecycle"], 0) + 1
    return counts


def newest_for(tasks, action):
    matches = [t for t in tasks if t["action_id"] == action]
    if not matches:
        return None
    return max(matches, key=lambda t: t["evidence"]["completed_at"])


def canonical_pointers(go_repo):
    """The pointers the repository still publishes.

    Only the candidate pointer remains. The runtime pointer was retired on
    2026-10-08, so there is no ``runtime`` key any more and nothing reads one --
    a runtime's identity is established from signed live Evidence instead.
    """
    out = {"candidate": None, "hold": {}, "read_errors": []}
    if not go_repo:
        return out
    base = pathlib.Path(go_repo) / "docs" / "canonical-baseline"
    try:
        out["candidate"] = read_json(base / "CURRENT_CANDIDATE.json")
    except (OSError, ValueError) as exc:
        out["read_errors"].append("CURRENT_CANDIDATE.json:%s" % type(exc).__name__)
    candidate = out["candidate"] or {}
    out["hold"] = {
        "hk_deploy": "HOLD",
        "final_release": candidate.get("final_release", "UNKNOWN"),
        "production": candidate.get("production", "UNKNOWN"),
        "runtime_status": None,
    }
    return out


def source_identity(args, request_count, fact_count=0):
    """Stable, portable provenance. Never a workstation path."""
    return {
        "tasks": {"repository": TASKS_REPOSITORY, "ref": args.tasks_ref,
                  "head_sha": args.tasks_head},
        "evidence": {"repository": EVIDENCE_REPOSITORY, "ref": args.evidence_ref,
                     "head_sha": args.evidence_head},
        "requests": {"repository": TASKS_REPOSITORY,
                     "refs": ["refs/heads/boss-request-*", "refs/heads/request/*"],
                     "collected": request_count},
        "request_facts": {"repository": TASKS_REPOSITORY,
                          "refs": ["refs/heads/request-facts/*"],
                          "collected": fact_count,
                          "exporter": "control-plane/command-center-request-visibility-v1"},
        "go": {"repository": GO_REPOSITORY, "ref": args.go_ref, "head_sha": args.go_head,
               "canonical_candidate_pointer": CANONICAL_CANDIDATE_POINTER},
    }


def build_state(loaded, task_verifier, evidence_verifier, at, options):
    stale_seconds = options["stale_seconds"]
    liveness_window = options["liveness_window"]
    verification_window = options["verification_window"]
    stuck_after = options["stuck_after"]
    recent_window = options["recent_window"]

    tasks = task_records(loaded, task_verifier, evidence_verifier, at, stale_seconds)
    requests = request_records(loaded, request_binding_context(loaded, tasks, task_verifier))
    visibility = request_visibility(loaded, requests, {
        "repository": TASKS_REPOSITORY, "refs": ["refs/heads/request-facts/*"],
        "exporter": "control-plane/command-center-request-visibility-v1"})
    # A fact whose Request file was never collected has no control-bus source, so
    # it can never be "the newest Request on the bus".
    on_bus = [entry for entry in requests if entry.get("source")]
    pointers = canonical_pointers(options.get("go_repo"))

    def has_success(task):
        return (task.get("evidence") or {}).get("status") == "SUCCESS"

    # `completed` = signature-verified success (PROVEN territory)
    # `observed`  = published success whose chain could not be fully verified here
    completed = [t for t in tasks if t["lifecycle"] == "COMPLETE"]
    observed = [t for t in tasks
                if t["lifecycle"] in ("EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED") and has_success(t)]
    successes = completed + observed
    deploys = [t for t in successes if t["action_id"] == "HK_STAGING_DEPLOY"
               and t["assertion"]["state"] != STATE_FAILED]
    health = [t for t in successes if t["action_id"] == "CONTROL_PLANE_HEALTH"]
    newest_health = max(health, key=lambda t: t["evidence"]["completed_at"], default=None)
    newest_evidence = (max(successes, key=lambda t: t["evidence"]["completed_at"], default=None)
                       or max((t for t in tasks if t.get("evidence")),
                              key=lambda t: t["evidence"]["completed_at"], default=None))

    def last_task(action=None):
        pool = [t for t in tasks if action is None or t["action_id"] == action]
        if not pool:
            return unknown("no signed task of this class exists on the control bus yet")
        pick = max(pool, key=lambda t: t["evidence"]["completed_at"]
                   if t.get("evidence") else t["issued_at"])
        state = STATE_OBSERVED if pick["task_signature_verified"] is None else (
            STATE_PROVEN if pick["task_signature_verified"] else STATE_FAILED)
        return assertion(state,
                         {"task_id": pick["task_id"], "action_id": pick["action_id"],
                          "lifecycle": pick["lifecycle"], "issued_at": pick["issued_at"],
                          "expires_at": pick["expires_at"]},
                         "the newest signed task of this class observed on the control bus",
                         [pick["source"]["path"]]
                         + ([pick["evidence"]["source"]["path"]] if pick.get("evidence") else []))

    # ---- HK agent activity and liveness ------------------------------------ #
    last_activity = unknown("no CONTROL_PLANE_HEALTH Evidence exists on the control bus")
    liveness = unknown("no CONTROL_PLANE_HEALTH Evidence exists on the control bus")
    if newest_health:
        age = (at - parse_time(newest_health["evidence"]["completed_at"])).total_seconds()
        payload = newest_health.get("liveness_payload") or {}
        probe = newest_health["evidence"]["source"]["path"]
        last_activity = assertion(
            STATE_PROVEN if newest_health["lifecycle"] == "COMPLETE" else STATE_OBSERVED,
            {"completed_at": newest_health["evidence"]["completed_at"],
             "hostname": payload.get("hostname"), "agent_version": payload.get("agent_version"),
             "age_seconds": int(age)},
            "the newest signed CONTROL_PLANE_HEALTH Evidence, at any age. Activity is not liveness",
            [probe])
        if age > liveness_window:
            liveness = assertion(STATE_UNKNOWN, None,
                                 "the newest signed liveness Evidence is %d s old, outside the "
                                 "%d s window: a past success is not proof of current liveness"
                                 % (int(age), liveness_window), [probe])
            liveness["age_seconds"] = int(age)
            liveness["last_seen"] = {"hostname": payload.get("hostname"),
                                     "agent_version": payload.get("agent_version"),
                                     "completed_at": newest_health["evidence"]["completed_at"]}
        elif newest_health["lifecycle"] == "COMPLETE":
            liveness = assertion(STATE_PROVEN,
                                 {"hostname": payload.get("hostname"),
                                  "agent_version": payload.get("agent_version"),
                                  "age_seconds": int(age)},
                                 "signature-verified liveness Evidence inside the freshness window",
                                 [probe])
        else:
            liveness = assertion(STATE_OBSERVED,
                                 {"hostname": payload.get("hostname"),
                                  "agent_version": payload.get("agent_version"),
                                  "age_seconds": int(age)},
                                 "fresh liveness Evidence inside the window, but its signature was "
                                 "not checked here, so OBSERVED is the strongest honest claim",
                                 [probe])

    # ---- repository-declared runtime vs live verified runtime -------------- #
    # There is no repository-declared runtime any more. The pointer that used to carry
    # one was retired on 2026-10-08, so the only runtime identity this projection can
    # name -- and the only thing verification can rest on -- is the one signed live
    # Evidence proves. The comparison the state used to report was "declared vs proven";
    # it is now "is the live runtime established by fresh signed Evidence at all".
    repository_runtime = unknown(
        "the repository publishes no runtime pointer: the retired "
        "docs/canonical-baseline/CURRENT_HK_RUNTIME.json was the last one, and a "
        "runtime's identity is established from signed live Evidence")

    newest_verify = newest_for(successes, "HK_STAGING_VERIFY")
    live_image, live_state = None, RUNTIME_UNKNOWN
    if newest_verify:
        live_image = newest_verify["parameters"].get("expected_current_image_id")
        verify_age = (at - parse_time(newest_verify["evidence"]["completed_at"])).total_seconds()
        verified = newest_verify["lifecycle"] == "COMPLETE"
        live_verified = assertion(
            STATE_PROVEN if verified else STATE_OBSERVED,
            {"image_config_id": live_image,
             "verified_at": newest_verify["evidence"]["completed_at"],
             "age_seconds": int(verify_age),
             "verification_rank": "SIGNATURE_VERIFIED" if verified else "OBSERVED_ONLY"},
            "the newest VERIFY Evidence names the image that was current at that moment. This is a "
            "point-in-time proof, not a continuous statement",
            [newest_verify["evidence"]["source"]["path"]])
        # `image_relation` and `repository_declared_image` stay in the published contract but
        # can only ever carry these values now: there is nothing declared to relate to.
        detail = {"verdict": RUNTIME_UNKNOWN, "image_relation": "UNKNOWN",
                  "repository_declared_image": None,
                  "live_proven_image": live_image,
                  "live_verification_age_seconds": int(verify_age),
                  "live_verification_rank": "SIGNATURE_VERIFIED" if verified else "OBSERVED_ONLY"}
        refs = sorted({newest_verify["evidence"]["source"]["path"]})
        if verify_age > verification_window:
            live_state = RUNTIME_NOT_RECENTLY_VERIFIED
            detail["verdict"] = live_state
            verification_assertion = assertion(
                STATE_OBSERVED, detail,
                "the newest VERIFY Evidence is %d s old, outside the %d s window, so the live "
                "runtime is not recently verified" % (int(verify_age), verification_window),
                refs)
        else:
            live_state = RUNTIME_MATCH
            detail["verdict"] = live_state
            verification_assertion = assertion(
                STATE_PROVEN if verified else STATE_OBSERVED, detail,
                "the live runtime is established by the newest signed VERIFY Evidence inside the "
                "window. There is no repository-declared runtime to compare it against: the "
                "retired pointer was the last one, and signed Evidence is the only identity the "
                "repository publishes", refs)
    else:
        live_verified = unknown("no VERIFY Evidence carrying a runtime image was observed")
        verification_assertion = unknown(
            "no VERIFY Evidence exists on the control bus, so live runtime verification is unknown")

    # The host-identity check used to compare the retired pointer's declared host against the
    # host that signed liveness Evidence. There is no declared host any more, and inventing one
    # would repeat exactly the mistake the pointer made, so it is reported as unestablished.
    runtime_identity_assertion = unknown(
        "the repository publishes no runtime pointer any more, so there is no declared runtime "
        "host to bind to signed liveness Evidence")

    # ---- health, verify, test_pr ------------------------------------------ #
    health_assertion = unknown("no Evidence of any kind exists on the control bus")
    if newest_verify:
        age = (at - parse_time(newest_verify["evidence"]["completed_at"])).total_seconds()
        if newest_verify["assertion"]["state"] == STATE_FAILED:
            health_assertion = assertion(
                STATE_FAILED, newest_verify["lifecycle"],
                "the newest VERIFY task did not reach a successful terminal state",
                [newest_verify["source"]["path"]])
        else:
            rank = STATE_PROVEN if newest_verify["lifecycle"] == "COMPLETE" else STATE_OBSERVED
            health_assertion = assertion(
                rank, "HEALTHY_AS_OF_LAST_PROBE",
                "the newest VERIFY Evidence reports VERIFY_OK. This is the last proven moment, not "
                "present-moment liveness", [newest_verify["evidence"]["source"]["path"]])
            health_assertion["as_of"] = newest_verify["evidence"]["completed_at"]
            health_assertion["age_seconds"] = int(age)
            health_assertion["stale"] = age > stale_seconds

    newest_test_pr = newest_for(successes, "HK_STAGING_TEST_PR")
    test_pr = unknown("no successful TEST_PR Evidence was observed")
    if newest_test_pr:
        verifier_rank = STATE_PROVEN if newest_test_pr["lifecycle"] == "COMPLETE" else STATE_OBSERVED
        test_pr = assertion(
            verifier_rank,
            {"task_id": newest_test_pr["task_id"],
             "pr_number": newest_test_pr["parameters"]["source"]["pr_number"],
             "commit_sha": newest_test_pr["parameters"]["source"]["commit_sha"],
             "result": newest_test_pr["evidence"].get("executor_result"),
             "built_image_id": newest_test_pr["evidence"].get("built_image_id"),
             "completed_at": newest_test_pr["evidence"]["completed_at"],
             "application_health_proven": False, "deployment_performed": False},
            "the newest successful TEST_PR Evidence. An isolated offline build is not a deployment",
            [newest_test_pr["evidence"]["source"]["path"]])

    # ---- task population classification ----------------------------------- #
    def brief(task):
        return {"task_id": task["task_id"], "action_id": task["action_id"],
                "lifecycle": task["lifecycle"], "issued_at": task["issued_at"],
                "expires_at": task["expires_at"],
                "source_path": task["source"]["path"]}

    active = [t for t in tasks if t["lifecycle"] in ("TASK_PUBLISHED", "TASK_SIGNED")]
    active_stuck = [t for t in active
                    if (at - parse_time(t["issued_at"])).total_seconds() > stuck_after]
    expired = [t for t in tasks if t["lifecycle"] == "TASK_EXPIRED"]
    recent_expired = [t for t in expired
                      if parse_time(t["expires_at"]) >= at - dt.timedelta(seconds=recent_window)]
    historical_expired = [t for t in expired if t not in recent_expired]
    broken = [t for t in tasks if t["lifecycle"] in
              ("EXECUTION_FAILED", "EVIDENCE_INVALID", "EVIDENCE_TIMEOUT", "POLICY_HOLD")]

    if active_stuck:
        stuck_answer = assertion(
            STATE_OBSERVED, "YES",
            "%d task(s) are published, still inside their validity window and more than %d s old "
            "with no Evidence" % (len(active_stuck), stuck_after),
            [t["source"]["path"] for t in active_stuck])
    else:
        stuck_answer = assertion(
            STATE_OBSERVED, "NO",
            "no published task is overdue. %d recently expired and %d historical expired task(s) "
            "are indexed separately and do not affect current health"
            % (len(recent_expired), len(historical_expired)))

    last_failure = unknown("no failed, invalid, hold or expired task was observed")
    terminal_non_success = broken + expired
    if terminal_non_success:
        def terminal_rank(task):
            return ((task.get("evidence") or {}).get("completed_at")) or task["expires_at"]
        pick = max(terminal_non_success, key=terminal_rank)
        proven_failure = pick in broken
        failure_refs = [pick["source"]["path"]]
        evidence_path = (pick.get("evidence") or {}).get("source", {}).get("path")
        if evidence_path:
            failure_refs.append(evidence_path)
        failure_value = {"task_id": pick["task_id"], "action_id": pick["action_id"],
                         "lifecycle": pick["lifecycle"], "value": pick["assertion"]["value"],
                         "kind": "FAILED_RECORD" if proven_failure else "EXPIRED_WITHOUT_EVIDENCE",
                         "at": terminal_rank(pick)}
        if pick.get("failure"):
            # CC V1-02: why it failed and where the attempt stopped, so the last
            # failure can be answered together with the Task that caused it.
            failure_value["failure"] = pick["failure"]
        last_failure = assertion(
            STATE_OBSERVED,
            failure_value,
            ("the most recent terminal failure record on the control bus" if proven_failure else
             "the most recent terminal non-success is an expiry, not a proven failure: the task "
             "reached its expiry with no Evidence, and that is now a meaningful statement — an "
             "authenticated Task whose claimed attempt fails publishes a signed failure record, so "
             "absence indicates the attempt was never claimed rather than an unpublished failure"),
            sorted(set(failure_refs)))

    # ---- rollback candidates ---------------------------------------------- #
    rollback_pairs = sorted({t["task_id"]: t["evidence"]["completed_at"] for t in deploys}.items(),
                            key=lambda pair: pair[1])
    rollback = unknown("no successful DEPLOY Evidence exists on the control bus")
    if rollback_pairs:
        newest_deploy = rollback_pairs[-1][0]
        rollback = assertion(
            STATE_OBSERVED,
            {"source_deploy_task_id": newest_deploy,
             "releases": [name for name, _ in rollback_pairs],
             "newest_completed_at": rollback_pairs[-1][1]},
            "rollback eligibility is a candidate set derived from successful DEPLOY Evidence. It is "
            "not an approval and not a signed ROLLBACK task",
            [t["evidence"]["source"]["path"] for t in deploys if t["task_id"] == newest_deploy])

    # ---- request channel and deploy capability ---------------------------- #
    request_channel = {
        "enabled_request_actions": list(ENABLED_REQUEST_ACTIONS),
        "human_request_actions": list(HUMAN_REQUEST_ACTIONS),
        "platform_request_actions": list(PLATFORM_REQUEST_ACTIONS),
        "enabled_human_request_actions": list(ENABLED_HUMAN_REQUEST_ACTIONS),
        "enabled_platform_request_actions": list(ENABLED_PLATFORM_REQUEST_ACTIONS),
        "request_action_source_class": dict(REQUEST_ACTION_SOURCE_CLASS),
        "platform_action_properties": {k: dict(v)
                                       for k, v in sorted(PLATFORM_ACTION_PROPERTIES.items())},
        "known_capabilities": list(KNOWN_CAPABILITIES),
        "capability_classification": dict(CAPABILITY_CLASSIFICATION),
        "deploy_request_enabled": True,
        "deploy_request_enabled_source": (
            "the channel contract exposes all six actions with deployment_authorization="
            "'request', so the DEPLOY Request is enabled and there is no switch to open: the "
            "authenticated Request is itself the authorisation. This is the contract-level "
            "answer only. Whether the live host currently accepts one is a live-host fact and "
            "is reported separately as live_request_switch, never asserted here; a host with "
            "deployments suspended refuses the Request with "
            "deployment_authorization_mode_unsupported"),
        "live_request_switch": unknown(
            "the live Command Center channel switch is a live-host fact. It is not on the control "
            "bus and this projection must not assert it"),
        "readiness_evaluation": "NOT_IN_SCOPE",
        "note": ("ChatGPT may create Request files only for enabled_human_request_actions. A "
                 "platform_request_actions entry is created by the platform's own bounded producer, "
                 "not by a human, and carries fixed empty parameters and no execution right: "
                 "read_only=true and human_deploy_authority=false. HK_STAGING_DEPLOY is reported as "
                 "a capability classification; computing deploy or rollback readiness is out of "
                 "scope for this contract"),
    }

    # ---- repository main vs runtime build source --------------------------- #
    repository_main = (assertion(STATE_OBSERVED, options["repository_main_sha"],
                                 "the repository main revision supplied to this run")
                       if options.get("repository_main_sha")
                       else unknown(
                           "the current repository main revision was not supplied. The projector "
                           "reads local checkouts and never runs git, so it will not substitute a "
                           "runtime source SHA for the repository head"))
    runtime_built_from = unknown(
        "the repository publishes no runtime pointer any more, so no product source commit is "
        "declared for the running runtime; the signed live VERIFY Evidence is the record")
    runtime_canonical_main = unknown(
        "the repository publishes no runtime pointer any more, so no canonical main commit is "
        "declared for the running runtime")

    # ---- deploy capability classification ---------------------------------- #
    # Capability only. This contract does not evaluate deploy readiness: real
    # readiness would have to combine an approved candidate, TEST_PR, VERIFY,
    # CANARY, Human Approval, a deployment plan, source/package/image binding,
    # the current runtime and the live Command Center switch. None of that is in
    # scope here, so no DEPLOY_READY / can_deploy / eligibility value is produced.
    hold = pointers["hold"]
    deploy_capability = assertion(
        STATE_OBSERVED,
        {"capability": "SUPPORTED_PROVEN", "request_enabled": True,
         "readiness_evaluation": "NOT_IN_SCOPE"},
        "the DEPLOY capability is proven and its Request is enabled, with no switch to open. "
        "This is a capability classification, not a readiness evaluation, and it must never be read "
        "as one")

    readiness = loaded.deploy_readiness
    if readiness is None:
        deploy_readiness_assertion = unknown(
            "no deploy readiness verdict was supplied. The evaluator is a separate read-only "
            "component, so without its document this projection states nothing about readiness")
    elif readiness["deploy_ready"] == "UNKNOWN":
        deploy_readiness_assertion = unknown(
            "the read-only evaluator could not establish %s, so readiness is unknown rather than yes"
            % ", ".join(readiness["unknown"] or ["-"]))
    elif readiness["deploy_ready"] == "NO":
        deploy_readiness_assertion = assertion(
            STATE_OBSERVED, "NO",
            "the read-only evaluator refused: %s" % ", ".join(readiness["failed"] or ["-"]),
            [DEPLOY_READINESS_DOCUMENT])
    else:
        deploy_readiness_assertion = assertion(
            STATE_OBSERVED, "YES",
            "every mandatory gate passed as of %s. This is an observation about the evidence, not "
            "an approval, and it authorises nothing" % (readiness["as_of"] or "the evaluation "
                                                                             "instant"),
            [DEPLOY_READINESS_DOCUMENT])

    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_STATE,
        "scope": CONTRACT_SCOPE,
        "authority": AUTHORITY,
        "authority_note": ("Derived projection only. The Signed Task is the only Execution "
                           "Authority and the Signed Evidence is the only proof. This document "
                           "never authorizes an operation, and it adds no execution capability."),
        "generated_at": iso(at),
        "freshness": {"stale_after_seconds": stale_seconds,
                      "liveness_window_seconds": liveness_window,
                      "liveness_probe_interval_seconds": LIVENESS_PROBE_INTERVAL_SECONDS,
                      "liveness_transport_grace_seconds": LIVENESS_TRANSPORT_GRACE_SECONDS,
                      "liveness_max_probes_per_24h": LIVENESS_MAX_PROBES_PER_24H,
                      "live_verification_window_seconds": verification_window,
                      "stuck_after_seconds": stuck_after,
                      "recent_expired_window_seconds": recent_window},
        "sources": source_identity(options["args"], len(requests), len(loaded.request_facts)),
        "verification": {
            "task": task_verifier.describe(),
            "evidence": evidence_verifier.describe(),
            "identity_contract": options["identity_contract"].describe(),
            "identities_separated": options["identities_separated"],
            "proven_allowed": options["proven_allowed"],
            "fail_closed_reasons": options["fail_closed_reasons"],
            "proven_requires_both_keys": True,
            "proven_requires_both_identities_bound": True,
            "note": ("A Task must never validate against the evidence key and Evidence must never "
                     "validate against the task key. PROVEN requires the artifact's own identity to "
                     "verify, and it additionally requires that identity to be the one published in "
                     "the verifier identity contract. A key that merely loads is not the right key"),
        },
        "counts": {
            "tasks": len(tasks), "evidence": len(loaded.evidence), "requests": len(requests),
            "request_facts": len(loaded.request_facts),
            "request_fact_observations": (len(loaded.request_facts)
                                         + loaded.request_facts_collapsed),
            "request_facts_collapsed": loaded.request_facts_collapsed,
            "by_lifecycle": lifecycle_counts(tasks), "anomalies": len(loaded.anomalies),
        },
        "requests": requests,
        "request_visibility": visibility,
        "tasks": tasks,
        "request_channel": request_channel,
        "control_state": {
            "health": health_assertion,
            "last_request": (assertion(STATE_OBSERVED, on_bus[-1]["request_id"],
                                       "the newest Request file observed on a control-bus ref",
                                       [on_bus[-1]["source"]["path"]])
                             if on_bus else unknown("no Request file observed on the control bus")),
            "last_task": last_task(),
            "last_evidence": (assertion(
                STATE_PROVEN if newest_evidence["lifecycle"] == "COMPLETE" else STATE_OBSERVED,
                {"task_id": newest_evidence["task_id"],
                 "action_id": newest_evidence["action_id"],
                 "completed_at": newest_evidence["evidence"]["completed_at"]},
                "the newest signed Evidence on the control bus",
                [newest_evidence["evidence"]["source"]["path"]])
                if newest_evidence else unknown("no signed Evidence exists on the control bus")),
            "last_failure": last_failure,
            "hk_agent_last_activity": last_activity,
            "hk_agent_liveness": liveness,
            "hk_runtime_identity": runtime_identity_assertion,
            "verify_status": last_task("HK_STAGING_VERIFY"),
            "test_pr_status": test_pr,
            "deploy_capability": deploy_capability,
            "repository_runtime_pointer": repository_runtime,
            "live_verified_runtime": live_verified,
            "runtime_verification": verification_assertion,
            "runtime_verification_state": live_state,
            "repository_main_sha": repository_main,
            "runtime_built_from_main_sha": runtime_built_from,
            "runtime_canonical_main_sha": runtime_canonical_main,
            "stuck_answer": stuck_answer,
            # CC V1-06. The verdict a separate read-only evaluator produced, quoted
            # verbatim and never evaluated here. `state` describes the observation;
            # `value` carries the closed verdict.
            "deploy_readiness": deploy_readiness_assertion,
            "deploy_readiness_gates": (loaded.deploy_readiness or {}).get("gates", []),
            "active_tasks": [brief(t) for t in active],
            "active_stuck_tasks": [brief(t) for t in active_stuck],
            "recent_expired_tasks": [brief(t) for t in recent_expired],
            "historical_expired_tasks": [brief(t) for t in historical_expired],
            "failed_or_invalid_tasks": [
                {"task_id": t["task_id"], "action_id": t["action_id"], "lifecycle": t["lifecycle"],
                 "reason": t["assertion"]["reason"], "source_path": t["source"]["path"]}
                for t in broken],
            "stale_tasks": [{"task_id": t["task_id"], "action_id": t["action_id"],
                             "completed_at": t["evidence"]["completed_at"]}
                            for t in tasks if t.get("staleness")],
            "last_successful_deploy": (assertion(STATE_OBSERVED, deploys[-1]["task_id"],
                                                 "the newest successful DEPLOY Evidence",
                                                 [deploys[-1]["evidence"]["source"]["path"]])
                                       if deploys else unknown("no successful DEPLOY Evidence")),
            # Informational, non-contract. These are recorded facts read from the
            # canonical pointer and from historical signed Evidence. They are NOT
            # part of CONTROL_STATUS_V1 and they are NOT a readiness evaluation.
            "informational": {
                "contract": False,
                "note": ("recorded facts only. Deploy readiness and rollback readiness are explicitly "
                         "out of scope for this contract"),
                "rollback_candidate_history": rollback,
                "release_gates": hold or {"hk_deploy": "UNKNOWN", "final_release": "UNKNOWN",
                                          "production": "UNKNOWN"},
                "final_release_gate": assertion(
                    STATE_HOLD if hold.get("final_release") == "HOLD" else STATE_UNKNOWN,
                    hold.get("final_release"),
                    "release acceptance is a separate axis from the business runtime and the Control "
                    "Plane"),
                "hk_deploy_gate": assertion(
                    STATE_HOLD if hold.get("hk_deploy") == "HOLD" else STATE_UNKNOWN,
                    hold.get("hk_deploy"),
                    "deployment authorization is not derived from the existence of a DEPLOY "
                    "capability, and this contract does not evaluate deployment readiness"),
                "production": assertion(
                    STATE_HOLD if hold.get("production") in ("HOLD", "UNTOUCHED_HOLD")
                    else STATE_UNKNOWN,
                    hold.get("production"),
                    "Production has not been touched and is out of scope for the Control Plane"),
            },
            "out_of_scope": {
                "deploy_readiness_evaluation": ("EVALUATED_READ_ONLY"
                                                if loaded.deploy_readiness else "NOT_IN_SCOPE"),
                "deploy_readiness_document": (DEPLOY_READINESS_DOCUMENT
                                              if loaded.deploy_readiness else None),
                "rollback_readiness_evaluation": "NOT_IN_SCOPE",
                "note": ("deploy readiness is evaluated read-only by "
                         "control-plane/command-center-deploy-readiness-v1 from this state plus an "
                         "optional operator-supplied bundle of live-host facts; it creates and "
                         "publishes nothing and its YES authorises nothing. Rollback readiness "
                         "would have to combine a signed source DEPLOY task, its Evidence and "
                         "Human Approval, and is not evaluated here"),
            },
        },
        "anomalies": loaded.anomalies,
        "rebuild": {
            "deterministic": True,
            "pin_generated_at": "pass --now <ISO8601> to make the byte output reproducible",
            "command": ("python control-plane/command-center-state-v1/state_projection.py "
                        "--tasks-repo <go-control-tasks> --evidence-repo <go-control-evidence> "
                        "--requests-dir <collected-requests> --request-facts-dir <exported-facts> "
                        "--go-repo <GO> "
                        "--task-verify-key <cc-task.pub> --evidence-verify-key <hk-evidence.pub> "
                        "--verifier-identities <identity/VERIFIER_IDENTITIES_V1.json> "
                        "--tasks-head <sha> --evidence-head <sha> --go-head <sha> "
                        "--repository-main-sha <sha> --now <ISO8601> --out <dir>"),
        },
    }


def verdict_for(control_state):
    """One shared health verdict so the two contracts can never disagree."""
    verify = control_state["verify_status"]
    if verify["state"] == STATE_FAILED:
        return verify
    return control_state["health"]


def build_status(state, verdict):
    cs = state["control_state"]
    tasks = state["tasks"]

    pr_index = {}
    for task in tasks:
        if task["action_id"] != "HK_STAGING_TEST_PR" or not task.get("evidence"):
            continue
        source = task["parameters"]["source"]
        pr_index.setdefault(source["pr_number"], []).append({
            "task_id": task["task_id"],
            "commit_sha": source["commit_sha"],
            "lifecycle": task["lifecycle"],
            "result": task["evidence"].get("executor_result"),
            "built_image_id": task["evidence"].get("built_image_id"),
            "completed_at": task["evidence"]["completed_at"],
            "signature_verified": task["evidence"].get("signature_verified"),
            "state": task["assertion"]["state"],
            "source_path": task["evidence"]["source"]["path"],
        })
    pending_test_pr = [{"task_id": t["task_id"], "pr_number": t["parameters"]["source"]["pr_number"],
                        "lifecycle": t["lifecycle"], "state": t["assertion"]["state"],
                        "issued_at": t["issued_at"], "expires_at": t["expires_at"]}
                       for t in tasks
                       if t["action_id"] == "HK_STAGING_TEST_PR" and not t.get("evidence")]

    answers = {
        # ---- the ten status questions, and nothing that implies more ------- #
        # 1  HK Agent 最近是否有活动
        "hk_agent_recent_activity": cs["hk_agent_last_activity"],
        # 2  当前有没有正在执行的任务
        "active_tasks": {"state": STATE_OBSERVED, "value": len(cs["active_tasks"]),
                         "reason": "tasks published and still inside their validity window",
                         "evidence": [t["source_path"] for t in cs["active_tasks"]],
                         "tasks": cs["active_tasks"]},
        # 3  最近任务是否完成
        "last_task": cs["last_task"],
        # 4 + 5  PR X 是否已经 TEST_PR / 结果是什么
        "pr_tested": {"latest": cs["test_pr_status"], "by_pr_number": pr_index,
                      "in_flight": pending_test_pr,
                      "note": "look up by_pr_number for 'has PR N been TEST_PR tested?'"},
        # 6  最近一次 VERIFY 是否成功
        "verify": cs["verify_status"],
        # 7  repository-declared runtime
        "repository_declared_runtime": cs["repository_runtime_pointer"],
        # 8  该 runtime 最近是否被 live VERIFY 证明
        "runtime_verification": cs["runtime_verification"],
        # 9  当前是否存在 active stuck task
        "stuck_tasks": {
            "answer": cs["stuck_answer"],
            "active_stuck_tasks": cs["active_stuck_tasks"],
            "recent_expired_tasks": cs["recent_expired_tasks"],
            "historical_expired_tasks": cs["historical_expired_tasks"],
            "default_lookup": "active_stuck_tasks",
            "note": ("'is anything stuck right now' is answered only from active_stuck_tasks. "
                     "Expired history is indexed separately and never affects current health"),
        },
        # 10 最近一次失败是什么
        "last_failure": cs["last_failure"],
        # Which actions chat may currently create a Request for.
        "request_channel": state["request_channel"],
        # Why a Request did not become a Task, from the Bridge's own facts.
        "request_fate": {
            "by_request_id": {r["request_id"]: {"lifecycle": r["lifecycle"],
                                                "why_not_a_task": r["why_not_a_task"],
                                                "binding": r["binding"]}
                              for r in state["requests"]},
            "accepted": sum(1 for r in state["requests"] if r["lifecycle"] == "REQUEST_VALIDATED"),
            "refused": sum(1 for r in state["requests"] if r["lifecycle"] == "REQUEST_REJECTED"),
            "duplicate": sum(1 for r in state["requests"] if r["lifecycle"] == "REQUEST_DUPLICATE"),
            "replayed": sum(1 for r in state["requests"] if r["lifecycle"] == "REQUEST_REPLAY_REJECTED"),
            "waiting": sum(1 for r in state["requests"] if r["lifecycle"] == "REQUEST_CREATED"),
            "unbound_submissions": state["request_visibility"][
                "submissions_without_a_request_identity"],
            "answer": ("look up by_request_id; why_not_a_task.state is a closed set and "
                       "BECAME_A_TASK is reported only when a signed Task corroborates it. A "
                       "Bridge fact is never Execution Authority."),
        },
        # ---- supporting fields, not part of the required answer set -------- #
        "last_evidence": cs["last_evidence"],
        "live_verified_runtime": cs["live_verified_runtime"],
        "go_is_healthy": verdict,
        "hk_agent_online": cs["hk_agent_liveness"],
        "repository_main_sha": cs["repository_main_sha"],
        "runtime_built_from_main_sha": cs["runtime_built_from_main_sha"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_STATUS,
        "scope": CONTRACT_SCOPE,
        "audience": "CHATGPT_CONNECTOR / HUMAN_OPERATOR",
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "freshness": state["freshness"],
        "sources": state["sources"],
        "verification": state["verification"],
        "answers": answers,
        "limits": {
            "read_contract_only": ("This is a bounded read contract. It is not Execution Authority, "
                                   "it never contains an execution parameter, and it can neither "
                                   "create nor sign a Task"),
            "unobservable_by_this_projection": [
                "the live Command Center channel switch and the approved deployment plan store",
                "the Hong Kong agent ledger (attempts, failures, nonce claims)",
                "runtime process state on HK-STAGING",
                "the current repository main revision, unless it is passed in explicitly",
                "any Bridge observation that was never exported as a fact: the Bridge prints "
                "refusal reasons and keeps them nowhere, so until the export is installed a "
                "Request with no settled fact is reported as REQUEST_CREATED",
            ],
            "never_infer": ("last successful task != agent online; repository pointer != live "
                            "runtime; capability present != request enabled; a Request file "
                            "existing != the Request was accepted"),
        },
        "out_of_scope": {
            "deploy_readiness_evaluation": "NOT_IN_SCOPE",
            "rollback_readiness_evaluation": "NOT_IN_SCOPE",
            "note": ("this contract answers the ten status questions, the request channel and the "
                     "fate of a submitted Request. It "
                     "does not compute can_deploy, deployment eligibility, rollback target selection "
                     "or release-gate verdicts, and no such key is present in answers. A read-only "
                     "deploy readiness verdict, when one has been produced, is carried in "
                     "CURRENT_CONTROL_STATE.json as control_state.deploy_readiness; it is never "
                     "an approval and this contract deliberately does not surface it"),
        },
        "verdict": {"healthy": verdict},
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks-repo", required=True, help="local checkout of go-control-tasks")
    parser.add_argument("--evidence-repo", required=True, help="local checkout of go-control-evidence")
    parser.add_argument("--requests-dir", help="optional directory of collected Request files")
    parser.add_argument("--request-facts-dir",
                        help=("optional directory of Bridge Request facts exported read-only by "
                              "control-plane/command-center-request-visibility-v1"))
    parser.add_argument("--deploy-readiness",
                        help=("optional DEPLOY_READINESS.json produced read-only by "
                              "control-plane/command-center-deploy-readiness-v1"))
    parser.add_argument("--go-repo", help="optional local checkout of the GO repository")
    parser.add_argument("--task-verify-key",
                        help="pinned Command Center task-manifest public key (hex-signature identity)")
    parser.add_argument("--evidence-verify-key",
                        help="pinned Hong Kong evidence public key (base64-signature identity)")
    parser.add_argument("--verifier-identities", default=str(default_identity_contract_path()),
                        help=("published verifier identity contract; a supplied key is only trusted "
                              "when its fingerprint matches this contract"))
    parser.add_argument("--tasks-head", default=None, help="pinned commit SHA of the tasks source")
    parser.add_argument("--tasks-ref", default="main")
    parser.add_argument("--evidence-head", default=None, help="pinned commit SHA of the evidence source")
    parser.add_argument("--evidence-ref", default="permission-test")
    parser.add_argument("--go-head", default=None, help="pinned commit SHA of the GO source")
    parser.add_argument("--go-ref", default="main")
    parser.add_argument("--repository-main-sha",
                        help="current repository main revision, if it has been established out of band")
    parser.add_argument("--out", required=True, help="output directory (created if absent)")
    parser.add_argument("--now", help="ISO 8601 instant to project at (default: current UTC)")
    parser.add_argument("--stale-after-seconds", type=int, default=86400)
    parser.add_argument("--liveness-window-seconds", type=int,
                        default=LIVENESS_FRESHNESS_WINDOW_SECONDS,
                        help="how old the newest signed liveness Evidence may be and still be "
                             "PROVEN. Defaults to the probe interval plus the transport grace, "
                             "which is %d s" % LIVENESS_FRESHNESS_WINDOW_SECONDS)
    parser.add_argument("--live-verification-window-seconds", type=int, default=86400)
    parser.add_argument("--stuck-after-seconds", type=int, default=900)
    parser.add_argument("--recent-expired-window-seconds", type=int, default=604800)
    parser.add_argument("--stdout", action="store_true", help="also print CONTROL_STATUS_V1")
    args = parser.parse_args(argv)

    at = parse_time(args.now) if args.now else now_utc().replace(microsecond=0)
    loaded = Loaded()
    load_tasks(args.tasks_repo, loaded)
    load_evidence(args.evidence_repo, loaded)
    load_requests(args.requests_dir, loaded)
    load_request_facts(args.request_facts_dir, loaded)
    load_deploy_readiness(args.deploy_readiness, loaded)

    identity_contract = IdentityContract(args.verifier_identities)
    task_verifier = Verifier(args.task_verify_key, TASK_VERIFIER_IDENTITY, "hex",
                             expected=identity_contract.expected(ROLE_TASK))
    evidence_verifier = Verifier(args.evidence_verify_key, EVIDENCE_VERIFIER_IDENTITY, "base64",
                                 expected=identity_contract.expected(ROLE_EVIDENCE))
    identities_separated = separated(task_verifier, evidence_verifier, loaded)
    task_bound, evidence_bound = bind_identities(task_verifier, evidence_verifier, loaded)
    proven_allowed = bool(identities_separated and task_bound and evidence_bound)

    # Fail closed. A verifier that is not the published identity, or that collides
    # with the other role, is disabled so it can never return True and therefore
    # can never produce PROVEN. Its identity_binding is still reported.
    if not task_bound or not identities_separated:
        task_verifier = task_verifier.disabled_copy()
    if not evidence_bound or not identities_separated:
        evidence_verifier = evidence_verifier.disabled_copy()

    fail_closed_reasons = sorted({
        "%s:%s" % (role, verifier.binding)
        for role, verifier in (("task", task_verifier), ("evidence", evidence_verifier))
        if verifier.binding != BINDING_BOUND
    } | ({"roles:IDENTITY_COLLISION"} if not identities_separated else set()))

    options = {
        "stale_seconds": args.stale_after_seconds,
        "liveness_window": args.liveness_window_seconds,
        "verification_window": args.live_verification_window_seconds,
        "stuck_after": args.stuck_after_seconds,
        "recent_window": args.recent_expired_window_seconds,
        "go_repo": args.go_repo,
        "repository_main_sha": args.repository_main_sha,
        "identities_separated": identities_separated,
        "identity_contract": identity_contract,
        "proven_allowed": proven_allowed,
        "fail_closed_reasons": fail_closed_reasons,
        "args": args,
    }
    state = build_state(loaded, task_verifier, evidence_verifier, at, options)
    status = build_status(state, verdict_for(state["control_state"]))

    # Portability guard: the derived documents must never carry a workstation
    # path, a user directory or a temp directory.
    leaked = sorted(set(LOCAL_PATH_RE.findall(
        json.dumps(state, sort_keys=True) + json.dumps(status, sort_keys=True))))
    if leaked:
        loaded.anomaly("LOCAL_PATH_LEAK",
                       "derived output contains machine-specific path fragments: %s" % leaked)
        state["anomalies"] = loaded.anomalies
        state["counts"]["anomalies"] = len(loaded.anomalies)

    index = {
        "schema_version": SCHEMA_VERSION,
        "contract": "TASK_INDEX",
        "scope": CONTRACT_SCOPE,
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "entries": [{
            "task_id": t["task_id"], "action_id": t["action_id"], "lifecycle": t["lifecycle"],
            "issued_at": t["issued_at"], "expires_at": t["expires_at"],
            "task_sha256": t["task_sha256"], "source_path": t["source"]["path"],
            "task_signature_verified": t["task_signature_verified"],
            "evidence_state": (t.get("evidence") or {}).get("status", "NO_EVIDENCE_PUBLISHED"),
            "evidence_path": (t.get("evidence") or {}).get("source", {}).get("path"),
            "evidence_sha256": (t.get("evidence") or {}).get("evidence_sha256"),
            "evidence_signature_verified": (t.get("evidence") or {}).get("signature_verified"),
            "assertion_state": t["assertion"]["state"],
        } for t in state["tasks"]],
    }
    latest = {
        "schema_version": SCHEMA_VERSION,
        "contract": "LATEST_EVIDENCE",
        "scope": CONTRACT_SCOPE,
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "by_action": {},
    }
    for task in sorted((t for t in state["tasks"] if t.get("evidence")),
                       key=lambda t: t["evidence"]["completed_at"]):
        latest["by_action"][task["action_id"]] = {
            "task_id": task["task_id"], "completed_at": task["evidence"]["completed_at"],
            "path": task["evidence"]["source"]["path"], "sha256": task["evidence"]["evidence_sha256"],
            "status": task["evidence"]["status"], "lifecycle": task["lifecycle"],
            "signature_verified": task["evidence"]["signature_verified"],
        }

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (("CURRENT_CONTROL_STATE.json", state),
                          ("CONTROL_STATUS_V1.json", status),
                          ("TASK_INDEX.json", index),
                          ("LATEST_EVIDENCE.json", latest)):
        (out / name).write_bytes(
            json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")

    summary = {
        "contract": CONTRACT_STATUS, "scope": CONTRACT_SCOPE,
        "generated_at": state["generated_at"],
        "tasks": state["counts"]["tasks"], "evidence": state["counts"]["evidence"],
        "requests": state["counts"]["requests"],
        "by_lifecycle": state["counts"]["by_lifecycle"],
        "task_signature_verification": state["verification"]["task"]["signature_verification"],
        "evidence_signature_verification": state["verification"]["evidence"]["signature_verification"],
        "task_identity_binding": state["verification"]["task"]["identity_binding"],
        "evidence_identity_binding": state["verification"]["evidence"]["identity_binding"],
        "proven_allowed": state["verification"]["proven_allowed"],
        "identities_separated": identities_separated,
        "hk_agent_liveness": status["answers"]["hk_agent_online"]["state"],
        "runtime_verification": state["control_state"]["runtime_verification_state"],
        "active_stuck_tasks": len(state["control_state"]["active_stuck_tasks"]),
        "enabled_request_actions": request_channel_list(state),
        "request_facts": state["counts"]["request_facts"],
        "request_lifecycles": state["request_visibility"]["by_lifecycle"],
        "anomalies": [a["kind"] for a in state["anomalies"]],
        "out": str(out),
    }
    print(json.dumps(summary, sort_keys=True))
    if args.stdout:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def request_channel_list(state):
    return state["request_channel"]["enabled_request_actions"]


if __name__ == "__main__":
    sys.exit(main())
