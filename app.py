"""
Sovereign Mind MCP Gateway v1.5.0
=================================
A unified MCP server with integrated web scraper support.
Added: Tailscale MCP backend for network management
"""

import os
import json
import asyncio
import httpx
import uuid
import queue
import subprocess
import sys
import re
from flask import Flask, request, jsonify, Response
import logging
from datetime import datetime

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
        "enabled": True,
        "transport": "json"
    },
    "googledrive": {
        "url": os.environ.get("MCP_GOOGLEDRIVE_URL", "https://google-drive-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "drive",
        "description": "Google Drive file access (service account)",
        "enabled": True,
        "transport": "json"
    },
    "github": {
        "url": os.environ.get("MCP_GITHUB_URL", "https://github-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp"),
        "prefix": "github",
        "description": "GitHub repositories",
        "enabled": True,
        "transport": "json"
    },
    "gemini": {
        "url": os.environ.get("MCP_GEMINI_URL", "https://gemini-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "gemini",
        "description": "Google Gemini AI",
        "enabled": True,
        "transport": "json"
    },
    "notebooklm": {
        "url": os.environ.get("MCP_NOTEBOOKLM_URL", "https://notebooklm-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "notebook",
        "description": "NotebookLM notebooks",
        "enabled": True,
        "transport": "json"
    },
    "vertex": {
        "url": os.environ.get("MCP_VERTEX_URL", "https://vertex-ai-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "vertex",
        "description": "Vertex AI (Imagen, Vision, Document AI)",
        "enabled": True,
        "transport": "json"
    },
    "azure": {
        "url": os.environ.get("MCP_AZURE_URL", "https://azure-cli-mcp.calmsmoke-f302257e.eastus.azurecontainerapps.io/mcp"),
        "prefix": "azure",
        "description": "Azure CLI commands",
        "enabled": True,
        "transport": "json"
    },
    "elevenlabs": {
        "url": os.environ.get("MCP_ELEVENLABS_URL", "https://elevenlabs-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp"),
        "prefix": "voice",
        "description": "ElevenLabs voice agents",
        "enabled": True,
        "transport": "json"
    },
    "simli": {
        "url": os.environ.get("MCP_SIMLI_URL", "https://simli-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "avatar",
        "description": "Simli visual avatars",
        "enabled": True,
        "transport": "json"
    },
    "vectorizer": {
        "url": os.environ.get("MCP_VECTORIZER_URL", "https://slide-transform-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "vector",
        "description": "Image vectorization and slide transformation",
        "enabled": True,
        "transport": "json"
    },
    "figma": {
        "url": os.environ.get("MCP_FIGMA_URL", "https://figma-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "figma",
        "description": "Figma design files (read-only)",
        "enabled": True,
        "transport": "json"
    },
    "dealcloud": {
        "url": os.environ.get("MCP_DEALCLOUD_URL", "https://dealcloud-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "dc",
        "description": "DealCloud CRM (deals, companies, interactions)",
        "enabled": True,
        "transport": "json"
    },
    "make": {
        "url": os.environ.get("MCP_MAKE_URL", "https://us2.make.com/mcp/u/7129f411-923e-4acd-b63f-d436d38939dc/stateless"),
        "prefix": "make",
        "description": "Make.com automation scenarios",
        "enabled": True,
        "transport": "sse",
        "headers": {
            "Accept": "application/json, text/event-stream"
        }
    },
    "tailscale": {
        "url": os.environ.get("MCP_TAILSCALE_URL", "https://tailscale-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "ts",
        "description": "Tailscale network management (devices, routes, ACL, auth keys)",
        "enabled": True,
        "transport": "json"
    }
}

# =============================================================================
# TOOL CATALOG CACHE
# =============================================================================

def parse_sse_response(text):
    """Parse SSE response format: event: message\ndata: {...}"""
    for line in text.split('\n'):
        if line.startswith('data: '):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    return None

class ToolCatalog:
    def __init__(self):
        self.tools = {}
        self.last_refresh = None
        self.refresh_interval = 300
    
    def needs_refresh(self):
        if self.last_refresh is None:
            return True
        return (datetime.now() - self.last_refresh).seconds > self.refresh_interval
    
    async def refresh(self):
        logger.info("Refreshing tool catalog from backend MCPs...")
        new_tools = {}
        
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            for backend_name, config in BACKEND_MCPS.items():
                if not config.get("enabled", False):
                    continue
                
                try:
                    headers = {"Content-Type": "application/json"}
                    if config.get("headers"):
                        headers.update(config["headers"])
                    
                    response = await client.post(
                        config["url"],
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        # Handle SSE transport (Make.com)
                        if config.get("transport") == "sse":
                            data = parse_sse_response(response.text)
                        else:
                            data = response.json()
                        
                        if not data:
                            logger.warning(f"  FAIL {backend_name}: Could not parse response")
                            continue
                            
                        tools = data.get("result", {}).get("tools", [])
                        prefix = config["prefix"]
                        
                        for tool in tools:
                            original_name = tool["name"]
                            prefixed_name = f"{prefix}_{original_name}"
                            new_tools[prefixed_name] = {
                                "backend": backend_name,
                                "backend_url": config["url"],
                                "original_name": original_name,
                                "transport": config.get("transport", "json"),
                                "headers": config.get("headers", {}),
                                "schema": {
                                    "name": prefixed_name,
                                    "description": f"[{prefix.upper()}] {tool.get('description', '')}",
                                    "inputSchema": tool.get("inputSchema", {})
                                }
                            }
                        logger.info(f"  OK {backend_name}: {len(tools)} tools loaded")
                    else:
                        logger.warning(f"  FAIL {backend_name}: HTTP {response.status_code}")
                except Exception as e:
                    logger.warning(f"  FAIL {backend_name}: {str(e)}")
        
        self.tools = new_tools
        self.last_refresh = datetime.now()
        logger.info(f"Tool catalog refreshed: {len(self.tools)} total tools")
    
    def get_all_tools(self):
        return [t["schema"] for t in self.tools.values()]
    
    def get_tool(self, prefixed_name):
        return self.tools.get(prefixed_name)

catalog = ToolCatalog()
sse_sessions = {}

# =============================================================================
# MCP PROTOCOL HANDLERS
# =============================================================================

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def call_backend_tool(backend_url: str, tool_name: str, arguments: dict, transport: str = "json", extra_headers: dict = None):
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        response = await client.post(
            backend_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
            headers=headers
        )
        
        if transport == "sse":
            return parse_sse_response(response.text)
        return response.json()

def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "sovereign-mind-gateway", "version": "1.5.0"}
    }

def handle_tools_list(params):
    if catalog.needs_refresh():
        run_async(catalog.refresh())
    return {"tools": catalog.get_all_tools()}

def handle_tools_call(params):
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    
    tool_info = catalog.get_tool(tool_name)
    if not tool_info:
        return {"content": [{"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}], "isError": True}
    
    try:
        result = run_async(call_backend_tool(
            tool_info["backend_url"], 
            tool_info["original_name"], 
            arguments,
            tool_info.get("transport", "json"),
            tool_info.get("headers", {})
        ))
        if result and "result" in result:
            return result["result"]
        elif result and "error" in result:
            return {"content": [{"type": "text", "text": f"Backend error: {result['error']}"}], "isError": True}
        else:
            return result if result else {"content": [{"type": "text", "text": "No response from backend"}], "isError": True}
    except Exception as e:
        logger.error(f"Error calling backend tool: {e}")
        return {"content": [{"type": "text", "text": f"Error calling tool: {str(e)}"}], "isError": True}

def process_mcp_message(data):
    method = data.get("method", "")
    params = data.get("params", {})
    request_id = data.get("id", 1)
    
    logger.info(f"MCP request: {method}")
    
    if method == "initialize":
        result = handle_initialize(params)
    elif method == "tools/list":
        result = handle_tools_list(params)
    elif method == "tools/call":
        result = handle_tools_call(params)
    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    
    return {"jsonrpc": "2.0", "id": request_id, "result": result}

# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "sovereign-mind-gateway",
        "version": "1.5.0",
        "features": ["mcp-proxy", "sse-transport", "web-scrapers", "make-sse-support", "tailscale"],
        "backends": list(BACKEND_MCPS.keys()),
        "total_tools": len(catalog.tools) if catalog.tools else "not yet loaded"
    })

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), 400
        response = process_mcp_message(data)
        return jsonify(response)
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return jsonify({"jsonrpc": "2.0", "id": data.get("id", 1) if data else 1, "error": {"code": -32603, "message": str(e)}}), 500

@app.route("/sse", methods=["GET"])
def sse_connect():
    session_id = str(uuid.uuid4())
    sse_sessions[session_id] = queue.Queue()
    logger.info(f"SSE connection established: {session_id}")
    
    def generate():
        yield f"event: endpoint\ndata: /sse/{session_id}/message\n\n"
        while True:
            try:
                try:
                    message = sse_sessions[session_id].get(timeout=30)
                    yield f"event: message\ndata: {json.dumps(message)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                break
        if session_id in sse_sessions:
            del sse_sessions[session_id]
        logger.info(f"SSE connection closed: {session_id}")
    
    return Response(generate(), mimetype="text/event-stream",
                   headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

@app.route("/sse/<session_id>/message", methods=["POST"])
def sse_message(session_id):
    if session_id not in sse_sessions:
        return jsonify({"error": "Session not found"}), 404
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400
        response = process_mcp_message(data)
        sse_sessions[session_id].put(response)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"SSE message error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/refresh", methods=["POST"])
def force_refresh():
    run_async(catalog.refresh())
    return jsonify({
        "status": "refreshed",
        "total_tools": len(catalog.tools),
        "timestamp": catalog.last_refresh.isoformat() if catalog.last_refresh else None
    })

@app.route("/tools", methods=["GET"])
def list_tools():
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
    return jsonify({"total_tools": len(catalog.tools), "backends": tools_by_backend})

# =============================================================================
# SCRAPER ENDPOINTS
# =============================================================================

@app.route("/scrapers/gfdata/run", methods=["POST"])
def run_gfdata_scraper():
    profile = request.json.get("profile", "mgc_core") if request.json else "mgc_core"
    valid_profiles = ["mgc_core", "distribution_only", "manufacturing_only", "full_lower_middle_market"]
    
    if profile not in valid_profiles:
        return jsonify({"error": f"Invalid profile. Must be one of: {valid_profiles}"}), 400
    
    logger.info(f"Starting GF Data scraper with profile: {profile}")
    
    try:
        bot_path = "/app/scrapers/gfdata/gfdata_bot.py"
        
        if not os.path.exists(bot_path):
            return jsonify({
                "error": "Scraper not found",
                "path": bot_path,
                "hint": "Container needs rebuild with scrapers directory"
            }), 404
        
        result = subprocess.run(
            [sys.executable, bot_path, "--profile", profile],
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ}
        )
        
        return jsonify({
            "status": "completed" if result.returncode == 0 else "failed",
            "profile": profile,
            "returncode": result.returncode,
            "stdout": result.stdout[-5000:] if result.stdout else None,
            "stderr": result.stderr[-2000:] if result.stderr else None
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({"status": "timeout", "error": "Scraper exceeded 10 minute timeout"}), 504
    except Exception as e:
        logger.error(f"Scraper error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/scrapers/gfdata/status", methods=["GET"])
def gfdata_status():
    import snowflake.connector
    
    try:
        conn = snowflake.connector.connect(
            user=os.environ.get('SNOWFLAKE_USER', 'JOHN_CLAUDE'),
            password=os.environ.get('SNOWFLAKE_PASSWORD'),
            account=os.environ.get('SNOWFLAKE_ACCOUNT'),
            warehouse=os.environ.get('SNOWFLAKE_WAREHOUSE', 'SOVEREIGN_MIND_WH'),
            database='HURRICANE',
            schema='MARKET_INTEL'
        )
        
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT job_id, source_name, status, records_scraped, records_loaded, 
                   error_message, started_at, completed_at
            FROM SCRAPE_JOBS 
            WHERE source_name = 'GF Data'
            ORDER BY started_at DESC LIMIT 5
        """)
        jobs = cursor.fetchall()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM GFDATA_RAW")
            record_count = cursor.fetchone()[0]
        except:
            record_count = 0
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "scraper": "gfdata",
            "bot_path": "/app/scrapers/gfdata/gfdata_bot.py",
            "bot_exists": os.path.exists("/app/scrapers/gfdata/gfdata_bot.py"),
            "total_records": record_count,
            "recent_jobs": [
                {
                    "job_id": str(j[0]),
                    "source": j[1],
                    "status": j[2],
                    "records_scraped": j[3],
                    "records_loaded": j[4],
                    "error": j[5],
                    "started_at": j[6].isoformat() if j[6] else None,
                    "completed_at": j[7].isoformat() if j[7] else None
                }
                for j in jobs
            ] if jobs else []
        })
        
    except Exception as e:
        logger.error(f"Status check error: {e}")
        return jsonify({"error": str(e)}), 500

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    logger.info("Sovereign Mind MCP Gateway v1.5.0 starting...")
    run_async(catalog.refresh())
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
