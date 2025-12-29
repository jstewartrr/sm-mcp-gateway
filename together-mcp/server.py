"""
Together AI MCP Server for Sovereign Mind
Provides access to open-source LLMs, fine-tuning, and embeddings
"""

import os
import json
import httpx
from typing import Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("together-ai")

TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY")
BASE_URL = "https://api.together.xyz/v1"

def get_headers():
    return {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }

# ============== INFERENCE ==============

@mcp.tool()
async def together_chat(
    prompt: str,
    model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    system_prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    top_p: float = 0.9
) -> dict:
    """
    Chat completion with Together AI models.
    Popular models: meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo, 
    meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo,
    mistralai/Mixtral-8x7B-Instruct-v0.1,
    deepseek-ai/DeepSeek-R1
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{BASE_URL}/chat/completions",
            headers=get_headers(),
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p
            }
        )
        response.raise_for_status()
        data = response.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "model": data["model"],
            "usage": data.get("usage", {})
        }

@mcp.tool()
async def together_completion(
    prompt: str,
    model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    max_tokens: int = 512,
    temperature: float = 0.7,
    stop: Optional[list] = None
) -> dict:
    """Raw text completion (non-chat format)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        if stop:
            payload["stop"] = stop
            
        response = await client.post(
            f"{BASE_URL}/completions",
            headers=get_headers(),
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        return {
            "text": data["choices"][0]["text"],
            "model": data["model"],
            "usage": data.get("usage", {})
        }

# ============== EMBEDDINGS ==============

@mcp.tool()
async def together_embeddings(
    texts: list,
    model: str = "togethercomputer/m2-bert-80M-32k-retrieval"
) -> dict:
    """
    Generate embeddings for texts.
    Models: togethercomputer/m2-bert-80M-32k-retrieval, BAAI/bge-large-en-v1.5
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/embeddings",
            headers=get_headers(),
            json={
                "model": model,
                "input": texts
            }
        )
        response.raise_for_status()
        data = response.json()
        return {
            "embeddings": [item["embedding"] for item in data["data"]],
            "model": data["model"],
            "usage": data.get("usage", {})
        }

# ============== MODELS ==============

@mcp.tool()
async def together_list_models(
    model_type: Optional[str] = None
) -> dict:
    """
    List available models. 
    model_type: 'chat', 'language', 'code', 'image', 'embedding', 'moderation'
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/models",
            headers=get_headers()
        )
        response.raise_for_status()
        models = response.json()
        
        if model_type:
            models = [m for m in models if m.get("type") == model_type]
        
        # Return summary
        return {
            "count": len(models),
            "models": [
                {
                    "id": m["id"],
                    "type": m.get("type"),
                    "context_length": m.get("context_length"),
                    "pricing": m.get("pricing", {})
                }
                for m in models[:50]  # Limit to 50
            ]
        }

# ============== FINE-TUNING ==============

@mcp.tool()
async def together_create_finetune(
    training_file: str,
    model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Reference",
    n_epochs: int = 3,
    learning_rate: float = 1e-5,
    suffix: Optional[str] = None
) -> dict:
    """
    Create a fine-tuning job.
    training_file: File ID from uploaded training data
    model: Base model to fine-tune
    """
    payload = {
        "training_file": training_file,
        "model": model,
        "n_epochs": n_epochs,
        "learning_rate": learning_rate
    }
    if suffix:
        payload["suffix"] = suffix
        
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/fine-tunes",
            headers=get_headers(),
            json=payload
        )
        response.raise_for_status()
        return response.json()

@mcp.tool()
async def together_list_finetunes() -> dict:
    """List all fine-tuning jobs."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/fine-tunes",
            headers=get_headers()
        )
        response.raise_for_status()
        return response.json()

@mcp.tool()
async def together_get_finetune(finetune_id: str) -> dict:
    """Get details of a specific fine-tuning job."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/fine-tunes/{finetune_id}",
            headers=get_headers()
        )
        response.raise_for_status()
        return response.json()

@mcp.tool()
async def together_cancel_finetune(finetune_id: str) -> dict:
    """Cancel a running fine-tuning job."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}/fine-tunes/{finetune_id}/cancel",
            headers=get_headers()
        )
        response.raise_for_status()
        return response.json()

# ============== FILES ==============

@mcp.tool()
async def together_upload_file(
    file_path: str,
    purpose: str = "fine-tune"
) -> dict:
    """
    Upload a file for fine-tuning.
    File should be JSONL format with 'text' field or conversation format.
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/jsonl")}
            data = {"purpose": purpose}
            
            # Remove Content-Type header for multipart
            headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
            
            response = await client.post(
                f"{BASE_URL}/files",
                headers=headers,
                files=files,
                data=data
            )
            response.raise_for_status()
            return response.json()

@mcp.tool()
async def together_list_files() -> dict:
    """List all uploaded files."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/files",
            headers=get_headers()
        )
        response.raise_for_status()
        return response.json()

@mcp.tool()
async def together_delete_file(file_id: str) -> dict:
    """Delete an uploaded file."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{BASE_URL}/files/{file_id}",
            headers=get_headers()
        )
        response.raise_for_status()
        return {"deleted": True, "id": file_id}

# ============== IMAGE GENERATION ==============

@mcp.tool()
async def together_generate_image(
    prompt: str,
    model: str = "black-forest-labs/FLUX.1-schnell-Free",
    width: int = 1024,
    height: int = 1024,
    steps: int = 4,
    n: int = 1
) -> dict:
    """
    Generate images using Together AI.
    Models: black-forest-labs/FLUX.1-schnell-Free, stabilityai/stable-diffusion-xl-base-1.0
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{BASE_URL}/images/generations",
            headers=get_headers(),
            json={
                "model": model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "n": n
            }
        )
        response.raise_for_status()
        data = response.json()
        return {
            "images": [img.get("url") or img.get("b64_json") for img in data["data"]],
            "model": model
        }

if __name__ == "__main__":
    mcp.run(transport="sse")
