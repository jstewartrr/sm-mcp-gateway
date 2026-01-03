"""
Microsoft Copilot MCP Server v1.0 - Placeholder
Provides MCP interface to Azure OpenAI/Copilot
"""
import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins="*")

AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")

TOOLS = [
    {"name": "copilot_chat", "description": "Chat with Microsoft Copilot/Azure OpenAI", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}, "system": {"type": "string"}}, "required": ["message"]}},
    {"name": "copilot_code", "description": "Generate or analyze code with Copilot", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}, "language": {"type": "string"}}, "required": ["prompt"]}}
]

@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "copilot-mcp", "version": "1.0.0", "status": "healthy", "azure_configured": bool(AZURE_OPENAI_KEY)})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "copilot-mcp", "status": "healthy", "azure_configured": bool(AZURE_OPENAI_KEY)})

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    data = request.get_json() or {}
    method = data.get("method", "")
    req_id = data.get("id", 1)
    
    if method == "initialize":
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "copilot-mcp", "version": "1.0.0"}, "capabilities": {"tools": {}}}})
    elif method == "tools/list":
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps({"status": "placeholder", "message": "Azure OpenAI integration pending credentials"})}]}})
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
