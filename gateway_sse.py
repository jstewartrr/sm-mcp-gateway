"""
Sovereign Mind MCP Gateway - SSE Transport
==========================================
SSE (Server-Sent Events) transport wrapper for ElevenLabs compatibility.
ElevenLabs requires SSE transport, not the standard streamable_http.

This wraps the main gateway to serve over SSE for ABBI.
"""

import os
import json
import logging
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response
from mcp.server.sse import SseServerTransport

# Import all tools from the main gateway
from gateway import mcp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sm_gateway_sse")

# Create SSE transport
sse_transport = SseServerTransport("/messages")

async def handle_sse(request):
    """Handle SSE connection for MCP clients."""
    logger.info(f"SSE connection from {request.client}")
    async with sse_transport.connect_sse(
        request.scope, 
        request.receive, 
        request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0],
            streams[1],
            mcp._mcp_server.create_initialization_options()
        )
    return Response()

async def handle_health(request):
    """Health check endpoint."""
    return Response(
        content=json.dumps({"status": "healthy", "transport": "sse"}),
        media_type="application/json"
    )

# Create Starlette app with SSE routes
app = Starlette(
    debug=True,
    routes=[
        Route("/health", handle_health),
        Route("/sse", handle_sse),
        Mount("/messages", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
