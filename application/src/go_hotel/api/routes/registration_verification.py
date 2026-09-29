from go_hotel.services import registration_privacy
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from go_hotel.services import registration_verification as verification
from go_hotel.services.registration_terms import require_registration_terms_ready

router = APIRouter(tags=['registration-verification'])


class ChallengeBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    audience: Literal['consumer', 'supplier']
    email: str = Field(min_length=3, max_length=128)
    accepted_terms: bool = Field(strict=True)
    registration_decisions: dict[str, str] = Field(default_factory=dict)
    term_versions: dict[str, str]
    term_hashes: dict[str, str]


@router.post('/v1/registration/challenges')
def send_registration_code(body: ChallengeBody, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if not body.accepted_terms:
        raise HTTPException(422, detail='REGISTRATION_TERMS_ACCEPTANCE_REQUIRED')
    try:
        policy = require_registration_terms_ready(body.audience)
        if body.term_versions != policy['versions'] or body.term_hashes != policy['term_hashes']:
            raise ValueError('REGISTRATION_TERMS_VERSION_MISMATCH')
        registration_privacy.validate_decisions(policy,body.registration_decisions)
        return {'data': verification.issue(body.audience, body.email, request.client.host if request.client else None, policy)}
    except ValueError as exc:
        error = str(exc)
        status = 429 if error == 'REGISTRATION_CODE_RATE_LIMITED' else 503 if error in ('REGISTRATION_TERMS_NOT_READY', 'REGISTRATION_VERIFICATION_NOT_READY', 'REGISTRATION_EMAIL_SEND_FAILED') else 422
        raise HTTPException(status, detail=error, headers={'Retry-After': '60'} if status == 429 else None) from None
    except (OSError, KeyError, TypeError):
        raise HTTPException(503, detail='REGISTRATION_TERMS_UNAVAILABLE') from None
