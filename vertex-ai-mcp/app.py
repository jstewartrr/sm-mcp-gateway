"""
Vertex AI MCP Server - Enhanced with Nano Banana Image Generation
For Sovereign Mind / MiddleGround Capital
Updated: 2025-12-23
"""
import os
import json
import base64
import logging
from io import BytesIO
from flask import Flask, request, jsonify, Response
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import GenerativeModel, Part, Image, GenerationConfig
from vertexai.vision_models import ImageGenerationModel
from google.cloud import vision

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON', '{}')
GOOGLE_PROJECT_ID = os.environ.get('GOOGLE_PROJECT_ID', 'innate-concept-481918-h9')
GOOGLE_LOCATION = os.environ.get('GOOGLE_LOCATION', 'us-central1')

# Initialize credentials
try:
    credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    credentials = service_account.Credentials.from_service_account_info(credentials_info)
    vertexai.init(project=GOOGLE_PROJECT_ID, location=GOOGLE_LOCATION, credentials=credentials)
    logger.info(f"Initialized Vertex AI for project: {GOOGLE_PROJECT_ID}")
except Exception as e:
    logger.error(f"Failed to initialize credentials: {e}")
    credentials = None

# Available models
MODELS = {
    # Text models
    "gemini-2.0-flash": "gemini-2.0-flash-exp",
    "gemini-1.5-pro": "gemini-1.5-pro-002",
    "gemini-1.5-flash": "gemini-1.5-flash-002",
    # Image generation models (Nano Banana family)
    "nano-banana": "gemini-2.5-flash-preview-05-20",  # Nano Banana GA
    "nano-banana-pro": "gemini-2.5-pro-preview-05-06",  # Nano Banana Pro (Preview)
    "gemini-2.5-flash-image": "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro-image": "gemini-2.5-pro-preview-05-06",
    # Imagen
    "imagen-3": "imagen-3.0-generate-001",
}

ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]

# MCP Tool Definitions
MCP_TOOLS = [
    {
        "name": "gemini_generate",
        "description": "Generate text content using Gemini models. Supports gemini-2.0-flash-exp, gemini-1.5-pro, gemini-1.5-flash.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The prompt to generate content from"},
                "model": {"type": "string", "default": "gemini-2.0-flash-exp", "description": "Model to use"},
                "temperature": {"type": "number", "default": 0.7, "description": "Temperature (0-1)"},
                "max_tokens": {"type": "integer", "default": 8192, "description": "Max output tokens"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "nano_banana_generate",
        "description": "Generate images using Nano Banana (Gemini 2.5 Flash). Best for infographics, diagrams, slides, and visual content. Returns base64-encoded image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text description of image to generate"},
                "aspect_ratio": {"type": "string", "default": "16:9", "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]},
                "style": {"type": "string", "default": "corporate", "description": "Style hint: corporate, minimal, bold, creative"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "nano_banana_pro_generate",
        "description": "Generate images using Nano Banana Pro (Gemini 2.5 Pro). Superior for complex infographics, accurate text rendering, diagrams with world knowledge. Returns base64-encoded image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text description of image to generate"},
                "aspect_ratio": {"type": "string", "default": "16:9", "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]},
                "style": {"type": "string", "default": "corporate", "description": "Style hint: corporate, minimal, bold, creative"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "nano_banana_edit",
        "description": "Edit an existing image using Nano Banana. Provide base64 image and edit instructions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded source image"},
                "prompt": {"type": "string", "description": "Edit instructions"}
            },
            "required": ["image_base64", "prompt"]
        }
    },
    {
        "name": "imagen_generate",
        "description": "Generate images using Imagen 3. Returns base64-encoded images.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text description of image to generate"},
                "negative_prompt": {"type": "string", "description": "What to avoid in the image"},
                "number_of_images": {"type": "integer", "default": 1, "description": "Number of images (1-4)"},
                "aspect_ratio": {"type": "string", "default": "1:1", "enum": ["1:1", "9:16", "16:9", "3:4", "4:3"]}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "imagen_edit",
        "description": "Edit an existing image using Imagen.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded source image"},
                "prompt": {"type": "string", "description": "Edit instructions"},
                "mask_base64": {"type": "string", "description": "Optional mask for inpainting"}
            },
            "required": ["image_base64", "prompt"]
        }
    },
    {
        "name": "gemini_analyze_image",
        "description": "Analyze an image using Gemini's multimodal capabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image"},
                "prompt": {"type": "string", "default": "Describe this image in detail", "description": "Analysis prompt"},
                "model": {"type": "string", "default": "gemini-2.0-flash-exp"}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "gemini_analyze_document",
        "description": "Analyze a document (PDF pages as images) using Gemini.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_text": {"type": "string", "description": "Document text content"},
                "analysis_prompt": {"type": "string", "description": "What to analyze"},
                "model": {"type": "string", "default": "gemini-1.5-pro"}
            },
            "required": ["document_text", "analysis_prompt"]
        }
    },
    {
        "name": "gemini_chat",
        "description": "Multi-turn chat conversation with Gemini.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "description": "Array of {role, content} messages"},
                "system_instruction": {"type": "string", "description": "System prompt"},
                "model": {"type": "string", "default": "gemini-2.0-flash-exp"}
            },
            "required": ["messages"]
        }
    },
    {
        "name": "vision_ocr",
        "description": "Extract text from an image using Cloud Vision OCR.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image"},
                "language_hints": {"type": "array", "items": {"type": "string"}, "description": "Language hints (e.g., ['en', 'ja'])"}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "vision_detect_labels",
        "description": "Detect labels/objects in an image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image"},
                "max_results": {"type": "integer", "default": 10}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "vision_detect_objects",
        "description": "Detect and localize objects in an image with bounding boxes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image"}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "vision_detect_faces",
        "description": "Detect faces and facial attributes in an image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image"}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "vision_detect_logos",
        "description": "Detect logos/brands in an image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image"}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "document_parse_pdf",
        "description": "Parse a PDF document and extract structured text, tables, and form fields using Document AI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_base64": {"type": "string", "description": "Base64-encoded PDF"},
                "processor_id": {"type": "string", "description": "Document AI processor ID (optional, uses default OCR)"}
            },
            "required": ["pdf_base64"]
        }
    },
    {
        "name": "document_extract_tables",
        "description": "Extract tables from a document image or PDF page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image of document page"}
            },
            "required": ["image_base64"]
        }
    },
    {
        "name": "list_models",
        "description": "List available Vertex AI models.",
        "inputSchema": {"type": "object", "properties": {}}
    }
]


