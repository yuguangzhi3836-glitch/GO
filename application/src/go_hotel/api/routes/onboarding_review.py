"""GO-side onboarding review surface.

An authorised reviewer opens a queue of cases that are waiting for a human
(UNDER_REVIEW, CLAIM_CONFLICT), reads one case with the applicant's private
evidence, and takes one of three decisions. The private-evidence read path
shipped in Batch 3 lives here too, so the review console has exactly one entry
point and the console's permission can be checked in one place.

Authorisation is ``admin:onboarding_review`` (frozen decision D-10), held by
GO_GOVERNANCE alone. An ordinary admin with ``admin:read`` gets 403 here, which is
the boundary that keeps an operator out of an applicant's legal documents.

Status mapping, and why it is not uniform:
  404  the case does not exist
  422  the request itself cannot be acted on (unknown decision, a NEEDS_CHANGES
       with no finding, a free-text-only finding, a missing reopen or conflict
       reason) — the caller must change the request before retrying
  409  the request is well-formed but the case is not in a state that accepts it
       (already decided, conflict not resolved yet, unconfirmed destructive act)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from go_hotel.security.deps import onboarding_reviewer_principal
from go_hotel.security.service import Principal
from go_hotel.services import onboarding_review as review
from go_hotel.services.legal_entity_document import legal_entity_document_service
from go_hotel.services.onboarding_review import onboarding_review_service

router = APIRouter(prefix='/internal/v1/onboarding-review', tags=['go-onboarding-review'])

# Refusals that mean "this request cannot be acted on as written", as opposed to
# "this request is fine but the case is not ready". The distinction matters to the
# console: one is a form to fix, the other is a state to re-read.
_UNPROCESSABLE = frozenset({
    review.DECISION_INVALID,
    review.FINDINGS_REQUIRED,
    review.FINDING_SHAPE_INVALID,
    review.REOPEN_REASON_REQUIRED,
    review.CLAIM_CONFLICT_RESOLUTION_INVALID,
    review.CLAIM_CONFLICT_REASON_REQUIRED,
})


def _refusal(error: ValueError) -> HTTPException:
    code = str(error)
    if code == review.CASE_NOT_FOUND:
        return HTTPException(404, detail=code)
    if code in _UNPROCESSABLE or code.startswith(review.FINDING_CODE_INVALID + ':'):
        return HTTPException(422, detail=code)
    return HTTPException(409, detail=code)


class ReviewDecisionBody(BaseModel):
    """One reviewer decision.

    ``decision`` is a plain string rather than a Literal on purpose: a Literal
    rejection arrives as an untranslatable validation payload, so the console
    could neither show the reason nor offer the valid choices.
    """
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=2000)
    findings: list[Any] | None = None


class ReviewReopenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class ReviewConflictBody(BaseModel):
    """Resolving a hotel conflict takes the hotel away from somebody.

    ``confirmed`` is a separate field rather than a convention, because "the
    reviewer clicked twice" has to be checkable, not inferred.
    """
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(min_length=1, max_length=48)
    reason: str = Field(min_length=1, max_length=500)
    confirmed: bool = False


def _document_response(raw: bytes, mime: str, filename: str, disposition: str) -> Response:
    from urllib.parse import quote

    ascii_fallback = ''.join(c if 32 <= ord(c) < 127 and c not in '"\\' else '_' for c in filename) or 'document'
    return Response(content=raw, media_type=mime, headers={
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}",
    })


# --- the queue and one case ------------------------------------------------
@router.get('/cases')
def review_queue(states: str | None = None, limit: int = 25, offset: int = 0,
                 p: Principal = Depends(onboarding_reviewer_principal)):
    wanted = [s.strip().upper() for s in states.split(',') if s.strip()] if states else None
    return {'data': onboarding_review_service.queue(states=wanted, limit=limit, offset=offset)}


@router.get('/cases/{supplier_id}')
def review_case(supplier_id: str, p: Principal = Depends(onboarding_reviewer_principal)):
    try:
        return {'data': onboarding_review_service.detail(supplier_id)}
    except ValueError as e:
        raise _refusal(e) from e


# --- the three-state decision ---------------------------------------------
@router.post('/cases/{supplier_id}/decision')
def review_decide(supplier_id: str, body: ReviewDecisionBody = Body(...),
                  p: Principal = Depends(onboarding_reviewer_principal)):
    try:
        return {'data': onboarding_review_service.decide(
            supplier_id, p.user_id, body.decision, body.note, body.findings)}
    except ValueError as e:
        raise _refusal(e) from e


@router.post('/cases/{supplier_id}/reopen')
def review_reopen(supplier_id: str, body: ReviewReopenBody = Body(...),
                  p: Principal = Depends(onboarding_reviewer_principal)):
    try:
        return {'data': onboarding_review_service.reopen(supplier_id, p.user_id, body.reason)}
    except ValueError as e:
        raise _refusal(e) from e


@router.post('/cases/{supplier_id}/resolve-conflict')
def review_resolve_conflict(supplier_id: str, body: ReviewConflictBody = Body(...),
                            p: Principal = Depends(onboarding_reviewer_principal)):
    try:
        return {'data': onboarding_review_service.resolve_conflict(
            supplier_id, p.user_id, body.resolution, body.reason, body.confirmed)}
    except ValueError as e:
        raise _refusal(e) from e


# --- applicant private evidence -------------------------------------------
@router.get('/documents/{document_id}')
def reviewer_document_meta(document_id: str, p: Principal = Depends(onboarding_reviewer_principal)):
    try:
        return {'data': legal_entity_document_service.meta_for_reviewer(document_id)}
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e


@router.get('/documents/{document_id}/content')
def reviewer_document_content(document_id: str, disposition: str = 'inline',
                              p: Principal = Depends(onboarding_reviewer_principal)):
    """A reviewer previews by default; ``disposition=attachment`` downloads."""
    inline = disposition != 'attachment'
    try:
        raw, mime, filename, resolved = legal_entity_document_service.read_for_reviewer(
            document_id, inline=inline)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    return _document_response(raw, mime, filename, resolved)
