"""
Tailscale MCP Server for Sovereign Mind
========================================
Provides network management via Tailscale API v2
"""

import os
import json
import httpx
from flask import Flask, request, jsonify
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
TAILSCALE_API_KEY = os.environ.get("TAILSCALE_API_KEY")
TAILSCALE_TAILNET = os.environ.get("TAILSCALE_TAILNET", "-")
TAILSCALE_BASE_URL = "https://api.tailscale.com/api/v2"

def get_headers():
    return {
        "Authorization": f"Bearer {TAILSCALE_API_KEY}",
        "Content-Type": "application/json"
    }

def list_devices():
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{TAILSCALE_BASE_URL}/tailnet/{TAILSCALE_TAILNET}/devices", headers=get_headers())
            if response.status_code == 200:
                data = response.json()
                devices = data.get("devices", [])
                return {
                    "success": True,
                    "device_count": len(devices),
                    "devices": [{"id": d.get("id"), "name": d.get("name"), "hostname": d.get("hostname"), 
                                "addresses": d.get("addresses", []), "os": d.get("os"), 
                                "clientVersion": d.get("clientVersion"), "lastSeen": d.get("lastSeen"),
                                "online": d.get("online", False), "authorized": d.get("authorized", False),
                                "tags": d.get("tags", []), "user": d.get("user")} for d in devices]
                }
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_device(device_id: str):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{TAILSCALE_BASE_URL}/device/{device_id}", headers=get_headers())
            if response.status_code == 200:
                return {"success": True, "device": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def authorize_device(device_id: str, authorized: bool = True):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAILSCALE_BASE_URL}/device/{device_id}/authorized", 
                                  headers=get_headers(), json={"authorized": authorized})
            if response.status_code in [200, 204]:
                return {"success": True, "message": f"Device {'authorized' if authorized else 'deauthorized'}"}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def delete_device(device_id: str):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(f"{TAILSCALE_BASE_URL}/device/{device_id}", headers=get_headers())
            if response.status_code in [200, 204]:
                return {"success": True, "message": "Device deleted"}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def set_device_tags(device_id: str, tags: list):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAILSCALE_BASE_URL}/device/{device_id}/tags", 
                                  headers=get_headers(), json={"tags": tags})
            if response.status_code in [200, 204]:
                return {"success": True, "message": "Tags updated", "tags": tags}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_dns_settings():
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{TAILSCALE_BASE_URL}/tailnet/{TAILSCALE_TAILNET}/dns/nameservers", headers=get_headers())
            if response.status_code == 200:
                return {"success": True, "dns": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_acl():
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{TAILSCALE_BASE_URL}/tailnet/{TAILSCALE_TAILNET}/acl", headers=get_headers())
            if response.status_code == 200:
                return {"success": True, "acl": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def list_keys():
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{TAILSCALE_BASE_URL}/tailnet/{TAILSCALE_TAILNET}/keys", headers=get_headers())
            if response.status_code == 200:
                return {"success": True, "keys": response.json().get("keys", [])}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def create_auth_key(reusable=False, ephemeral=False, preauthorized=True, expiry_seconds=86400, tags=None, description=None):
    try:
        payload = {"capabilities": {"devices": {"create": {"reusable": reusable, "ephemeral": ephemeral, 
                   "preauthorized": preauthorized, "tags": tags or []}}}, "expirySeconds": expiry_seconds}
        if description:
            payload["description"] = description
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAILSCALE_BASE_URL}/tailnet/{TAILSCALE_TAILNET}/keys", 
                                  headers=get_headers(), json=payload)
            if response.status_code in [200, 201]:
                return {"success": True, "key": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def delete_auth_key(key_id: str):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(f"{TAILSCALE_BASE_URL}/tailnet/{TAILSCALE_TAILNET}/keys/{key_id}", headers=get_headers())
            if response.status_code in [200, 204]:
                return {"success": True, "message": "Key deleted"}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_device_routes(device_id: str):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{TAILSCALE_BASE_URL}/device/{device_id}/routes", headers=get_headers())
            if response.status_code == 200:
                return {"success": True, "routes": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def set_device_routes(device_id: str, routes: list):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAILSCALE_BASE_URL}/device/{device_id}/routes", 
                                  headers=get_headers(), json={"routes": routes})
            if response.status_code in [200, 204]:
                return {"success": True, "message": "Routes updated"}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

