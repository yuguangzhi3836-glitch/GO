"""Composition roots for the separately installed C14 Command Center and HK hosts.

This module connects the already bounded gate, Git bus, sandbox, durable claims,
receipt route, and machine-signature adapters.  It owns no credentials and does
not install or start a daemon.  Constructor inputs are trusted host configuration,
never Request/Task fields.
"""
from __future__ import annotations

import secrets
import time
from typing import Callable

from acceptance_gate import C14_ACTION, C14_ENVIRONMENT, Refusal
from ai_acceptance_host import AIAdmissionHost
from control_receipt_route import ControlReceiptRoute
from docker_sandbox import DockerSandbox
from durable_claims import DurableClaims
from evidence_time import utc_epoch
from git_acceptance_bus import GitAcceptanceBus


def _callable(value, reason):
    if not callable(value):
        raise Refusal(reason)
    return value


def _version(value, reason):
    if type(value) is not str or not value or len(value) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise Refusal(reason)
    return value


def _bus(value, kind, write_enabled):
    if (not isinstance(value, GitAcceptanceBus) or value.kind != kind or
            value.write_enabled is not write_enabled):
        raise Refusal("runtime_bus_role")
    return value


class CommandCenterAcceptanceHost:
    """Single C14-only composition root for issue/readback/receipt/review.

    The existing Command Center Task signer/verifier and HK runner public-key
    verifier are injected.  AI opinions remain unsigned records read through
    ``AIAdmissionHost``.  Verifying a C13 record memorizes only its content
    digest for the immediately derived C14 admission; it creates no opinion.
    """

    def __init__(self, *, opinions: AIAdmissionHost, task_bus: GitAcceptanceBus,
                 evidence_bus: GitAcceptanceBus, receipts: ControlReceiptRoute,
                 task_signer: Callable[[bytes], str],
                 task_verifier: Callable[[bytes, str], bool],
                 runner_verifier: Callable[[str, bytes, str], bool],
                 nonce_source: Callable[[], str] | None = None):
        if not isinstance(opinions, AIAdmissionHost) or not isinstance(receipts, ControlReceiptRoute):
            raise Refusal("runtime_component")
        self.opinions = opinions
        self.tasks = _bus(task_bus, "tasks", True)
        self.evidence = _bus(evidence_bus, "evidence", False)
        self.receipts = receipts
        self._task_signer = _callable(task_signer, "runtime_task_signer")
        self._task_verifier = _callable(task_verifier, "runtime_task_verifier")
        self._runner_verifier = _callable(runner_verifier, "runtime_runner_verifier")
        self._nonce_source = _callable(nonce_source or (lambda: secrets.token_urlsafe(24)),
                                       "runtime_nonce_source")
        self._verified_c13 = set()

    def authorize_candidate(self, candidate_sha, application_tree):
        return self.opinions.authorize_candidate(candidate_sha, application_tree)

    def qualify_actor(self, role, candidate_sha):
        return self.opinions.qualify_actor(role, candidate_sha)

    def verify_c13_evidence(self, reference):
        result = self.opinions.verify_c13_evidence(reference)
        if result.get("verified") is True:
            self._verified_c13.add(result.get("evidence_sha256"))
        return result

    def verify_c13_prerequisite(self, admission):
        return (type(admission) is dict and admission.get("action_id") == C14_ACTION and
                admission.get("environment") == C14_ENVIRONMENT and
                admission.get("c13_evidence_sha256") in self._verified_c13)

    def fresh_nonce(self):
        return self._nonce_source()

    def sign_house_task(self, raw):
        return self._task_signer(raw)

    def verify_house_task(self, raw, signature):
        return self._task_verifier(raw, signature)

    def publish_house_task(self, task_id, raw):
        return self.tasks.publish_house_task(task_id, raw)

    def read_house_task(self, task_id):
        return self.tasks.read_house_task(task_id)

    def verify_acceptance_runner(self, runner_id, raw, signature):
        return self._runner_verifier(runner_id, raw, signature)

    def read_house_evidence(self, task_id, nonce):
        return self.evidence.read_house_evidence(task_id, nonce)

    def read_house_artifact(self, task_id, nonce, name):
        return self.evidence.read_house_artifact(task_id, nonce, name)

    def sign_control_receipt(self, raw):
        return self.receipts.sign_control_receipt(raw)

    def verify_control_receipt(self, raw, signature):
        return self.receipts.verify_control_receipt(raw, signature)

    def publish_control_receipt(self, task_id, nonce, raw):
        return self.receipts.publish_control_receipt(task_id, nonce, raw)

    def read_control_receipt(self, task_id, nonce):
        return self.receipts.read_control_receipt(task_id, nonce)

    def c14_review_identity(self):
        return self.opinions.c14_review_identity()

    def read_review_opinion(self, reference):
        return self.opinions.read_review_opinion(reference)


