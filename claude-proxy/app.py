"""
Claude OpenAI-Compatible Proxy v1.0
====================================
Translates OpenAI /chat/completions format to Anthropic /v1/messages format.
For use with Simli and other services expecting OpenAI-compatible endpoints.
"""

import os
import json
import httpx
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

def convert_openai_to_anthropic(openai_request: dict) -> dict:
    """Convert OpenAI chat completion request to Anthropic messages format."""
    messages = openai_request.get("messages", [])
    
    system_message = None
    anthropic_messages = []
    
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        
        if role == "system":
            system_message = content
        elif role == "user":
            anthropic_messages.append({"role": "user", "content": content})
        elif role == "assistant":
            anthropic_messages.append({"role": "assistant", "content": content})
    
    anthropic_request = {
        "model": ANTHROPIC_MODEL,
        "messages": anthropic_messages,
        "max_tokens": openai_request.get("max_tokens", 4096),
    }
    
    if system_message:
        anthropic_request["system"] = system_message
    
    if "temperature" in openai_request:
        anthropic_request["temperature"] = openai_request["temperature"]
    if "top_p" in openai_request:
        anthropic_request["top_p"] = openai_request["top_p"]
    if "stop" in openai_request:
        anthropic_request["stop_sequences"] = openai_request["stop"]
    
    return anthropic_request


def convert_anthropic_to_openai(anthropic_response: dict, model: str) -> dict:
    """Convert Anthropic messages response to OpenAI chat completion format."""
    content = ""
    for block in anthropic_response.get("content", []):
        if block.get("type") == "text":
            content += block.get("text", "")
    
    return {
        "id": f"chatcmpl-{anthropic_response.get('id', 'unknown')}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content
            },
            "finish_reason": anthropic_response.get("stop_reason", "stop")
        }],
        "usage": {
            "prompt_tokens": anthropic_response.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": anthropic_response.get("usage", {}).get("output_tokens", 0),
            "total_tokens": (
                anthropic_response.get("usage", {}).get("input_tokens", 0) +
                anthropic_response.get("usage", {}).get("output_tokens", 0)
            )
        }
    }


def convert_anthropic_stream_to_openai(chunk: dict, model: str) -> str:
    """Convert Anthropic streaming chunk to OpenAI SSE format."""
    chunk_type = chunk.get("type")
    
    if chunk_type == "content_block_delta":
        delta = chunk.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            openai_chunk = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": None
                }]
            }
            return f"data: {json.dumps(openai_chunk)}\n\n"
    
    elif chunk_type == "message_stop":
        openai_chunk = {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        return f"data: {json.dumps(openai_chunk)}\n\ndata: [DONE]\n\n"
    
    return ""


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "claude-openai-proxy",
        "version": "1.0",
        "model": ANTHROPIC_MODEL,
        "api_key_set": bool(ANTHROPIC_API_KEY)
    })


@app.route("/v1/chat/completions", methods=["POST"])
@app.route("/chat/completions", methods=["POST"])
def chat_completions():
    """OpenAI-compatible chat completions endpoint."""
    try:
        openai_request = request.get_json()
        if not openai_request:
            return jsonify({"error": "No request body"}), 400
        
        logger.info(f"Received request for model: {openai_request.get('model', 'default')}")
        
        model = ANTHROPIC_MODEL
        anthropic_request = convert_openai_to_anthropic(openai_request)
        stream = openai_request.get("stream", False)
        
        if stream:
            anthropic_request["stream"] = True
            
            def generate():
                with httpx.Client(timeout=120.0) as client:
                    with client.stream(
                        "POST",
                        "https://api.anthropic.com/v1/messages",
                        json=anthropic_request,
                        headers={
                            "x-api-key": ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json"
                        }
                    ) as response:
                        for line in response.iter_lines():
                            if line.startswith("data: "):
                                try:
                                    chunk = json.loads(line[6:])
                                    openai_chunk = convert_anthropic_stream_to_openai(chunk, model)
                                    if openai_chunk:
                                        yield openai_chunk
                                except json.JSONDecodeError:
                                    continue
            
            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive"
                }
            )
        
        else:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    json=anthropic_request,
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Anthropic error: {response.text}")
                    return jsonify({"error": response.text}), response.status_code
                
                anthropic_response = response.json()
                openai_response = convert_anthropic_to_openai(anthropic_response, model)
                
                return jsonify(openai_response)
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/v1/models", methods=["GET"])
@app.route("/models", methods=["GET"])
def list_models():
    """Return available models in OpenAI format."""
    return jsonify({
        "object": "list",
        "data": [
            {"id": ANTHROPIC_MODEL, "object": "model", "owned_by": "anthropic"},
            {"id": "claude-sonnet-4-20250514", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-haiku-4-20250514", "object": "model", "owned_by": "anthropic"},
        ]
    })


if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set!")
    
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Claude OpenAI Proxy on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
