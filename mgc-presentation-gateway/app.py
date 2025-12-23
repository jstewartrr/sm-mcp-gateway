"""
MGC Presentation Gateway - AI-Powered Presentation Creation Tools
For MiddleGround Capital Team Use

This gateway provides AI capabilities for creating professional presentations:
- Infographic generation (Nano Banana / Gemini)
- Image generation (Imagen 3)
- Slide analysis and redesign suggestions
- Background removal and vectorization
- Document analysis for content extraction
- OCR and vision capabilities

SECURITY: This gateway provides NO access to internal databases.
Users cannot access Sovereign Mind, Hurricane, or any Snowflake data.

Version: 1.0.0
Updated: 2025-12-23
"""
import os
import json
import logging
import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =============================================================================
# BACKEND MCP SERVERS
# =============================================================================

BACKENDS = {
    "vertex_ai": {
        "url": os.environ.get("VERTEX_AI_MCP_URL", "https://vertex-ai-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io"),
        "endpoint": "/mcp"
    },
    "vectorizer": {
        "url": os.environ.get("VECTORIZER_MCP_URL", "https://slide-transform-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io"),
        "endpoint": "/mcp"
    }
}

# =============================================================================
# TOOL ROUTING
# =============================================================================

TOOL_ROUTING = {
    "generate_infographic": "vertex_ai",
    "generate_infographic_pro": "vertex_ai",
    "generate_image": "vertex_ai",
    "edit_image": "vertex_ai",
    "analyze_image": "vertex_ai",
    "extract_text_from_image": "vertex_ai",
    "detect_objects": "vertex_ai",
    "detect_logos": "vertex_ai",
    "analyze_document": "vertex_ai",
    "extract_tables": "vertex_ai",
    "generate_content": "vertex_ai",
    "chat": "vertex_ai",
    "analyze_slide": "vectorizer",
    "extract_slide_elements": "vectorizer",
    "vectorize_image": "vectorizer",
    "remove_background": "vectorizer",
    "check_credits": "vectorizer",
    "list_capabilities": None,
}

BACKEND_TOOL_MAP = {
    "generate_infographic": "nano_banana_generate",
    "generate_infographic_pro": "nano_banana_pro_generate",
    "generate_image": "imagen_generate",
    "edit_image": "nano_banana_edit",
    "analyze_image": "gemini_analyze_image",
    "extract_text_from_image": "vision_ocr",
    "detect_objects": "vision_detect_objects",
    "detect_logos": "vision_detect_logos",
    "analyze_document": "gemini_analyze_document",
    "extract_tables": "document_extract_tables",
    "generate_content": "gemini_generate",
    "chat": "gemini_chat",
    "analyze_slide": "analyze_slide_for_redesign",
    "extract_slide_elements": "extract_slide_elements",
    "vectorize_image": "vectorize_image",
    "remove_background": "remove_background",
    "check_credits": "get_credits_balance",
}

# =============================================================================
# SECURITY - Block any database access attempts
# =============================================================================

BLOCKED_PATTERNS = [
    "snowflake", "database", "sovereign", "hurricane", "hive", "sql", 
    "query", "db_", "_db", "warehouse", "schema"
]

def is_blocked(tool_name: str) -> bool:
    name_lower = tool_name.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in name_lower:
            logger.warning(f"BLOCKED: {tool_name}")
            return True
    return False

# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