class HongKongAcceptanceHost:
    """Single isolated Runner composition root used by ``c14_isolated_runner``."""

    def __init__(self, *, runner_id: str, task_bus: GitAcceptanceBus,
                 evidence_bus: GitAcceptanceBus, claims: DurableClaims,
                 sandbox: DockerSandbox, task_verifier: Callable[[bytes, str], bool],
                 evidence_signer: Callable[[bytes], str],
                 evidence_verifier: Callable[[str, bytes, str], bool],
                 agent_version: str, runner_version: str,
                 clock: Callable[[], int] | None = None):
        if (not isinstance(claims, DurableClaims) or not isinstance(sandbox, DockerSandbox) or
                claims.runner_id != runner_id):
            raise Refusal("runtime_component")
        self._runner_id = _version(runner_id, "runtime_runner_id")
        self.tasks = _bus(task_bus, "tasks", False)
        self.evidence = _bus(evidence_bus, "evidence", True)
        self.claims, self.sandbox = claims, sandbox
        self._task_verifier = _callable(task_verifier, "runtime_task_verifier")
        self._evidence_signer = _callable(evidence_signer, "runtime_evidence_signer")
        self._evidence_verifier = _callable(evidence_verifier, "runtime_evidence_verifier")
        self._agent_version = _version(agent_version, "runtime_agent_version")
        self._runner_version = _version(runner_version, "runtime_runner_version")
        self._clock = _callable(clock or (lambda: int(time.time())), "runtime_clock")

    def registered_runner_id(self):
        return self._runner_id

    def verify_house_task(self, raw, signature):
        return self._task_verifier(raw, signature)

    def read_house_task(self, task_id):
        return self.tasks.read_house_task(task_id)

    def task_is_fresh(self, task, epoch):
        try:
            return (type(epoch) is int and utc_epoch(task["issued_at"], "runner_task_time") <= epoch <=
                    utc_epoch(task["expires_at"], "runner_task_time"))
        except (KeyError, TypeError):
            return False

    def now_epoch(self):
        value = self._clock()
        if type(value) is not int or value < 0:
            raise Refusal("runtime_clock")
        return value

    def claim_task_once(self, task_id, nonce):
        return self.claims.claim_task_once(task_id, nonce)

    def run_fixed_isolated_suite(self, candidate, tree, commands):
        return self.sandbox.run_fixed_isolated_suite(candidate, tree, commands)

    def agent_version(self):
        return self._agent_version

    def runner_version(self):
        return self._runner_version

    def sign_acceptance_evidence(self, raw):
        return self._evidence_signer(raw)

    def verify_acceptance_runner(self, runner_id, raw, signature):
        if runner_id != self._runner_id:
            return False
        return self._evidence_verifier(runner_id, raw, signature)

    def publish_house_artifact(self, task_id, nonce, name, raw):
        return self.evidence.publish_house_artifact(task_id, nonce, name, raw)

    def publish_house_evidence(self, task_id, nonce, raw):
        return self.evidence.publish_house_evidence(task_id, nonce, raw)

