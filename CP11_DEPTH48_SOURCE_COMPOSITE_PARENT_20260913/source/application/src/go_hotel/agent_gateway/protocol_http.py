from __future__ import annotations

import json, uuid
from dataclasses import asdict
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .a2a import A2AAdapter,A2A_PROTOCOL_VERSION,GO_TRANSACTION_EXTENSION,build_agent_card
from .contracts import AgentContext
from .mcp import MCPAdapter,MCP_PROTOCOL_VERSION
from .rest import AgentAuthorizer
from .service import AgentTransactionGateway


def _authorize(authorize:AgentAuthorizer,authorization:str,agent_id:str,request_id:str,trace_id:str,purpose:str)->AgentContext:
    try:return authorize(authorization,agent_id,request_id,trace_id,purpose)
    except PermissionError as exc:raise HTTPException(403,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(401,detail=str(exc)) from exc


def _error(request_id,code:int,message:str,reason:str|None=None):
    data=[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":reason or message.replace(" ","_").upper(),"domain":"goaidirect.net"}]
    return {"jsonrpc":"2.0","id":request_id,"error":{"code":code,"message":message,"data":data}}


def build_mcp_router(gateway:AgentTransactionGateway,authorize:AgentAuthorizer)->APIRouter:
    router=APIRouter(tags=["mcp-2026-07-28"]);adapter=MCPAdapter(gateway)

    @router.post("/mcp")
    async def mcp(request:Request,authorization:str=Header(...,alias="Authorization"),x_go_agent_id:str=Header(...,alias="X-GO-Agent-ID"),x_go_request_id:str=Header(...,alias="X-GO-Request-ID"),x_go_trace_id:str=Header(...,alias="X-GO-Trace-ID"),x_go_purpose:str=Header(...,alias="X-GO-Purpose"),mcp_protocol_version:str=Header(...,alias="MCP-Protocol-Version"),mcp_method:str=Header(...,alias="Mcp-Method"),mcp_name:str=Header(...,alias="Mcp-Name")):
        try:body=await request.json()
        except Exception:return JSONResponse(_error(None,-32700,"Invalid JSON payload"),status_code=400)
        rpc_id=body.get("id") if isinstance(body,dict) else None
        if mcp_protocol_version!=MCP_PROTOCOL_VERSION:return JSONResponse(_error(rpc_id,-32022,"Unsupported protocol version","UNSUPPORTED_PROTOCOL_VERSION"),status_code=400)
        if not isinstance(body,dict) or body.get("jsonrpc")!="2.0" or not isinstance(body.get("method"),str):return JSONResponse(_error(rpc_id,-32600,"Request payload validation error"),status_code=400)
        method=body["method"];params=body.get("params") or {};expected=params.get("name") if method=="tools/call" else method
        if mcp_method!=method or mcp_name!=expected:return JSONResponse(_error(rpc_id,-32020,"Header mismatch","HEADER_MISMATCH"),status_code=400)
        ctx=_authorize(authorize,authorization,x_go_agent_id,x_go_request_id,x_go_trace_id,x_go_purpose)
        try:
            if method=="server/discover":result={"resultType":"complete","protocolVersion":MCP_PROTOCOL_VERSION,"serverInfo":{"name":"go-agent-transaction-gateway","version":"1.1.0"},"capabilities":{"tools":{}},"ttlMs":300000,"cacheScope":"private"}
            elif method=="tools/list":result={"resultType":"complete","tools":adapter.list_tools()["tools"],"ttlMs":300000,"cacheScope":"private"}
            elif method=="tools/call":
                envelope=await adapter.call_tool(ctx,params.get("name"),params.get("arguments") or {});structured=asdict(envelope);result={"resultType":"complete","content":[{"type":"text","text":json.dumps(structured,sort_keys=True,separators=(",",":"))}],"structuredContent":structured,"isError":False}
            else:return JSONResponse(_error(rpc_id,-32601,"Method not found"),status_code=200)
        except (ValueError,PermissionError,KeyError,TypeError) as exc:return JSONResponse(_error(rpc_id,-32602,"Invalid parameters",str(exc)),status_code=200)
        return {"jsonrpc":"2.0","id":rpc_id,"result":result}
    return router


def build_a2a_router(gateway:AgentTransactionGateway,authorize:AgentAuthorizer)->APIRouter:
    router=APIRouter(tags=["a2a-1.0"]);adapter=A2AAdapter(gateway)

    @router.get("/.well-known/agent-card.json")
    async def agent_card(request:Request):
        return JSONResponse(build_agent_card(str(request.base_url).rstrip("/")+"/a2a/v1"),media_type="application/a2a+json")

    @router.post("/a2a/v1")
    async def a2a_jsonrpc(request:Request,authorization:str=Header(...,alias="Authorization"),x_go_agent_id:str=Header(...,alias="X-GO-Agent-ID"),x_go_request_id:str=Header(...,alias="X-GO-Request-ID"),x_go_trace_id:str=Header(...,alias="X-GO-Trace-ID"),x_go_purpose:str=Header(...,alias="X-GO-Purpose"),a2a_version:str=Header(...,alias="A2A-Version")):
        try:body=await request.json()
        except Exception:return JSONResponse(_error(None,-32700,"Invalid JSON payload"),status_code=400)
        rpc_id=body.get("id") if isinstance(body,dict) else None
        if a2a_version!=A2A_PROTOCOL_VERSION:return JSONResponse(_error(rpc_id,-32600,"A2A protocol version not supported","VERSION_NOT_SUPPORTED"),status_code=400)
        if not isinstance(body,dict) or body.get("jsonrpc")!="2.0":return JSONResponse(_error(rpc_id,-32600,"Request payload validation error"),status_code=400)
        if body.get("method")!="SendMessage":return JSONResponse(_error(rpc_id,-32601,"Method not found"),status_code=200)
        params=body.get("params") or {};message=params.get("message") or {}
        if message.get("role")!="ROLE_USER" or not message.get("messageId") or not message.get("parts"):return JSONResponse(_error(rpc_id,-32602,"Invalid parameters"),status_code=200)
        if GO_TRANSACTION_EXTENSION not in set(message.get("extensions") or []):return JSONResponse(_error(rpc_id,-32602,"Invalid parameters","GO_TRANSACTION_EXTENSION_REQUIRED"),status_code=200)
        metadata=message.get("metadata") or {};skill=metadata.get("goSkill");payload=metadata.get("payload")
        if not isinstance(skill,str) or not isinstance(payload,dict):return JSONResponse(_error(rpc_id,-32602,"Invalid parameters","GO_TRANSACTION_METADATA_REQUIRED"),status_code=200)
        ctx=_authorize(authorize,authorization,x_go_agent_id,x_go_request_id,x_go_trace_id,x_go_purpose)
        try:envelope=await adapter.execute(ctx,skill,payload)
        except (ValueError,PermissionError,KeyError,TypeError) as exc:return JSONResponse(_error(rpc_id,-32602,"Invalid parameters",str(exc)),status_code=200)
        result={"message":{"messageId":str(uuid.uuid4()),"contextId":message.get("contextId") or ctx.trace_id,"role":"ROLE_AGENT","parts":[{"data":asdict(envelope),"mediaType":"application/json"}],"metadata":{"goSkill":skill,"authority":envelope.authority},"extensions":[GO_TRANSACTION_EXTENSION]}}
        return {"jsonrpc":"2.0","id":rpc_id,"result":result}
    return router
