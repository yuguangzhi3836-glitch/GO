"""End-to-end verification of one C13+C14 round.

This is the single entry point the workflows, the ledger adapter and (next round)
the CC ``ReviewVerifier`` call. It answers one question:

    "are these two sealed bundles a valid, bound, independent, same-candidate
     C14-then-C13 pair for the task the scheduler actually dispatched?"

It never accepts a tampered, unbound, mismatched, expired or prerequisite-blocked
record set, and it never authorises an action.

The dispatch input is per-cell, because one round is two executions of two
different cells with two different ledger tasks:

    {"candidate_sha", "application_tree", "cell_pair", "issue_number",
     "request_id", "c14_task_id", "c13_task_id",
     "c14_ledger_reference", "c13_ledger_reference"}
"""
from __future__ import annotations

from lite_aggregate import compute as compute_final_root
from lite_aggregate import preview_eligibility
from lite_bundle import C13_ROOT_FIELD, C14_ROOT_FIELD
from lite_bundle import validate as validate_bundle
from lite_bundle import verify_root
from lite_canonical import digest_bytes
from lite_errors import Block, Reject
import lite_candidate as candidate_module
import lite_identity as identity_module
import lite_prerequisite as prerequisite_module

CELL_PAIR = "C13+C14"

DISPATCH_FIELDS = (
    "candidate_sha",
    "application_tree",
    "cell_pair",
    "issue_number",
    "request_id",
    "c14_task_id",
    "c13_task_id",
    "c14_ledger_reference",
    "c13_ledger_reference",
)

ROLES = (("c14", "C14"), ("c13", "C13"))

OPINION_HASH_FIELDS = {
    "c14_opinion": ("c14", "opinion_sha256"),
    "c13_opinion": ("c13", "opinion_sha256"),
    "junit": ("c13", "junit_sha256"),
    "stdout": ("c13", "stdout_sha256"),
    "manifest": ("c13", "manifest_sha256"),
}


class Decision:
    """Collected outcome. ``rejects`` / ``blocks`` carry stable machine codes."""

    def __init__(self):
        self.rejects = []
        self.blocks = []
        self.notes = {}
        self.c14_root = None
        self.c13_root = None
        self.final_root = None
        self.eligibility = None
        self.independence = None

    def reject(self, reason, where):
        self.rejects.append({"reason": reason, "where": where})

    def block(self, reason, where):
        self.blocks.append({"reason": reason, "where": where})

    @property
    def decision(self):
        if self.rejects:
            return "REJECT"
        if self.blocks:
            return "BLOCK"
        return "ACCEPT"

    @property
    def ok(self):
        return self.decision == "ACCEPT"

    @property
    def reasons(self):
        return [item["reason"] for item in self.rejects] + [item["reason"] for item in self.blocks]

    def as_dict(self):
        return {
            "decision": self.decision,
            "ok": self.ok,
            "rejects": self.rejects,
            "blocks": self.blocks,
            "notes": self.notes,
            "c14_root": self.c14_root,
            "c13_root": self.c13_root,
            "FINAL_ROOT": self.final_root,
            "eligibility": self.eligibility,
            "independence": self.independence,
            "authorizes_any_action": False,
        }


def _role_task_id(dispatch, role):
    return dispatch["c14_task_id"] if role == "c14" else dispatch["c13_task_id"]


def _role_ledger_reference(dispatch, role):
    return dispatch["c14_ledger_reference"] if role == "c14" else dispatch["c13_ledger_reference"]


def _hash_artifacts(decision, artifacts, bundles):
    """Recompute the digests of the bytes actually received."""
    for name, (role, field) in OPINION_HASH_FIELDS.items():
        bundle = bundles.get(role)
        if bundle is None or field not in bundle:
            continue
        if bundle[field] is None:
            # The record declares that this artefact does not exist: a provider failure, or a
            # precheck refusal that never produced an opinion. Nothing can be bound, so neither
            # requiring the artefact nor comparing its digest would mean anything. A record that
            # *does* declare a digest is still checked and still rejected on mismatch.
            continue
        if name not in artifacts:
            decision.reject("artifact_not_supplied", name)
            continue
        if digest_bytes(artifacts[name]) != bundle[field]:
            decision.reject("artifact_digest_tamper", f"{name}:{field}")


