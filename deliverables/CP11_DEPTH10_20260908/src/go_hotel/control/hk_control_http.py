"""FastAPI transport adapter for the HK Staging Control Plane.

TLS/mTLS termination is expected at the approved reverse proxy. This router exposes
only the signed control envelope endpoint and a non-sensitive health endpoint.
It never accepts a command string, executable path, or arbitrary shell payload.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .hk_control_service import HKControlService
from .hk_control_replay_store import PostgresControlReplayStore
from .hk_control_handlers import build_hk_control_handlers


router = APIRouter(prefix="/internal/v1/hk-control", tags=["hk-control"])


class ControlEnvelopeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    task_type: str
    environment: str
    authority: str
    candidate_sha256: str
    task_sha256: str
    payload: dict
    node_id: str
    nonce: str
    issued_at: str
    signature: str


def _secret() -> bytes:
    value = os.getenv("GO_HK_CONTROL_HMAC_KEY", "").encode("utf-8")
    if len(value) < 32:
        raise RuntimeError("HK_CONTROL_HMAC_KEY_NOT_READY")
    return value


def _node_id() -> str:
    value = str(os.getenv("GO_HK_CONTROL_NODE_ID") or "").strip()
    if not value:
        raise RuntimeError("HK_CONTROL_NODE_ID_NOT_READY")
    return value


def _service() -> HKControlService:
    return HKControlService(
        secret=_secret(),
        node_id=_node_id(),
        replay_guard=PostgresControlReplayStore(),
        handlers=build_hk_control_handlers(),
    )


@router.get("/health")
def health():
    # Never expose token/key/candidate details here.
    try:
        node_ready = bool(_node_id())
        key_ready = bool(_secret())
    except RuntimeError:
        node_ready = bool(os.getenv("GO_HK_CONTROL_NODE_ID"))
        key_ready = len(os.getenv("GO_HK_CONTROL_HMAC_KEY", "")) >= 32
    return {
        "service": "GO_HK_CONTROL",
        "environment": "HK_STAGING",
        "node_identity_ready": node_ready,
        "signing_key_ready": key_ready,
        "arbitrary_shell": False,
    }


@router.post("/tasks")
def submit_task(body: ControlEnvelopeBody, request: Request):
    # Reverse proxy must inject a verified mTLS assertion when mTLS is enabled.
    # If the deployment requires mTLS, missing assertion fails closed.
    if str(os.getenv("GO_HK_CONTROL_REQUIRE_MTLS", "true")).lower() in {"1", "true", "yes"}:
        if request.headers.get("x-go-mtls-verified") != "SUCCESS":
            raise HTTPException(status_code=403, detail="HK_CONTROL_MTLS_REQUIRED")
    try:
        return _service().submit(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
