"""
Google Drive MCP Server with SSE transport for Claude.ai
"""

import os
import json
import io
import base64
from flask import Flask, request, jsonify, Response
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import pandas as pd
from PyPDF2 import PdfReader
from pptx import Presentation
from docx import Document

app = Flask(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
    creds_dict = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('drive', 'v3', credentials=credentials)

TOOLS = [
    {
        "name": "list_folder_contents",
        "description": "List all files and folders in a Google Drive folder. Returns file names, IDs, types, and sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "The Google Drive folder ID. Use 'root' for the root folder."},
                "page_size": {"type": "integer", "description": "Number of files to return (max 100)", "default": 50}
            },
            "required": ["folder_id"]
        }
    },
    {
        "name": "search_files",
        "description": "Search for files in Google Drive by name or content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (file name or content)"},
                "folder_id": {"type": "string", "description": "Optional folder ID to limit search scope"},
                "file_type": {"type": "string", "description": "Filter by file type: spreadsheet, document, pdf, presentation, folder"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_excel_file",
        "description": "Read an Excel file (.xlsx, .xls) or Google Sheet and return its contents as JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID"},
                "sheet_name": {"type": "string", "description": "Specific sheet name to read (optional)"}
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "read_pdf_file",
        "description": "Read a PDF file and extract its text content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID"},
                "page_numbers": {"type": "array", "items": {"type": "integer"}, "description": "Specific pages to read"}
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "read_powerpoint_file",
        "description": "Read a PowerPoint file (.pptx) or Google Slides and extract text from all slides.",
        "inputSchema": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": "The Google Drive file ID"}},
            "required": ["file_id"]
        }
    },
    {
        "name": "read_word_file",
        "description": "Read a Word document (.docx) or Google Doc and extract its text content.",
        "inputSchema": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": "The Google Drive file ID"}},
            "required": ["file_id"]
        }
    },
    {
        "name": "read_text_file",
        "description": "Read a text-based file (txt, csv, json, etc.) and return its contents.",
        "inputSchema": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": "The Google Drive file ID"}},
            "required": ["file_id"]
        }
    },
    {
        "name": "get_file_metadata",
        "description": "Get detailed metadata about a file including name, size, created date, modified date, owner.",
        "inputSchema": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": "The Google Drive file ID"}},
            "required": ["file_id"]
        }
    }
]