TOOLS = [
    {"name": "list_devices", "description": "List all devices in the Tailscale network (tailnet)", 
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_device", "description": "Get detailed information about a specific Tailscale device",
     "inputSchema": {"type": "object", "properties": {"device_id": {"type": "string", "description": "The device ID"}}, "required": ["device_id"]}},
    {"name": "authorize_device", "description": "Authorize or deauthorize a device in the tailnet",
     "inputSchema": {"type": "object", "properties": {"device_id": {"type": "string"}, "authorized": {"type": "boolean", "default": True}}, "required": ["device_id"]}},
    {"name": "delete_device", "description": "Remove a device from the tailnet",
     "inputSchema": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": ["device_id"]}},
    {"name": "set_device_tags", "description": "Set ACL tags on a device",
     "inputSchema": {"type": "object", "properties": {"device_id": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["device_id", "tags"]}},
    {"name": "get_dns_settings", "description": "Get DNS nameserver settings for the tailnet",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_acl", "description": "Get Access Control List policy for the tailnet",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "list_keys", "description": "List all auth keys for the tailnet",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "create_auth_key", "description": "Create a new auth key for adding devices",
     "inputSchema": {"type": "object", "properties": {"reusable": {"type": "boolean", "default": False}, 
                    "ephemeral": {"type": "boolean", "default": False}, "preauthorized": {"type": "boolean", "default": True},
                    "expiry_seconds": {"type": "integer", "default": 86400}, "tags": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"}}, "required": []}},
    {"name": "delete_auth_key", "description": "Delete an auth key",
     "inputSchema": {"type": "object", "properties": {"key_id": {"type": "string"}}, "required": ["key_id"]}},
    {"name": "get_device_routes", "description": "Get subnet routes for a device",
     "inputSchema": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": ["device_id"]}},
    {"name": "set_device_routes", "description": "Enable or disable subnet routes for a device",
     "inputSchema": {"type": "object", "properties": {"device_id": {"type": "string"}, "routes": {"type": "array", "items": {"type": "string"}}}, "required": ["device_id", "routes"]}}
]

def execute_tool(name: str, arguments: dict):
    tools_map = {
        "list_devices": lambda a: list_devices(),
        "get_device": lambda a: get_device(a["device_id"]),
        "authorize_device": lambda a: authorize_device(a["device_id"], a.get("authorized", True)),
        "delete_device": lambda a: delete_device(a["device_id"]),
        "set_device_tags": lambda a: set_device_tags(a["device_id"], a["tags"]),
        "get_dns_settings": lambda a: get_dns_settings(),
        "get_acl": lambda a: get_acl(),
        "list_keys": lambda a: list_keys(),
        "create_auth_key": lambda a: create_auth_key(a.get("reusable", False), a.get("ephemeral", False), 
                          a.get("preauthorized", True), a.get("expiry_seconds", 86400), a.get("tags"), a.get("description")),
        "delete_auth_key": lambda a: delete_auth_key(a["key_id"]),
        "get_device_routes": lambda a: get_device_routes(a["device_id"]),
        "set_device_routes": lambda a: set_device_routes(a["device_id"], a["routes"])
    }
    return tools_map.get(name, lambda a: {"error": f"Unknown tool: {name}"})(arguments)

def handle_initialize(params):
    return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "tailscale-mcp", "version": "1.0.0"}}

def handle_tools_list(params):
    return {"tools": TOOLS}

def handle_tools_call(params):
    try:
        result = execute_tool(params.get("name", ""), params.get("arguments", {}))
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

def process_mcp_message(data):
    method = data.get("method", "")
    params = data.get("params", {})
    request_id = data.get("id", 1)
    logger.info(f"MCP request: {method}")
    
    handlers = {"initialize": handle_initialize, "tools/list": handle_tools_list, "tools/call": handle_tools_call}
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method in handlers:
        return {"jsonrpc": "2.0", "id": request_id, "result": handlers[method](params)}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "tailscale-mcp", "version": "1.0.0",
                   "tailnet": TAILSCALE_TAILNET, "api_key_configured": bool(TAILSCALE_API_KEY)})

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), 400
        return jsonify(process_mcp_message(data))
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return jsonify({"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": str(e)}}), 500

if __name__ == "__main__":
    logger.info("Tailscale MCP Server starting...")
    if not TAILSCALE_API_KEY:
        logger.warning("TAILSCALE_API_KEY not set!")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