def verify_round(
    *,
    c14_bundle,
    c13_bundle,
    c14_contract,
    c13_contract,
    dispatch,
    implementation_execution_id,
    artifacts=None,
    now=None,
) -> Decision:
    """Verify a complete round. Record problems land in the decision, not as raises."""
    decision = Decision()
    artifacts = artifacts or {}

    if not isinstance(dispatch, dict) or set(dispatch) != set(DISPATCH_FIELDS):
        decision.reject("dispatch_input_invalid", "dispatch")
        return decision
    if dispatch["cell_pair"] != CELL_PAIR:
        decision.reject("cell_pair_invalid", "dispatch")

    # --- 1. frozen candidate contracts: structure, freshness, dispatch binding ---
    for role, cell in ROLES:
        contract = c14_contract if role == "c14" else c13_contract
        if contract is None:
            decision.reject("candidate_contract_missing", role)
            continue
        try:
            candidate_module.check_binding(
                contract,
                expected_candidate_sha=dispatch["candidate_sha"],
                expected_application_tree=dispatch["application_tree"],
                expected_cell_id=cell,
                expected_task_id=_role_task_id(dispatch, role),
                expected_issue_number=dispatch["issue_number"],
                expected_request_id=dispatch["request_id"],
                now=now,
            )
        except Reject as error:
            decision.reject(error.reason, f"{role}_contract")
    if decision.rejects:
        return decision

    # --- 2. both records must exist ---
    if c14_bundle is None:
        decision.block("c14_record_missing", "c14")
    if c13_bundle is None:
        decision.block("c13_record_missing", "c13")
    if decision.blocks:
        return decision

    bundles = {"c14": c14_bundle, "c13": c13_bundle}

    # --- 3. bundle structure, root recomputation, per-cell binding ---
    for role, cell in ROLES:
        bundle = bundles[role]
        contract = c14_contract if role == "c14" else c13_contract
        try:
            validate_bundle(bundle)
            verify_root(bundle)
        except Reject as error:
            decision.reject(error.reason, role)
            continue
        if bundle["candidate_sha"] != contract["candidate_commit_sha"]:
            decision.reject("opinion_candidate_mismatch", role)
        if bundle["application_tree"] != contract["application_tree"]:
            decision.reject("application_tree_tamper", role)
        if bundle["task_id"] != _role_task_id(dispatch, role):
            decision.reject("issue_task_binding_mismatch", f"{role}:task_id")
        if dispatch["issue_number"] is not None and bundle["issue_number"] != dispatch["issue_number"]:
            decision.reject("issue_task_binding_mismatch", f"{role}:issue_number")
        if bundle["ledger_reference"] != _role_ledger_reference(dispatch, role):
            decision.reject("issue_task_binding_mismatch", f"{role}:ledger_reference")
        if bundle["nonce"] != contract["nonce"]:
            decision.reject("nonce_binding_mismatch", role)
    if decision.rejects:
        return decision

    # --- 4. tampering with the bytes is caught by re-hashing, not by trust ---
    _hash_artifacts(decision, artifacts, bundles)
    if decision.rejects:
        return decision

    decision.c14_root = c14_bundle[C14_ROOT_FIELD]
    decision.c13_root = c13_bundle[C13_ROOT_FIELD]
    decision.notes["ai_provider"] = {
        "c14": c14_bundle["ai_provider"],
        "c13": c13_bundle["ai_provider"],
    }

    # --- 5. same candidate on both sides (section 7) ---
    if c14_bundle["candidate_sha"] != c13_bundle["candidate_sha"]:
        decision.reject("c14_candidate_a_c13_candidate_b", "candidate")

    # --- 6. machine-checked independence (section 21) ---
    identities = identity_module.from_bundles(
        c14_bundle, c13_bundle, implementation_execution_id=implementation_execution_id
    )
    absent = sorted(name for name in identity_module.FIELDS if not identities.get(name))
    if absent:
        # A record may legitimately declare that no AI execution happened: a provider failure,
        # or a precheck refusal decided before any call. There is then no execution identity to
        # compare, and demanding one would force exactly the fabricated id this round removes.
        # Recorded as a note rather than a violation, because it is not one - and it cannot
        # open anything: only a BLOCKED record may have an absent execution identity (validation
        # requires it on every AI_REVIEW verdict that produced an opinion), and gate 8 blocks a
        # round whose C14 verdict is not admissible.
        decision.notes["independence_skipped"] = {"absent": absent}
    else:
        independence = identity_module.check(identities)
        decision.independence = {"ok": independence.ok, "violations": independence.violations}
        for violation in independence.violations:
            decision.reject(violation["reason"], "independence")

    # --- 7. the C14 summary C13 consumed must be the real, sealed one ---
    if not prerequisite_module.summary_matches(c13_bundle["c14_prerequisite"], c14_bundle):
        decision.reject("c13_prerequisite_not_sealed", "c13.c14_prerequisite")
    if decision.rejects:
        return decision

    # --- 8. C13 prerequisite gate (section 19) ---
    try:
        prerequisite_module.evaluate(c14_bundle, candidate_sha=dispatch["candidate_sha"], now=now)
    except Reject as error:
        decision.reject(error.reason, "c14_prerequisite")
        return decision
    except Block as error:
        decision.block(error.reason, "c14_prerequisite")
        return decision

    # --- 9. the round is only complete when C13 itself passed ---
    if c13_bundle["verdict"] != "PASS_SCOPED":
        decision.block("c13_not_pass_scoped", c13_bundle["verdict"])

    # --- 10. aggregate; CC/HK witness slots stay reserved this round ---
    decision.eligibility = preview_eligibility(c14_bundle["verdict"], c13_bundle["verdict"])
    if decision.ok:
        final = compute_final_root(
            candidate_sha=c14_bundle["candidate_sha"],
            application_tree=c14_bundle["application_tree"],
            c14_root=decision.c14_root,
            c14_verdict=c14_bundle["verdict"],
            c13_root=decision.c13_root,
            c13_verdict=c13_bundle["verdict"],
            ledger_binding={
                "cell_pair": dispatch["cell_pair"],
                "c14_task_id": dispatch["c14_task_id"],
                "c13_task_id": dispatch["c13_task_id"],
                "issue_number": dispatch["issue_number"],
                "c14_ledger_reference": dispatch["c14_ledger_reference"],
                "c13_ledger_reference": dispatch["c13_ledger_reference"],
            },
        )
        decision.final_root = final["FINAL_ROOT"]
    return decision


def require(**kwargs) -> Decision:
    """Strict form: raise on REJECT / BLOCK instead of returning a decision."""
    decision = verify_round(**kwargs)
    if decision.rejects:
        first = decision.rejects[0]
        raise Reject(first["reason"], first["where"])
    if decision.blocks:
        first = decision.blocks[0]
        raise Block(first["reason"], first["where"])
    return decision