# ============== NANO BANANA IMAGE GENERATION ==============

def nano_banana_generate(prompt: str, aspect_ratio: str = "16:9", style: str = "corporate") -> dict:
    """Generate images using Nano Banana (Gemini 2.5 Flash)"""
    try:
        # Enhance prompt with style
        enhanced_prompt = f"{prompt}. Style: {style}, professional quality, clean design."
        
        model = GenerativeModel("gemini-2.5-flash-preview-05-20")
        
        # Configure for image output
        generation_config = GenerationConfig(
            response_modalities=["IMAGE", "TEXT"],
            temperature=0.7,
        )
        
        response = model.generate_content(
            enhanced_prompt,
            generation_config=generation_config,
        )
        
        # Extract image from response
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                image_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                return {
                    "success": True,
                    "model": "gemini-2.5-flash-preview-05-20 (Nano Banana)",
                    "image_base64": image_data,
                    "mime_type": part.inline_data.mime_type,
                    "aspect_ratio": aspect_ratio
                }
            elif hasattr(part, 'text') and part.text:
                # Model returned text instead of image
                return {
                    "success": False,
                    "error": "Model returned text instead of image",
                    "text_response": part.text
                }
        
        return {"success": False, "error": "No image generated in response"}
        
    except Exception as e:
        logger.error(f"Nano Banana generation error: {e}")
        return {"success": False, "error": str(e)}


def nano_banana_pro_generate(prompt: str, aspect_ratio: str = "16:9", style: str = "corporate") -> dict:
    """Generate images using Nano Banana Pro (Gemini 2.5 Pro) - best for infographics"""
    try:
        # Enhance prompt with style and infographic hints
        enhanced_prompt = f"""Create a professional {style} infographic or visual: {prompt}
        
Requirements:
- Clean, modern design
- Accurate text rendering
- Professional corporate quality
- Aspect ratio: {aspect_ratio}"""
        
        model = GenerativeModel("gemini-2.5-pro-preview-05-06")
        
        generation_config = GenerationConfig(
            response_modalities=["IMAGE", "TEXT"],
            temperature=0.7,
        )
        
        response = model.generate_content(
            enhanced_prompt,
            generation_config=generation_config,
        )
        
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                image_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                return {
                    "success": True,
                    "model": "gemini-2.5-pro-preview-05-06 (Nano Banana Pro)",
                    "image_base64": image_data,
                    "mime_type": part.inline_data.mime_type,
                    "aspect_ratio": aspect_ratio
                }
            elif hasattr(part, 'text') and part.text:
                return {
                    "success": False,
                    "error": "Model returned text instead of image",
                    "text_response": part.text
                }
        
        return {"success": False, "error": "No image generated in response"}
        
    except Exception as e:
        logger.error(f"Nano Banana Pro generation error: {e}")
        return {"success": False, "error": str(e)}


