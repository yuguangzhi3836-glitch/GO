"""Independent AI group provenance and content-addressed opinion readback.

Group/execution facts and the recorded opinion directory come from the trusted
review recorder, never a Request or candidate checkout. No AI keys/signatures.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from acceptance_gate import C13_ENVIRONMENT, C14_ENVIRONMENT, Refusal
import c13_attestation as c13


@dataclass(frozen=True)
class AIReviewGroup:
    actor_id: str
    principal_id: str
    role: str
    side: str
    kind: str = "AI"

    def validate(self, role: str) -> None:
        side = {"C13": "development", "C14": "runtime"}[role]
        if (self.kind != "AI" or self.role != role or self.side != side or
                any(type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", value)
                    for value in (self.actor_id, self.principal_id))):
            raise Refusal("ai_registration_identity")


# Compatibility name only: this is review provenance, not signing registration.
AIRegistration = AIReviewGroup


class AIAdmissionHost:
    """Implement the acceptance gate's Host using separately supplied trust.

    principal_id denotes the actual independent AI execution/context, not a
    GitHub account or a signing principal. The recorder checks that separation
    from the implementation and other group. Names alone do not prove it.
    Both groups may share a GitHub account; neither needs keys or signatures.
    """

    def __init__(self, implementation_principal: str, reviewer: AIReviewGroup,
                 verdict_root: Path, artifact_zip: bytes,
                 runner: AIReviewGroup | None = None):
        if type(implementation_principal) is not str or not implementation_principal:
            raise Refusal("implementation_principal")
        reviewer.validate("C13")
        if reviewer.principal_id == implementation_principal:
            raise Refusal("ai_principal_not_independent")
        if runner is not None:
            runner.validate("C14")
            if (runner.principal_id in {implementation_principal, reviewer.principal_id} or
                    runner.actor_id == reviewer.actor_id):
                raise Refusal("ai_principal_not_independent")
        self.reviewer, self.runner = reviewer, runner
        self.verdict_root, self.artifact_zip = Path(verdict_root), artifact_zip

    def authorize_candidate(self, candidate_sha: str, application_tree: str) -> bool:
        return (candidate_sha, application_tree) == (c13.CANDIDATE, c13.TREE)

    def qualify_actor(self, role: str, candidate_sha: str) -> dict:
        if candidate_sha != c13.CANDIDATE or role not in {"C13", "C14"}:
            raise Refusal("ai_registration_scope")
        actor = self.reviewer if role == "C13" else self.runner
        if actor is None:
            raise Refusal("ai_registration_missing")
        return {"id": actor.actor_id, "role": role, "registered": True,
                "environment": C13_ENVIRONMENT if role == "C13" else C14_ENVIRONMENT,
                "independent_of": ["implementation"] if role == "C13" else ["implementation", "c13"]}

    def read_review_opinion(self, reference: str) -> bytes:
        if type(reference) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", reference):
            raise Refusal("c13_content_reference")
        # Host-provisioned absolute directory, read-only access; no caller paths.
        if not self.verdict_root.is_absolute():
            raise Refusal("c13_verdict_root")
        root_fd = file_fd = None
        try:
            root_fd = os.open(self.verdict_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            root_info = os.fstat(root_fd)
            if root_info.st_uid != os.geteuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
                raise Refusal("review_store_permissions")
            file_fd = os.open(reference[7:] + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=root_fd)
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode):
                raise Refusal("c13_verdict_file")
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise Refusal("review_file_permissions")
            with os.fdopen(file_fd, "rb") as stream:
                file_fd = None
                raw = stream.read(16385)
        except OSError as exc:
            raise Refusal("c13_verdict_readback") from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if root_fd is not None:
                os.close(root_fd)
        if len(raw) > 16384 or hashlib.sha256(raw).hexdigest() != reference[7:]:
            raise Refusal("c13_content_digest")
        return raw

    def verify_c13_evidence(self, reference: str) -> dict:
        try:
            return c13.verify(self.read_review_opinion(reference), self.artifact_zip,
                              self.reviewer.actor_id, self.reviewer.principal_id)
        except c13.Refusal as exc:
            raise Refusal(str(exc)) from exc

    def c14_review_identity(self) -> tuple[str, str]:
        if self.runner is None:
            raise Refusal("ai_registration_missing")
        return self.runner.actor_id, self.runner.principal_id
