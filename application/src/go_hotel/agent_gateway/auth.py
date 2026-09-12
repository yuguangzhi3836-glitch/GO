from __future__ import annotations
from collections.abc import Iterable
from .contracts import AgentContext,AgentProtocol

ISSUER='GO_COMMAND_CENTER'
AUDIENCE='GO_AGENT_GATEWAY'
TOKEN_TYPE='GO_AGENT_ACCESS'

def signed_agent_authorizer(authorization:str,agent_id:str,request_id:str,trace_id:str,purpose:str)->AgentContext:
    if not authorization.startswith('Bearer '):raise ValueError('AGENT_BEARER_REQUIRED')
    from go_hotel.security.crypto import decode_jwt
    claims=decode_jwt(authorization[7:].strip())
    if claims.get('typ')!=TOKEN_TYPE or claims.get('iss')!=ISSUER or claims.get('aud')!=AUDIENCE:raise ValueError('INVALID_AGENT_TOKEN')
    if claims.get('agent_id')!=agent_id or claims.get('sub')!=agent_id:raise PermissionError('AGENT_IDENTITY_MISMATCH')
    purposes=claims.get('purposes') or []
    if not isinstance(purposes,list) or purpose not in purposes:raise PermissionError('AGENT_PURPOSE_NOT_AUTHORIZED')
    scopes=claims.get('scopes') or []
    if not isinstance(scopes,list) or any(not isinstance(x,str) for x in scopes):raise ValueError('INVALID_AGENT_SCOPES')
    traveler=claims.get('traveler_ref')
    if traveler is not None and not isinstance(traveler,str):raise ValueError('INVALID_TRAVELER_REFERENCE')
    try:protocol=AgentProtocol(claims.get('protocol'))
    except (ValueError,TypeError):raise ValueError('INVALID_AGENT_PROTOCOL') from None
    return AgentContext(request_id,trace_id,agent_id,protocol,purpose,frozenset(scopes),traveler)

def protocol_authorizer(protocols:Iterable[AgentProtocol]):
    allowed=frozenset(protocols)
    def authorize(authorization:str,agent_id:str,request_id:str,trace_id:str,purpose:str)->AgentContext:
        ctx=signed_agent_authorizer(authorization,agent_id,request_id,trace_id,purpose)
        if ctx.protocol not in allowed:raise PermissionError('AGENT_PROTOCOL_MISMATCH')
        return ctx
    return authorize