# Tool implementations
def download_file(service, file_id):
    request = service.files().get_media(fileId=file_id)
    file_buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(file_buffer, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    file_buffer.seek(0)
    return file_buffer

def export_google_file(service, file_id, mime_type):
    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    file_buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(file_buffer, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    file_buffer.seek(0)
    return file_buffer

def list_folder_contents(folder_id, page_size=50):
    service = get_drive_service()
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query, pageSize=min(page_size, 100),
        fields="files(id, name, mimeType, size, createdTime, modifiedTime, owners)"
    ).execute()
    files = results.get('files', [])
    formatted = [{"id": f.get('id'), "name": f.get('name'), "type": f.get('mimeType'),
                  "size": f.get('size', 'N/A'), "modified": f.get('modifiedTime')} for f in files]
    return {"files": formatted, "count": len(formatted)}

def search_files(query, folder_id=None, file_type=None):
    service = get_drive_service()
    search_query = f"name contains '{query}' and trashed = false"
    if folder_id:
        search_query += f" and '{folder_id}' in parents"
    mime_map = {"spreadsheet": "application/vnd.google-apps.spreadsheet",
                "document": "application/vnd.google-apps.document", "pdf": "application/pdf",
                "presentation": "application/vnd.google-apps.presentation",
                "folder": "application/vnd.google-apps.folder"}
    if file_type and file_type in mime_map:
        search_query += f" and mimeType = '{mime_map[file_type]}'"
    results = service.files().list(q=search_query, pageSize=50,
                                   fields="files(id, name, mimeType, size, modifiedTime)").execute()
    return {"files": results.get('files', []), "query": search_query}

def read_excel_file(file_id, sheet_name=None):
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime_type = file_meta.get('mimeType')
    if mime_type == 'application/vnd.google-apps.spreadsheet':
        file_buffer = export_google_file(service, file_id, 
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        file_buffer = download_file(service, file_id)
    if sheet_name:
        df = pd.read_excel(file_buffer, sheet_name=sheet_name)
        return {"file_name": file_meta.get('name'), "sheet": sheet_name,
                "columns": list(df.columns), "row_count": len(df), "data": df.head(100).to_dict(orient='records')}
    else:
        xlsx = pd.ExcelFile(file_buffer)
        sheets_data = {}
        for sheet in xlsx.sheet_names[:5]:
            df = pd.read_excel(xlsx, sheet_name=sheet)
            sheets_data[sheet] = {"columns": list(df.columns), "row_count": len(df),
                                  "data": df.head(50).to_dict(orient='records')}
        return {"file_name": file_meta.get('name'), "sheets": list(xlsx.sheet_names), "data": sheets_data}

def read_pdf_file(file_id, page_numbers=None):
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="name").execute()
    file_buffer = download_file(service, file_id)
    reader = PdfReader(file_buffer)
    total_pages = len(reader.pages)
    pages_to_read = page_numbers if page_numbers else range(min(total_pages, 20))
    text_content = []
    for page_num in pages_to_read:
        if 0 <= page_num < total_pages:
            text_content.append({"page": page_num + 1, "text": reader.pages[page_num].extract_text()})
    return {"file_name": file_meta.get('name'), "total_pages": total_pages, "content": text_content}

def read_powerpoint_file(file_id):
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    if file_meta.get('mimeType') == 'application/vnd.google-apps.presentation':
        file_buffer = export_google_file(service, file_id,
            'application/vnd.openxmlformats-officedocument.presentationml.presentation')
    else:
        file_buffer = download_file(service, file_id)
    prs = Presentation(file_buffer)
    slides = []
    for idx, slide in enumerate(prs.slides):
        text = "\n".join([shape.text for shape in slide.shapes if hasattr(shape, "text")])
        slides.append({"slide_number": idx + 1, "text": text})
    return {"file_name": file_meta.get('name'), "total_slides": len(prs.slides), "slides": slides}

def read_word_file(file_id):
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    if file_meta.get('mimeType') == 'application/vnd.google-apps.document':
        file_buffer = export_google_file(service, file_id,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    else:
        file_buffer = download_file(service, file_id)
    doc = Document(file_buffer)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return {"file_name": file_meta.get('name'), "paragraph_count": len(paragraphs), "paragraphs": paragraphs[:100]}

def read_text_file(file_id):
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    file_buffer = download_file(service, file_id)
    content = file_buffer.read().decode('utf-8', errors='replace')
    return {"file_name": file_meta.get('name'), "content": content[:50000]}

def get_file_metadata(file_id):
    service = get_drive_service()
    f = service.files().get(fileId=file_id,
        fields="id,name,mimeType,size,createdTime,modifiedTime,owners,webViewLink").execute()
    return {"id": f.get('id'), "name": f.get('name'), "mime_type": f.get('mimeType'),
            "size": f.get('size'), "created": f.get('createdTime'), "modified": f.get('modifiedTime'),
            "owner": f.get('owners', [{}])[0].get('emailAddress'), "web_link": f.get('webViewLink')}

def execute_tool(name, args):
    if name == 'list_folder_contents':
        return list_folder_contents(args.get('folder_id'), args.get('page_size', 50))
    elif name == 'search_files':
        return search_files(args.get('query'), args.get('folder_id'), args.get('file_type'))
    elif name == 'read_excel_file':
        return read_excel_file(args.get('file_id'), args.get('sheet_name'))
    elif name == 'read_pdf_file':
        return read_pdf_file(args.get('file_id'), args.get('page_numbers'))
    elif name == 'read_powerpoint_file':
        return read_powerpoint_file(args.get('file_id'))
    elif name == 'read_word_file':
        return read_word_file(args.get('file_id'))
    elif name == 'read_text_file':
        return read_text_file(args.get('file_id'))
    elif name == 'get_file_metadata':
        return get_file_metadata(args.get('file_id'))
    else:
        raise ValueError(f"Unknown tool: {name}")

def generate_sse():
    """SSE generator for MCP protocol"""
    import time
    # Send endpoint info for client to POST to
    endpoint_event = {
        "jsonrpc": "2.0",
        "method": "endpoint",
        "params": {"url": "/messages"}
    }
    yield f"event: endpoint\ndata: {json.dumps(endpoint_event)}\n\n"
    
    # Keep connection alive
    while True:
        yield f": keepalive\n\n"
        time.sleep(30)

# SSE endpoint for Claude.ai MCP - supports both /sse and /mcp paths
@app.route('/sse', methods=['GET'])
def mcp_sse():
    """SSE endpoint for MCP protocol - Claude.ai connects here"""
    return Response(generate_sse(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive',
                             'Access-Control-Allow-Origin': '*'})

@app.route('/mcp', methods=['GET'])
def mcp_endpoint():
    """SSE endpoint at /mcp path for Claude.ai MCP connector"""
    return Response(generate_sse(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive',
                             'Access-Control-Allow-Origin': '*'})

@app.route('/messages', methods=['POST'])
def mcp_messages():
    """Handle MCP JSON-RPC requests"""
    data = request.get_json()
    if not data:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    
    method = data.get('method')
    params = data.get('params', {})
    req_id = data.get('id')
    
    try:
        if method == 'initialize':
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "google-drive-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}}
            }
        elif method == 'tools/list':
            result = {"tools": TOOLS}
        elif method == 'tools/call':
            tool_name = params.get('name')
            tool_args = params.get('arguments', {})
            tool_result = execute_tool(tool_name, tool_args)
            result = {"content": [{"type": "text", "text": json.dumps(tool_result, indent=2, default=str)}]}
        else:
            return jsonify({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}, "id": req_id})
        
        return jsonify({"jsonrpc": "2.0", "result": result, "id": req_id})
    
    except Exception as e:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)}, "id": req_id})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "google-drive-mcp"})

@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "Google Drive MCP Server", "version": "1.0.1", "sse_endpoint": "/sse", "mcp_endpoint": "/mcp", "messages_endpoint": "/messages"})

# Log startup
print("Google Drive MCP Server starting...", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting server on port {port}", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)