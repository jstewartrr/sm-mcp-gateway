"""
Sovereign Mind MCP Gateway
===========================
A unified MCP server that proxies requests to multiple backend MCP servers.
Provides ABBI and other voice interfaces with single-connection access to the entire SM ecosystem.

Supports both HTTP POST (/mcp) and SSE (/sse) transports.

Architecture:
    ABBI → SM Gateway → [Snowflake, Asana, Make, GitHub, Gemini, ...]
"""

import os
import json
import asyncio
import httpx
import uuid
import queue
import threading
from flask import Flask, request, jsonify, Response
from functools import wraps
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =============================================================================
# BACKEND MCP SERVER CONFIGURATION
# =============================================================================

BACKEND_MCPS = {
    "snowflake": {
        "url": os.environ.get("MCP_SNOWFLAKE_URL", "https://john-claude-mcp.wittyplant-239da1c3.eastus.azurecontainerapps.io/mcp"),
        "prefix": "sm",
        "description": "Sovereign Mind Snowflake database (JOHN_CLAUDE user)",
        "enabled": True
    },
    "asana": {
        "url": os.environ.get("MCP_ASANA_URL", "https://mcp.asana.com/sse"),
        "prefix": "asana",
        "description": "Asana task and project management",
        "enabled": False  # Disabled - requires OAuth, use direct connection
    },
    "make": {
        "url": os.environ.get("MCP_MAKE_URL", "https://mcp.make.com"),
        "prefix": "make",
        "description": "Make.com automation scenarios",
        "enabled": False  # Disabled - requires OAuth
    },
    "github": {
        "url": os.environ.get("MCP_GITHUB_URL", "https://github-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp"),
        "prefix": "github",
        "description": "GitHub repositories",
        "enabled": True
    },
    "gemini": {
        "url": os.environ.get("MCP_GEMINI_URL", "https://gemini-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "gemini",
        "description": "Google Gemini AI",
        "enabled": True
    },
    "notebooklm": {
        "url": os.environ.get("MCP_NOTEBOOKLM_URL", "https://notebooklm-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "notebook",
        "description": "NotebookLM notebooks",
        "enabled": True
    },
    "vertex": {
        "url": os.environ.get("MCP_VERTEX_URL", "https://vertex-ai-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "vertex",
        "description": "Vertex AI (Imagen, Vision, Document AI)",
        "enabled": True
    },
    "azure": {
        "url": os.environ.get("MCP_AZURE_URL", "https://azure-cli-mcp.calmsmoke-f302257e.eastus.azurecontainerapps.io/mcp"),
        "prefix": "azure",
        "description": "Azure CLI commands",
        "enabled": True
    },
    "elevenlabs": {
        "url": os.environ.get("MCP_ELEVENLABS_URL", "https://elevenlabs-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp"),
        "prefix": "voice",
        "description": "ElevenLabs voice agents",
        "enabled": True
    },
    "simli": {
        "url": os.environ.get("MCP_SIMLI_URL", "https://simli-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "avatar",
        "description": "Simli visual avatars",
        "enabled": True
    },
    "vectorizer": {
        "url": os.environ.get("MCP_VECTORIZER_URL", "https://slide-transform-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "vector",
        "description": "Image vectorization and slide transformation",
        "enabled": True
    },
    "figma": {
        "url": os.environ.get("MCP_FIGMA_URL", "https://figma-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "figma",
        "description": "Figma design files (read-only)",
        "enabled": True
    }
}

# =============================================================================
# TOOL CATALOG CACHE
# =============================================================================

class ToolCatalog:
    """Manages the unified tool catalog from all backend MCPs."""
    
    def __init__(self):
        self.tools = {}  # prefixed_name -> {backend, original_name, schema}
        self.last_refresh = None
        self.refresh_interval = 300  # 5 minutes
    
    def needs_refresh(self):
        if self.last_refresh is None:
            return True
        return (datetime.now() - self.last_refresh).seconds > self.refresh_interval
    
    async def refresh(self):
        """Fetch tool schemas from all enabled backend MCPs."""
        logger.info("Refreshing tool catalog from backend MCPs...")
        new_tools = {}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for backend_name, config in BACKEND_MCPS.items():
                if not config.get("enabled", False):
                    continue
                
                try:
                    # Fetch tools/list from backend
                    response = await client.post(
                        config["url"],
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/list",
                            "params": {}
                        },
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        tools = data.get("result", {}).get("tools", [])
                        prefix = config["prefix"]
                        
                        for tool in tools:
                            original_name = tool["name"]
                            prefixed_name = f"{prefix}_{original_name}"
                            
                            new_tools[prefixed_name] = {
                                "backend": backend_name,
                                "backend_url": config["url"],
                                "original_name": original_name,
                                "schema": {
                                    "name": prefixed_name,
                                    "description": f"[{prefix.upper()}] {tool.get('description', '')}",
                                    "inputSchema": tool.get("inputSchema", {})
                                }
                            }
                        
                        logger.info(f"  ✓ {backend_name}: {len(tools)} tools loaded")
                    else:
                        logger.warning(f"  ✗ {backend_name}: HTTP {response.status_code}")
                        
                except Exception as e:
                    logger.warning(f"  ✗ {backend_name}: {str(e)}")
        
        self.tools = new_tools
        self.last_refresh = datetime.now()
        logger.info(f"Tool catalog refreshed: {len(self.tools)} total tools")
    
    def get_all_tools(self):
        """Return all tool schemas for tools/list response."""
        return [t["schema"] for t in self.tools.values()]
    
    def get_tool(self, prefixed_name):
        """Get tool info by prefixed name."""
        return self.tools.get(prefixed_name)


# Global catalog instance
catalog = ToolCatalog()

# SSE session management
sse_sessions = {}  # session_id -> queue

# =============================================================================
# MCP PROTOCOL HANDLERS
# =============================================================================

def run_async(coro):
    """Helper to run async code from sync Flask handlers."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def call_backend_tool(backend_url: str, tool_name: str, arguments: dict):
    """Forward a tool call to a backend MCP server."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            backend_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            },
            headers={"Content-Type": "application/json"}
        )
        return response.json()


def handle_initialize(params):
    """Handle MCP initialize request."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": True}
        },
        "serverInfo": {
            "name": "sovereign-mind-gateway",
            "version": "1.0.0"
        }
    }


def handle_tools_list(params):
    """Handle tools/list request - return unified catalog."""
    if catalog.needs_refresh():
        run_async(catalog.refresh())
    
    return {"tools": catalog.get_all_tools()}


def handle_tools_call(params):
    """Handle tools/call request - route to appropriate backend."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    
    # Look up tool in catalog
    tool_info = catalog.get_tool(tool_name)
    if not tool_info:
        return {
            "content": [{
                "type": "text",
                "text": f"Error: Unknown tool '{tool_name}'"
            }],
            "isError": True
        }
    
    # Forward to backend
    try:
        result = run_async(call_backend_tool(
            tool_info["backend_url"],
            tool_info["original_name"],
            arguments
        ))
        
        # Extract result from JSON-RPC response
        if "result" in result:
            return result["result"]
        elif "error" in result:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Backend error: {result['error']}"
                }],
                "isError": True
            }
        else:
            return result
            
    except Exception as e:
        logger.error(f"Error calling backend tool: {e}")
        return {
            "content": [{
                "type": "text",
                "text": f"Error calling tool: {str(e)}"
            }],
            "isError": True
        }


def process_mcp_message(data):
    """Process an MCP JSON-RPC message and return the response."""
    method = data.get("method", "")
    params = data.get("params", {})
    request_id = data.get("id", 1)
    
    logger.info(f"MCP request: {method}")
    
    # Route to appropriate handler
    if method == "initialize":
        result = handle_initialize(params)
    elif method == "tools/list":
        result = handle_tools_list(params)
    elif method == "tools/call":
        result = handle_tools_call(params)
    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }
    
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    }


# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route("/", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "sovereign-mind-gateway",
        "version": "1.0.0",
        "transports": ["http (/mcp)", "sse (/sse)"],
        "backends": {
            name: {
                "enabled": cfg.get("enabled", False),
                "prefix": cfg.get("prefix", "")
            }
            for name, cfg in BACKEND_MCPS.items()
        },
        "total_tools": len(catalog.tools) if catalog.tools else "not yet loaded"
    })


@app.route("/mcp", methods=["POST"])
def mcp_handler():
    """Main MCP JSON-RPC endpoint (HTTP POST transport)."""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }), 400
        
        response = process_mcp_message(data)
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id", 1) if data else 1,
            "error": {"code": -32603, "message": str(e)}
        }), 500


@app.route("/sse", methods=["GET"])
def sse_connect():
    """SSE endpoint - establishes event stream connection."""
    session_id = str(uuid.uuid4())
    sse_sessions[session_id] = queue.Queue()
    
    logger.info(f"SSE connection established: {session_id}")
    
    def generate():
        # Send the endpoint URL for POST messages
        yield f"event: endpoint\ndata: /sse/{session_id}/message\n\n"
        
        # Keep connection alive and send any queued responses
        while True:
            try:
                # Wait for messages with timeout for keepalive
                try:
                    message = sse_sessions[session_id].get(timeout=30)
                    yield f"event: message\ndata: {json.dumps(message)}\n\n"
                except queue.Empty:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                break
        
        # Cleanup
        if session_id in sse_sessions:
            del sse_sessions[session_id]
        logger.info(f"SSE connection closed: {session_id}")
    
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.route("/sse/<session_id>/message", methods=["POST"])
def sse_message(session_id):
    """Handle incoming messages for an SSE session."""
    if session_id not in sse_sessions:
        return jsonify({"error": "Session not found"}), 404
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data"}), 400
        
        # Process the MCP message
        response = process_mcp_message(data)
        
        # Queue the response to be sent via SSE
        sse_sessions[session_id].put(response)
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        logger.error(f"SSE message error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/refresh", methods=["POST"])
def force_refresh():
    """Force refresh the tool catalog."""
    run_async(catalog.refresh())
    return jsonify({
        "status": "refreshed",
        "total_tools": len(catalog.tools),
        "timestamp": catalog.last_refresh.isoformat() if catalog.last_refresh else None
    })


@app.route("/tools", methods=["GET"])
def list_tools():
    """Human-readable tool listing."""
    if catalog.needs_refresh():
        run_async(catalog.refresh())
    
    tools_by_backend = {}
    for name, info in catalog.tools.items():
        backend = info["backend"]
        if backend not in tools_by_backend:
            tools_by_backend[backend] = []
        tools_by_backend[backend].append({
            "prefixed_name": name,
            "original_name": info["original_name"],
            "description": info["schema"].get("description", "")
        })
    
    return jsonify({
        "total_tools": len(catalog.tools),
        "backends": tools_by_backend
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Pre-load tool catalog on startup
    logger.info("Sovereign Mind MCP Gateway starting...")
    run_async(catalog.refresh())
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
