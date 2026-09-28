"""Public read-only legal text, not a mechanism to approve or publish terms."""
from fastapi import APIRouter, HTTPException, Query, Response
from typing import Literal
from go_hotel.services.registration_terms import registration_terms_status, read_registration_term

router = APIRouter(tags=['registration-terms'])


@router.get('/v1/registration-terms')
def terms_index(response: Response, audience: Literal['consumer', 'supplier'] = Query(...)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return {'data': registration_terms_status(audience)}
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(503, detail='REGISTRATION_TERMS_UNAVAILABLE') from exc


@router.get('/v1/registration-terms/{term_id}/{version}')
def terms_document(term_id: str, version: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    try:
        return {'data': read_registration_term(term_id, version)}
    except ValueError as exc:
        if str(exc) == 'REGISTRATION_TERMS_NOT_FOUND':
            raise HTTPException(404, detail=str(exc)) from exc
        raise HTTPException(503, detail='REGISTRATION_TERMS_UNAVAILABLE') from exc
    except (OSError, KeyError) as exc:
        raise HTTPException(503, detail='REGISTRATION_TERMS_UNAVAILABLE') from exc
