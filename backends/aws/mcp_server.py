"""SM AWS MCP - SSE-compatible MCP server for Claude.ai"""
import os
import json
import asyncio
import boto3
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uuid

app = FastAPI(title="SM AWS MCP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

def get_boto_session():
    return boto3.Session(aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY, region_name=AWS_REGION)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "SM AWS MCP", "version": "1.0.0"}

@app.get("/")
async def root():
    return {"service": "SM AWS MCP", "status": "running"}

def get_tools():
    return [
        {"name": "aws_bedrock_list_models", "description": "[AWS] List available Bedrock AI models", "inputSchema": {"type": "object", "properties": {}, "required": []}},
        {"name": "aws_bedrock_invoke", "description": "[AWS] Invoke AI model on Bedrock", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}, "model_id": {"type": "string"}, "max_tokens": {"type": "integer"}}, "required": ["prompt"]}},
        {"name": "aws_s3_list_buckets", "description": "[AWS] List S3 buckets", "inputSchema": {"type": "object", "properties": {}, "required": []}},
        {"name": "aws_lambda_list", "description": "[AWS] List Lambda functions", "inputSchema": {"type": "object", "properties": {}, "required": []}}
    ]

def execute_tool(name, args):
    try:
        session = get_boto_session()
        if name == 'aws_bedrock_list_models':
            resp = session.client('bedrock').list_foundation_models()
            return {'success': True, 'models': [{'id': m['modelId'], 'provider': m.get('providerName', '')} for m in resp.get('modelSummaries', [])[:20]]}
        elif name == 'aws_bedrock_invoke':
            model = args.get('model_id', 'anthropic.claude-sonnet-4-20250514-v1:0')
            body = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': args.get('max_tokens', 4096), 'messages': [{'role': 'user', 'content': args['prompt']}]}
            resp = session.client('bedrock-runtime').invoke_model(modelId=model, body=json.dumps(body))
            result = json.loads(resp['body'].read())
            return {'success': True, 'response': result.get('content', [{}])[0].get('text', '')}
        elif name == 'aws_s3_list_buckets':
            resp = session.client('s3').list_buckets()
            return {'success': True, 'buckets': [b['Name'] for b in resp.get('Buckets', [])]}
        elif name == 'aws_lambda_list':
            resp = session.client('lambda').list_functions()
            return {'success': True, 'functions': [f['FunctionName'] for f in resp.get('Functions', [])]}
        return {'success': False, 'error': f'Unknown tool: {name}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.get("/sse")
async def sse_endpoint(request: Request):
    session_id = str(uuid.uuid4())
    async def event_generator():
        yield f"event: endpoint\ndata: /mcp/message?session_id={session_id}\n\n"
        while True:
            if await request.is_disconnected(): break
            await asyncio.sleep(30)
            yield ": keepalive\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/mcp/message")
async def mcp_message(request: Request):
    body = await request.json()
    method, id = body.get("method", ""), body.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "SM AWS MCP", "version": "1.0.0"}}}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": id, "result": {"tools": get_tools()}}
    elif method == "tools/call":
        result = execute_tool(body.get("params", {}).get("name", ""), body.get("params", {}).get("arguments", {}))
        return {"jsonrpc": "2.0", "id": id, "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": id, "result": {}}
    return {"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