MCP_TOOLS = [
    {"name": "generate_infographic", "description": "Generate professional infographics using Nano Banana (Gemini 2.5 Flash). Best for diagrams, charts, and visual content.", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Detailed description of the infographic"}, "aspect_ratio": {"type": "string", "default": "16:9", "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"]}, "style": {"type": "string", "default": "corporate", "enum": ["corporate", "minimal", "bold", "creative"]}}, "required": ["prompt"]}},
    {"name": "generate_infographic_pro", "description": "Generate complex infographics with accurate text using Nano Banana Pro. Best for detailed data visualizations.", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}, "aspect_ratio": {"type": "string", "default": "16:9"}, "style": {"type": "string", "default": "corporate"}}, "required": ["prompt"]}},
    {"name": "generate_image", "description": "Generate photorealistic images using Imagen 3. Best for backgrounds, hero images, artistic visuals.", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}, "negative_prompt": {"type": "string"}, "number_of_images": {"type": "integer", "default": 1}, "aspect_ratio": {"type": "string", "default": "16:9"}}, "required": ["prompt"]}},
    {"name": "edit_image", "description": "Edit an image using natural language instructions.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["image_base64", "prompt"]}},
    {"name": "analyze_image", "description": "Analyze an image and get detailed description.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}, "prompt": {"type": "string", "default": "Describe this image in detail"}}, "required": ["image_base64"]}},
    {"name": "extract_text_from_image", "description": "Extract text from image using OCR.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}, "language_hints": {"type": "array", "items": {"type": "string"}}}, "required": ["image_base64"]}},
    {"name": "detect_objects", "description": "Detect objects with bounding boxes.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}}, "required": ["image_base64"]}},
    {"name": "detect_logos", "description": "Detect logos and brands in image.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}}, "required": ["image_base64"]}},
    {"name": "analyze_document", "description": "Analyze document text and extract insights for presentations.", "inputSchema": {"type": "object", "properties": {"document_text": {"type": "string"}, "analysis_prompt": {"type": "string"}}, "required": ["document_text", "analysis_prompt"]}},
    {"name": "extract_tables", "description": "Extract tables from document image as markdown.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}}, "required": ["image_base64"]}},
    {"name": "generate_content", "description": "Generate text content for slides: bullet points, summaries, talking points.", "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}}, "required": ["prompt"]}},
    {"name": "chat", "description": "Multi-turn conversation for brainstorming and refining content.", "inputSchema": {"type": "object", "properties": {"messages": {"type": "array"}, "system_instruction": {"type": "string"}}, "required": ["messages"]}},
    {"name": "analyze_slide", "description": "Analyze slide image and get redesign suggestions.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}, "style": {"type": "string", "default": "corporate"}, "brand_colors": {"type": "string", "description": "e.g. '#003366,#FF6600'"}}, "required": ["image_base64"]}},
    {"name": "extract_slide_elements", "description": "Extract text and graphics from slide image.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}}, "required": ["image_base64"]}},
    {"name": "vectorize_image", "description": "Convert raster image to scalable SVG.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}, "output_format": {"type": "string", "default": "svg"}}, "required": ["image_base64"]}},
    {"name": "remove_background", "description": "Remove background from image, return transparent PNG.", "inputSchema": {"type": "object", "properties": {"image_base64": {"type": "string"}}, "required": ["image_base64"]}},
    {"name": "check_credits", "description": "Check remaining vectorization API credits.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_capabilities", "description": "List all gateway capabilities.", "inputSchema": {"type": "object", "properties": {}}}
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def proxy_to_backend(backend_name: str, tool_name: str, arguments: dict) -> dict:
    try:
        backend = BACKENDS.get(backend_name)
        if not backend:
            return {"error": f"Backend not configured: {backend_name}"}
        
        url = f"{backend['url']}{backend['endpoint']}"
        backend_tool = BACKEND_TOOL_MAP.get(tool_name, tool_name)
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": backend_tool, "arguments": arguments}
        }
        
        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()
        return response.json().get("result", response.json())
        
    except Exception as e:
        logger.error(f"Backend error {backend_name}/{tool_name}: {e}")
        return {"error": str(e)}


def list_capabilities() -> dict:
    return {
        "gateway": "MGC Presentation Gateway",
        "version": "1.0.0",
        "description": "AI-powered presentation creation tools",
        "capabilities": {
            "image_generation": ["generate_infographic", "generate_infographic_pro", "generate_image", "edit_image"],
            "image_analysis": ["analyze_image", "extract_text_from_image", "detect_objects", "detect_logos"],
            "document_analysis": ["analyze_document", "extract_tables"],
            "content_generation": ["generate_content", "chat"],
            "slide_tools": ["analyze_slide", "extract_slide_elements", "vectorize_image", "remove_background"]
        },
        "brand_colors": {"mgc_navy": "#003366", "mgc_orange": "#FF6600"}
    }

# =============================================================================
# MCP ENDPOINTS
# =============================================================================

@app.route('/mcp', methods=['POST'])
def mcp_handler():
    try:
        data = request.get_json()
        method = data.get('method')
        params = data.get('params', {})
        request_id = data.get('id')
        
        if method == 'initialize':
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mgc-presentation-gateway", "version": "1.0.0"},
                    "capabilities": {"tools": {}}
                }
            })
        
        elif method == 'tools/list':
            return jsonify({"jsonrpc": "2.0", "id": request_id, "result": {"tools": MCP_TOOLS}})
        
        elif method == 'tools/call':
            tool_name = params.get('name')
            arguments = params.get('arguments', {})
            
            if is_blocked(tool_name):
                return jsonify({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Tool not available"}})
            
            if tool_name == "list_capabilities":
                result = list_capabilities()
            else:
                backend = TOOL_ROUTING.get(tool_name)
                if backend:
                    result = proxy_to_backend(backend, tool_name, arguments)
                else:
                    result = {"error": f"Unknown tool: {tool_name}"}
            
            return jsonify({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}})
        
        elif method == 'ping':
            return jsonify({"jsonrpc": "2.0", "id": request_id, "result": {}})
        
        return jsonify({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
        
    except Exception as e:
        logger.error(f"Handler error: {e}")
        return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "mgc-presentation-gateway", "version": "1.0.0", "tool_count": len(MCP_TOOLS), "database_access": False})


@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "MGC Presentation Gateway", "version": "1.0.0", "endpoints": {"/mcp": "POST", "/health": "GET"}})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