def nano_banana_edit(image_base64: str, prompt: str) -> dict:
    """Edit an existing image using Nano Banana"""
    try:
        model = GenerativeModel("gemini-2.5-flash-preview-05-20")
        
        # Decode the input image
        image_bytes = base64.b64decode(image_base64)
        image_part = Part.from_image(Image.from_bytes(image_bytes))
        
        generation_config = GenerationConfig(
            response_modalities=["IMAGE", "TEXT"],
            temperature=0.7,
        )
        
        response = model.generate_content(
            [image_part, prompt],
            generation_config=generation_config,
        )
        
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                image_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                return {
                    "success": True,
                    "model": "gemini-2.5-flash-preview-05-20 (Nano Banana)",
                    "image_base64": image_data,
                    "mime_type": part.inline_data.mime_type
                }
        
        return {"success": False, "error": "No edited image in response"}
        
    except Exception as e:
        logger.error(f"Nano Banana edit error: {e}")
        return {"success": False, "error": str(e)}


# ============== EXISTING FUNCTIONS ==============

def gemini_generate(prompt: str, model: str = "gemini-2.0-flash-exp", 
                   temperature: float = 0.7, max_tokens: int = 8192) -> dict:
    """Generate text content using Gemini"""
    try:
        model_id = MODELS.get(model, model)
        gen_model = GenerativeModel(model_id)
        
        generation_config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        response = gen_model.generate_content(prompt, generation_config=generation_config)
        return {
            "success": True,
            "content": response.text,
            "model": model_id
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def imagen_generate(prompt: str, negative_prompt: str = None, 
                   number_of_images: int = 1, aspect_ratio: str = "1:1") -> dict:
    """Generate images using Imagen 3"""
    try:
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
        
        response = model.generate_images(
            prompt=prompt,
            negative_prompt=negative_prompt,
            number_of_images=number_of_images,
            aspect_ratio=aspect_ratio,
        )
        
        images = []
        for img in response.images:
            img_bytes = img._image_bytes
            images.append({
                "base64": base64.b64encode(img_bytes).decode('utf-8'),
                "mime_type": "image/png"
            })
        
        return {"success": True, "images": images, "count": len(images)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def imagen_edit(image_base64: str, prompt: str, mask_base64: str = None) -> dict:
    """Edit an image using Imagen"""
    try:
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
        image_bytes = base64.b64decode(image_base64)
        
        # Note: Full edit implementation depends on Imagen edit API availability
        return {"success": False, "error": "Imagen edit not fully implemented - use nano_banana_edit instead"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def gemini_analyze_image(image_base64: str, prompt: str = "Describe this image in detail", 
                         model: str = "gemini-2.0-flash-exp") -> dict:
    """Analyze an image using Gemini"""
    try:
        model_id = MODELS.get(model, model)
        gen_model = GenerativeModel(model_id)
        
        image_bytes = base64.b64decode(image_base64)
        image_part = Part.from_image(Image.from_bytes(image_bytes))
        
        response = gen_model.generate_content([image_part, prompt])
        return {"success": True, "analysis": response.text, "model": model_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def gemini_analyze_document(document_text: str, analysis_prompt: str, 
                           model: str = "gemini-1.5-pro") -> dict:
    """Analyze document text using Gemini"""
    try:
        model_id = MODELS.get(model, model)
        gen_model = GenerativeModel(model_id)
        
        full_prompt = f"{analysis_prompt}\n\nDocument:\n{document_text}"
        response = gen_model.generate_content(full_prompt)
        return {"success": True, "analysis": response.text, "model": model_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def gemini_chat(messages: list, system_instruction: str = None, 
                model: str = "gemini-2.0-flash-exp") -> dict:
    """Multi-turn chat with Gemini"""
    try:
        model_id = MODELS.get(model, model)
        gen_model = GenerativeModel(model_id, system_instruction=system_instruction)
        chat = gen_model.start_chat()
        
        for msg in messages[:-1]:
            if msg.get("role") == "user":
                chat.send_message(msg.get("content", ""))
        
        last_msg = messages[-1].get("content", "") if messages else ""
        response = chat.send_message(last_msg)
        
        return {"success": True, "response": response.text, "model": model_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vision_ocr(image_base64: str, language_hints: list = None) -> dict:
    """Extract text from image using Cloud Vision"""
    try:
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image(content=base64.b64decode(image_base64))
        
        context = vision.ImageContext(language_hints=language_hints) if language_hints else None
        response = client.text_detection(image=image, image_context=context)
        
        texts = [{"text": t.description, "bounds": [(v.x, v.y) for v in t.bounding_poly.vertices]} 
                 for t in response.text_annotations]
        
        return {"success": True, "texts": texts, "full_text": texts[0]["text"] if texts else ""}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vision_detect_labels(image_base64: str, max_results: int = 10) -> dict:
    """Detect labels in image"""
    try:
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image(content=base64.b64decode(image_base64))
        response = client.label_detection(image=image, max_results=max_results)
        
        labels = [{"description": l.description, "score": l.score} for l in response.label_annotations]
        return {"success": True, "labels": labels}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vision_detect_objects(image_base64: str) -> dict:
    """Detect and localize objects"""
    try:
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image(content=base64.b64decode(image_base64))
        response = client.object_localization(image=image)
        
        objects = [{
            "name": obj.name,
            "score": obj.score,
            "bounds": [(v.x, v.y) for v in obj.bounding_poly.normalized_vertices]
        } for obj in response.localized_object_annotations]
        
        return {"success": True, "objects": objects}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vision_detect_faces(image_base64: str) -> dict:
    """Detect faces in image"""
    try:
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image(content=base64.b64decode(image_base64))
        response = client.face_detection(image=image)
        
        faces = [{
            "confidence": f.detection_confidence,
            "joy": f.joy_likelihood.name,
            "sorrow": f.sorrow_likelihood.name,
            "anger": f.anger_likelihood.name,
            "surprise": f.surprise_likelihood.name
        } for f in response.face_annotations]
        
        return {"success": True, "faces": faces, "count": len(faces)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vision_detect_logos(image_base64: str) -> dict:
    """Detect logos in image"""
    try:
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image(content=base64.b64decode(image_base64))
        response = client.logo_detection(image=image)
        
        logos = [{"description": l.description, "score": l.score} for l in response.logo_annotations]
        return {"success": True, "logos": logos}
    except Exception as e:
        return {"success": False, "error": str(e)}


def document_parse_pdf(pdf_base64: str, processor_id: str = None) -> dict:
    """Parse PDF using Document AI"""
    return {"success": False, "error": "Document AI parsing requires processor setup - use gemini_analyze_document instead"}


def document_extract_tables(image_base64: str) -> dict:
    """Extract tables from document image"""
    try:
        return gemini_analyze_image(
            image_base64, 
            "Extract all tables from this document image. Format each table as markdown.",
            "gemini-1.5-pro"
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_models() -> dict:
    """List available models"""
    return {
        "success": True,
        "models": {
            "gemini": ["gemini-2.0-flash-exp", "gemini-1.5-pro-002", "gemini-1.5-flash-002"],
            "nano_banana": ["gemini-2.5-flash-preview-05-20 (Nano Banana)", "gemini-2.5-pro-preview-05-06 (Nano Banana Pro)"],
            "imagen": ["imagen-3.0-generate-001"],
            "vision": ["Cloud Vision API v1"],
            "document_ai": ["Document AI API v1"]
        }
    }


# ============== MCP ENDPOINTS ==============

@app.route('/mcp', methods=['POST'])
def mcp_handler():
    """Main MCP JSON-RPC handler"""
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
                    "serverInfo": {"name": "vertex-ai-mcp", "version": "2.0.0"},
                    "capabilities": {"tools": {}}
                }
            })
        
        elif method == 'tools/list':
            return jsonify({"jsonrpc": "2.0", "id": request_id, "result": {"tools": MCP_TOOLS}})
        
        elif method == 'tools/call':
            tool_name = params.get('name')
            arguments = params.get('arguments', {})
            
            # Route to appropriate function
            tool_map = {
                'gemini_generate': gemini_generate,
                'nano_banana_generate': nano_banana_generate,
                'nano_banana_pro_generate': nano_banana_pro_generate,
                'nano_banana_edit': nano_banana_edit,
                'imagen_generate': imagen_generate,
                'imagen_edit': imagen_edit,
                'gemini_analyze_image': gemini_analyze_image,
                'gemini_analyze_document': gemini_analyze_document,
                'gemini_chat': gemini_chat,
                'vision_ocr': vision_ocr,
                'vision_detect_labels': vision_detect_labels,
                'vision_detect_objects': vision_detect_objects,
                'vision_detect_faces': vision_detect_faces,
                'vision_detect_logos': vision_detect_logos,
                'document_parse_pdf': document_parse_pdf,
                'document_extract_tables': document_extract_tables,
                'list_models': list_models,
            }
            
            func = tool_map.get(tool_name)
            if func:
                result = func(**arguments)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}
            
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
            })
        
        elif method == 'ping':
            return jsonify({"jsonrpc": "2.0", "id": request_id, "result": {}})
        
        return jsonify({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })
        
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "service": "vertex-ai-mcp",
        "version": "2.0.0",
        "project": GOOGLE_PROJECT_ID,
        "features": ["gemini", "nano_banana", "nano_banana_pro", "imagen", "vision", "document_ai"]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
