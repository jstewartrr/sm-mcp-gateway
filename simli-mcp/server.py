"""Simli MCP Server - Fixed endpoint mapping"""
import os
import json
import logging
import requests
from flask import Flask, request, jsonify, Response
from functools import wraps

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

SIMLI_API_KEY = os.environ.get("SIMLI_API_KEY", "")
SIMLI_BASE_URL = "https://api.simli.ai"

TOOLS = [
    {
        "name": "list_agents",
        "description": "List all Simli agents/avatars in your account",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_agent",
        "description": "Get details of a specific Simli agent by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent ID to retrieve"}
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "create_agent",
        "description": "Create a new Simli agent/avatar",
        "inputSchema": {
            "type": "object",
            "properties": {
                "face_id": {"type": "string", "description": "Face ID for the avatar"},
                "name": {"type": "string", "description": "Name for the agent"},
                "prompt": {"type": "string", "description": "System prompt for the agent"},
                "first_message": {"type": "string", "description": "Initial greeting message"},
                "voice_provider": {"type": "string", "description": "Voice provider: 'elevenlabs' or 'cartesia'", "default": "elevenlabs"},
                "voice_id": {"type": "string", "description": "Voice ID"}
            },
            "required": ["face_id", "name"]
        }
    },
    {
        "name": "update_agent",
        "description": "Update a Simli agent's settings (face, name, prompt, voice, etc.)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent ID to update"},
                "face_id": {"type": "string", "description": "New face ID for the avatar"},
                "name": {"type": "string", "description": "New name for the agent"},
                "prompt": {"type": "string", "description": "System prompt for the agent"},
                "first_message": {"type": "string", "description": "Initial greeting message"},
                "voice_provider": {"type": "string", "description": "Voice provider: 'elevenlabs' or 'cartesia'"},
                "voice_id": {"type": "string", "description": "Voice ID (for ElevenLabs or Cartesia)"},
                "max_idle_time": {"type": "integer", "description": "Max idle time in seconds before timeout"},
                "max_session_length": {"type": "integer", "description": "Max session length in seconds"}
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "delete_agent",
        "description": "Delete a Simli agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent ID to delete"}
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "list_faces",
        "description": "List available preset face IDs for avatars",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]

def simli_request(method, endpoint, data=None):
    """Make request to Simli API"""
    url = f"{SIMLI_BASE_URL}{endpoint}"
    headers = {
        "x-simli-api-key": SIMLI_API_KEY,
        "Content-Type": "application/json"
    }
    logger.info(f"Making {method} request to {url}")
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            return {"error": f"Unsupported method: {method}"}
        
        logger.info(f"Response status: {response.status_code}")
        
        if response.status_code >= 400:
            return {"error": f"API error {response.status_code}: {response.text}"}
        
        if response.text:
            return response.json()
        return {"success": True}
    except Exception as e:
        logger.error(f"Request failed: {e}")
        return {"error": str(e)}


def handle_tool_call(tool_name, arguments):
    """Execute tool and return result"""
    
    if tool_name == "list_agents":
        result = simli_request("GET", "/agents")
        if isinstance(result, list):
            return {"success": True, "agents": result, "count": len(result)}
        return result
    
    elif tool_name == "get_agent":
        agent_id = arguments.get("agent_id")
        if not agent_id:
            return {"error": "agent_id is required"}
        result = simli_request("GET", f"/agent/{agent_id}")
        return result
    
    elif tool_name == "create_agent":
        data = {
            "face_id": arguments.get("face_id"),
            "name": arguments.get("name", "Untitled Agent")
        }
        if arguments.get("prompt"):
            data["prompt"] = arguments["prompt"]
        if arguments.get("first_message"):
            data["first_message"] = arguments["first_message"]
        if arguments.get("voice_provider"):
            data["voice_provider"] = arguments["voice_provider"]
        if arguments.get("voice_id"):
            data["voice_id"] = arguments["voice_id"]
        
        result = simli_request("POST", "/agent", data)
        return result
    
    elif tool_name == "update_agent":
        agent_id = arguments.get("agent_id")
        if not agent_id:
            return {"error": "agent_id is required"}
        
        data = {}
        for key in ["face_id", "name", "prompt", "first_message", "voice_provider", 
                    "voice_id", "max_idle_time", "max_session_length"]:
            if arguments.get(key) is not None:
                data[key] = arguments[key]
        
        result = simli_request("PUT", f"/agent/{agent_id}", data)
        return result
    
    elif tool_name == "delete_agent":
        agent_id = arguments.get("agent_id")
        if not agent_id:
            return {"error": "agent_id is required"}
        result = simli_request("DELETE", f"/agent/{agent_id}")
        return result
    
    elif tool_name == "list_faces":
        return {
            "success": True,
            "note": "These are commonly available preset faces. Create custom faces at app.simli.com",
            "preset_faces": [
                {"id": "tmp9i8bbq7c", "name": "Default Male"},
                {"id": "t7cR30LkYqwg", "name": "Default Female"}
            ],
            "custom_faces_url": "https://app.simli.com/create"
        }
    
    else:
        return {"error": f"Unknown tool: {tool_name}"}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "simli-mcp", "version": "1.2.0"})


@app.route("/mcp", methods=["POST"])
def mcp_handler():
    """Handle MCP protocol requests"""
    data = request.get_json()
    
    if not data:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    
    method = data.get("method")
    params = data.get("params", {})
    request_id = data.get("id")
    
    if method == "initialize":
        return jsonify({
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "simli-mcp", "version": "1.2.0"}
            },
            "id": request_id
        })
    
    elif method == "tools/list":
        return jsonify({
            "jsonrpc": "2.0",
            "result": {"tools": TOOLS},
            "id": request_id
        })
    
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        result = handle_tool_call(tool_name, arguments)
        
        return jsonify({
            "jsonrpc": "2.0",
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
            },
            "id": request_id
        })
    
    else:
        return jsonify({
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": request_id
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
