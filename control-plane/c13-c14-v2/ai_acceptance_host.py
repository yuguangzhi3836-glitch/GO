"""Host-side AI identity qualification and content-addressed C13 readback.

Registration objects and the verdict directory MUST come from installed host
trust configuration, never a Request, candidate checkout or verdict itself.
This adapter consumes public keys only; it cannot register, sign or dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from acceptance_gate import C13_ENVIRONMENT, C14_ENVIRONMENT, Refusal
import c13_attestation as c13


@dataclass(frozen=True)
class AIRegistration:
    actor_id: str
    principal_id: str
    role: str
    side: str
    public_spki_pem: bytes
    key_fingerprint_sha256: str
    kind: str = "AI"

    def validate(self, role: str) -> None:
        side = {"C13": "development", "C14": "runtime"}[role]
        if (self.kind != "AI" or self.role != role or self.side != side or
                any(type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", value)
                    for value in (self.actor_id, self.principal_id))):
            raise Refusal("ai_registration_identity")
        try:
            public = serialization.load_pem_public_key(self.public_spki_pem)
            der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        except (TypeError, ValueError) as exc:
            raise Refusal("ai_registration_public_key") from exc
        valid_algorithm = (isinstance(public, ec.EllipticCurvePublicKey) and
                           isinstance(public.curve, ec.SECP256R1)) if role == "C13" else isinstance(public, ed25519.Ed25519PublicKey)
        if not valid_algorithm or hashlib.sha256(der).hexdigest() != self.key_fingerprint_sha256:
            raise Refusal("ai_registration_key_binding")


class AIAdmissionHost:
    """Implement the acceptance gate's Host using separately supplied trust.

    The trusted installer must establish principal separation, key custody and
    revocation before constructing this snapshot. Distinct names alone do not
    prove operational independence. Reconstruct it after trust updates.
    C13 qualification deliberately does not require a C14 registration.
    """

    def __init__(self, implementation_principal: str, reviewer: AIRegistration,
                 verdict_root: Path, artifact_zip: bytes,
                 runner: AIRegistration | None = None):
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

    def verify_c13_evidence(self, reference: str) -> dict:
        if type(reference) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", reference):
            raise Refusal("c13_content_reference")
        # Host-provisioned absolute directory, read-only access; no caller paths.
        if not self.verdict_root.is_absolute():
            raise Refusal("c13_verdict_root")
        root_fd = file_fd = None
        try:
            root_fd = os.open(self.verdict_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            file_fd = os.open(reference[7:] + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=root_fd)
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise Refusal("c13_verdict_file")
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
        try:
            return c13.verify(raw, self.artifact_zip, self.reviewer.public_spki_pem,
                              self.reviewer.actor_id)
        except c13.Refusal as exc:
            raise Refusal(str(exc)) from exc
