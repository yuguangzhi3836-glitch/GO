from __future__ import annotations
from fastapi import FastAPI
from .auth import protocol_authorizer
from .lifecycle_core import GoTransactionCore
from .contracts import AgentProtocol
from .protocol_http import build_a2a_router,build_mcp_router
from .rest import build_agent_router
from .service import AgentTransactionGateway

gateway=AgentTransactionGateway(GoTransactionCore())

def install_agent_gateway(app:FastAPI)->None:
    app.include_router(build_agent_router(gateway,protocol_authorizer({AgentProtocol.REST,AgentProtocol.APPLE_APP_INTENTS})))
    app.include_router(build_mcp_router(gateway,protocol_authorizer({AgentProtocol.MCP})))
    app.include_router(build_a2a_router(gateway,protocol_authorizer({AgentProtocol.A2A})))
