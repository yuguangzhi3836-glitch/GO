"""The contract step of supplier onboarding (frozen decisions D-07, D-003, CHANGE 11).

Four endpoints, and the status codes say which of three different things went wrong:

* ``404`` — the thing does not exist (no onboarding case for this account).
* ``409`` — the request is well formed but the *state* does not accept it: not
  verified yet, no signed scan uploaded, a signed scan that has since been replaced,
  the contract already activated. These are all "do the earlier step first" answers.
* ``422`` — the request itself cannot be executed: the applicant did not tick that
  they agree, or confirmed a template version the server is not serving.
* ``503`` — the platform's own asset is missing (no readable contract template).
  That is not the applicant's fault and must not be dressed up as their error.

The old ``POST /bff/supplier/onboarding/contract`` took a typed
``contract_ref`` string as proof of signature and then waited for an administrator.
Both halves are gone: a typed string is not evidence, and there is no second human
review of the contract (D-003). Confirmation is now the act that activates.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from go_hotel.api.routes.bff import _document_response
from go_hotel.security.deps import supplier_account_principal
from go_hotel.security.service import Principal
from go_hotel.services.onboarding_contract import onboarding_contract_service

router = APIRouter(tags=["supplier-onboarding-contract"])

# The state cannot accept this action; the applicant has an earlier step to finish.
_CONFLICT = frozenset(
    {
        "CONTRACT_NOT_CONFIRMABLE",
        "CONTRACT_TEMPLATE_CHANGED",
        "CONTRACT_SIGNED_DOCUMENT_REQUIRED",
        "CONTRACT_SIGNED_DOCUMENT_INVALID",
        "CONTRACT_HOTEL_REQUIRED",
        "LEGAL_ENTITY_REQUIRED",
    }
)
# The request itself is not executable, whatever the state.
_UNPROCESSABLE = frozenset({"CONTRACT_AGREEMENT_REQUIRED"})
_MISSING = frozenset({"SUPPLIER_ONBOARDING_NOT_FOUND"})
_UNAVAILABLE = frozenset({"CONTRACT_TEMPLATE_UNAVAILABLE"})


def _refusal(error: str) -> HTTPException:
    code = str(error)
    if code in _MISSING:
        return HTTPException(404, detail=code)
    if code in _UNAVAILABLE:
        return HTTPException(503, detail=code)
    if code in _UNPROCESSABLE:
        return HTTPException(422, detail=code)
    if code in _CONFLICT:
        return HTTPException(409, detail=code)
    return HTTPException(409, detail=code)


class ContractConfirmationBody(BaseModel):
    """``agreed`` is a real boolean, not a convention.

    ``template_sha256`` is required: it is the hash of the version the human
    actually had on screen, and the server compares it with the template it is
    serving. A missing value is refused rather than treated as "latest", because
    "the client did not say" and "the client read this version" are different
    facts. Deliberately not a ``Literal`` — a literal rejection arrives as a
    validation payload the UI cannot translate into a sentence.
    """
    model_config = ConfigDict(extra="forbid")
    agreed: bool = Field(default=False)
    template_sha256: str = Field(default="", max_length=64)
    signed_document_id: str | None = Field(default=None, max_length=96)
    note: str | None = Field(default=None, max_length=2000)


@router.get("/bff/supplier/onboarding/contract")
def supplier_contract_state(p: Principal = Depends(supplier_account_principal)):
    try:
        return {"data": onboarding_contract_service.state(p.supplier_id)}
    except ValueError as exc:
        raise _refusal(str(exc)) from exc


@router.get("/bff/supplier/onboarding/contract/template")
def supplier_contract_template(disposition: str = "inline",
        p: Principal = Depends(supplier_account_principal)):
    """The template itself. ``inline`` for the on-screen reader, ``attachment`` to save.

    Any other value falls back to ``attachment``: the safe reading of an unknown
    disposition is "do not render this".
    """
    try:
        raw, mime, filename = onboarding_contract_service.template_bytes()
    except ValueError as exc:
        raise _refusal(str(exc)) from exc
    return _document_response(raw, mime, filename,
                              "inline" if disposition == "inline" else "attachment")


@router.post("/bff/supplier/onboarding/contract/confirm")
def supplier_contract_confirm(body: ContractConfirmationBody,
        p: Principal = Depends(supplier_account_principal)):
    try:
        return {"data": onboarding_contract_service.confirm(
            p.supplier_id, p.user_id,
            agreed=body.agreed, template_sha256=body.template_sha256,
            signed_document_id=body.signed_document_id, note=body.note)}
    except ValueError as exc:
        raise _refusal(str(exc)) from exc


@router.get("/bff/supplier/my-hotel")
def supplier_my_hotel(p: Principal = Depends(supplier_account_principal)):
    """The supplier's own hotel, for the console card (JOURNEY S11).

    Deliberately on ``supplier_account_principal`` rather than the activation gate:
    the onboarding workspace has to be able to render this before activation, and
    the answer itself distinguishes "activated" from "not yet".
    """
    try:
        return {"data": onboarding_contract_service.activation(p.supplier_id)}
    except ValueError as exc:
        raise _refusal(str(exc)) from exc
