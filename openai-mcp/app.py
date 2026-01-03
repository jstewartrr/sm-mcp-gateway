"""
OpenAI/ChatGPT MCP Server v1.0
Provides MCP interface to OpenAI API
"""
import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx

app = Flask(__name__)
CORS(app, origins="*")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

TOOLS = [
    {
        "name": "openai_chat",
        "description": "Send a chat message to OpenAI GPT model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to send"},
                "system": {"type": "string", "description": "System prompt (optional)"},
                "model": {"type": "string", "description": "Model override (optional)"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "openai_analyze",
        "description": "Analyze text or data with OpenAI",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to analyze"},
                "task": {"type": "string", "description": "Analysis task description"}
            },
            "required": ["content", "task"]
        }
    }
]

def call_openai(messages, model=None):
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY not configured"}
    
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model or OPENAI_MODEL,
                    "messages": messages,
                    "max_tokens": 4096
                }
            )
            if response.status_code == 200:
                data = response.json()
                return {"response": data["choices"][0]["message"]["content"]}
            else:
                return {"error": f"API error: {response.status_code}", "details": response.text}
    except Exception as e:
        return {"error": str(e)}

@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "openai-mcp",
        "version": "1.0.0",
        "status": "healthy",
        "api_key_set": bool(OPENAI_API_KEY),
        "model": OPENAI_MODEL
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "service": "openai-mcp",
        "status": "healthy",
        "api_key_set": bool(OPENAI_API_KEY)
    })

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    data = request.get_json() or {}
    method = data.get("method", "")
    params = data.get("params", {})
    req_id = data.get("id", 1)
    
    if method == "initialize":
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "openai-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}}
            }
        })
    
    elif method == "tools/list":
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        })
    
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        
        if tool_name == "openai_chat":
            messages = []
            if args.get("system"):
                messages.append({"role": "system", "content": args["system"]})
            messages.append({"role": "user", "content": args["message"]})
            result = call_openai(messages, args.get("model"))
            
        elif tool_name == "openai_analyze":
            messages = [
                {"role": "system", "content": f"You are an expert analyst. Task: {args['task']}"},
                {"role": "user", "content": args["content"]}
            ]
            result = call_openai(messages)
            
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result)}]}
        })
    
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
