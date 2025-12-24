"""
Google Drive MCP Server
Provides full access to Google Drive files including Excel, PDF, PowerPoint, etc.
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
import openpyxl

app = Flask(__name__)

# Google Drive API setup
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    """Initialize Google Drive service with service account credentials."""
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=credentials)

# MCP Protocol Implementation
def create_mcp_response(result):
    """Format response according to MCP protocol."""
    return jsonify(result)

def create_error_response(error_msg, code=-1):
    """Format error response."""
    return jsonify({"error": {"code": code, "message": error_msg}})

# Tool definitions
TOOLS = [
    {
        "name": "list_folder_contents",
        "description": "List all files and folders in a Google Drive folder. Returns file names, IDs, types, and sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "The Google Drive folder ID. Use 'root' for the root folder."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of files to return (max 100)",
                    "default": 50
                }
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
                "query": {
                    "type": "string",
                    "description": "Search query (file name or content)"
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional folder ID to limit search scope"
                },
                "file_type": {
                    "type": "string",
                    "description": "Filter by file type: spreadsheet, document, pdf, presentation, folder"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_excel_file",
        "description": "Read an Excel file (.xlsx, .xls) and return its contents as JSON. Can read specific sheets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "Specific sheet name to read (optional, reads all if not specified)"
                }
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
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                },
                "page_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific page numbers to read (optional, reads all if not specified)"
                }
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "read_powerpoint_file",
        "description": "Read a PowerPoint file (.pptx) and extract text from all slides.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                }
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "read_word_file",
        "description": "Read a Word document (.docx) and extract its text content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                }
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "read_text_file",
        "description": "Read a text-based file (txt, csv, json, etc.) and return its contents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                }
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "get_file_metadata",
        "description": "Get detailed metadata about a file including name, size, created date, modified date, owner, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                }
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "download_file_base64",
        "description": "Download a file and return its contents as base64 encoded string.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The Google Drive file ID"
                }
            },
            "required": ["file_id"]
        }
    }
]

def download_file(service, file_id):
    """Download a file from Google Drive."""
    request = service.files().get_media(fileId=file_id)
    file_buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(file_buffer, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    file_buffer.seek(0)
    return file_buffer

def export_google_file(service, file_id, mime_type):
    """Export a Google Workspace file to specified format."""
    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    file_buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(file_buffer, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    file_buffer.seek(0)
    return file_buffer

# Tool implementations
def list_folder_contents(folder_id, page_size=50):
    """List contents of a folder."""
    service = get_drive_service()
    
    query = f"'{folder_id}' in parents and trashed = false"
    
    results = service.files().list(
        q=query,
        pageSize=min(page_size, 100),
        fields="files(id, name, mimeType, size, createdTime, modifiedTime, owners)"
    ).execute()
    
    files = results.get('files', [])
    
    formatted_files = []
    for f in files:
        formatted_files.append({
            "id": f.get('id'),
            "name": f.get('name'),
            "type": f.get('mimeType'),
            "size": f.get('size', 'N/A'),
            "created": f.get('createdTime'),
            "modified": f.get('modifiedTime'),
            "owner": f.get('owners', [{}])[0].get('emailAddress', 'Unknown')
        })
    
    return {"files": formatted_files, "count": len(formatted_files)}

def search_files(query, folder_id=None, file_type=None):
    """Search for files in Google Drive."""
    service = get_drive_service()
    
    search_query = f"name contains '{query}' and trashed = false"
    
    if folder_id:
        search_query += f" and '{folder_id}' in parents"
    
    mime_type_map = {
        "spreadsheet": "application/vnd.google-apps.spreadsheet",
        "document": "application/vnd.google-apps.document",
        "pdf": "application/pdf",
        "presentation": "application/vnd.google-apps.presentation",
        "folder": "application/vnd.google-apps.folder",
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
    
    if file_type and file_type in mime_type_map:
        search_query += f" and mimeType = '{mime_type_map[file_type]}'"
    
    results = service.files().list(
        q=search_query,
        pageSize=50,
        fields="files(id, name, mimeType, size, modifiedTime, parents)"
    ).execute()
    
    return {"files": results.get('files', []), "query": search_query}

def read_excel_file(file_id, sheet_name=None):
    """Read an Excel file and return contents as JSON."""
    service = get_drive_service()
    
    # Get file metadata to check type
    file_meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime_type = file_meta.get('mimeType')
    
    # Handle Google Sheets - export as Excel
    if mime_type == 'application/vnd.google-apps.spreadsheet':
        file_buffer = export_google_file(
            service, file_id, 
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        file_buffer = download_file(service, file_id)
    
    # Read with pandas
    if sheet_name:
        df = pd.read_excel(file_buffer, sheet_name=sheet_name)
        return {
            "file_name": file_meta.get('name'),
            "sheet": sheet_name,
            "columns": list(df.columns),
            "row_count": len(df),
            "data": df.to_dict(orient='records')
        }
    else:
        # Read all sheets
        xlsx = pd.ExcelFile(file_buffer)
        sheets_data = {}
        for sheet in xlsx.sheet_names:
            df = pd.read_excel(xlsx, sheet_name=sheet)
            sheets_data[sheet] = {
                "columns": list(df.columns),
                "row_count": len(df),
                "data": df.to_dict(orient='records')
            }
        return {
            "file_name": file_meta.get('name'),
            "sheets": list(xlsx.sheet_names),
            "data": sheets_data
        }

def read_pdf_file(file_id, page_numbers=None):
    """Read a PDF file and extract text."""
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="name").execute()
    file_buffer = download_file(service, file_id)
    
    reader = PdfReader(file_buffer)
    total_pages = len(reader.pages)
    
    pages_to_read = page_numbers if page_numbers else range(total_pages)
    
    text_content = []
    for page_num in pages_to_read:
        if 0 <= page_num < total_pages:
            page = reader.pages[page_num]
            text_content.append({
                "page": page_num + 1,
                "text": page.extract_text()
            })
    
    return {
        "file_name": file_meta.get('name'),
        "total_pages": total_pages,
        "pages_read": len(text_content),
        "content": text_content
    }

def read_powerpoint_file(file_id):
    """Read a PowerPoint file and extract text from slides."""
    service = get_drive_service()
    
    file_meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime_type = file_meta.get('mimeType')
    
    # Handle Google Slides - export as PPTX
    if mime_type == 'application/vnd.google-apps.presentation':
        file_buffer = export_google_file(
            service, file_id,
            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        )
    else:
        file_buffer = download_file(service, file_id)
    
    prs = Presentation(file_buffer)
    
    slides_content = []
    for idx, slide in enumerate(prs.slides):
        slide_text = []
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                slide_text.append(shape.text)
        slides_content.append({
            "slide_number": idx + 1,
            "text": "\n".join(slide_text)
        })
    
    return {
        "file_name": file_meta.get('name'),
        "total_slides": len(prs.slides),
        "slides": slides_content
    }

def read_word_file(file_id):
    """Read a Word document and extract text."""
    service = get_drive_service()
    
    file_meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime_type = file_meta.get('mimeType')
    
    # Handle Google Docs - export as DOCX
    if mime_type == 'application/vnd.google-apps.document':
        file_buffer = export_google_file(
            service, file_id,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    else:
        file_buffer = download_file(service, file_id)
    
    doc = Document(file_buffer)
    
    paragraphs = []
    for para in doc.paragraphs:
        if para.text.strip():
            paragraphs.append(para.text)
    
    # Extract tables
    tables_content = []
    for table_idx, table in enumerate(doc.tables):
        table_data = []
        for row in table.rows:
            row_data = [cell.text for cell in row.cells]
            table_data.append(row_data)
        tables_content.append({
            "table_number": table_idx + 1,
            "data": table_data
        })
    
    return {
        "file_name": file_meta.get('name'),
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
        "tables": tables_content
    }

def read_text_file(file_id):
    """Read a text-based file."""
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    file_buffer = download_file(service, file_id)
    
    content = file_buffer.read().decode('utf-8', errors='replace')
    
    return {
        "file_name": file_meta.get('name'),
        "mime_type": file_meta.get('mimeType'),
        "content": content
    }

def get_file_metadata(file_id):
    """Get detailed file metadata."""
    service = get_drive_service()
    
    file_meta = service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,createdTime,modifiedTime,owners,parents,webViewLink,webContentLink"
    ).execute()
    
    return {
        "id": file_meta.get('id'),
        "name": file_meta.get('name'),
        "mime_type": file_meta.get('mimeType'),
        "size_bytes": file_meta.get('size'),
        "created": file_meta.get('createdTime'),
        "modified": file_meta.get('modifiedTime'),
        "owner": file_meta.get('owners', [{}])[0].get('emailAddress'),
        "parent_folders": file_meta.get('parents', []),
        "web_view_link": file_meta.get('webViewLink'),
        "download_link": file_meta.get('webContentLink')
    }

def download_file_base64(file_id):
    """Download file and return as base64."""
    service = get_drive_service()
    file_meta = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    file_buffer = download_file(service, file_id)
    
    content = file_buffer.read()
    base64_content = base64.b64encode(content).decode('utf-8')
    
    return {
        "file_name": file_meta.get('name'),
        "mime_type": file_meta.get('mimeType'),
        "size_bytes": file_meta.get('size'),
        "base64_content": base64_content
    }

# Route handlers
@app.route('/mcp', methods=['GET', 'POST'])
def mcp_endpoint():
    """Main MCP endpoint."""
    if request.method == 'GET':
        return jsonify({
            "name": "google-drive-mcp",
            "version": "1.0.0",
            "description": "Google Drive MCP Server - Full file access including Excel, PDF, PowerPoint",
            "tools": TOOLS
        })
    
    # Handle POST requests
    data = request.get_json()
    
    if not data:
        return create_error_response("No JSON data provided")
    
    method = data.get('method')
    params = data.get('params', {})
    
    if method == 'tools/list':
        return jsonify({"tools": TOOLS})
    
    elif method == 'tools/call':
        tool_name = params.get('name')
        tool_args = params.get('arguments', {})
        
        try:
            if tool_name == 'list_folder_contents':
                result = list_folder_contents(
                    tool_args.get('folder_id'),
                    tool_args.get('page_size', 50)
                )
            elif tool_name == 'search_files':
                result = search_files(
                    tool_args.get('query'),
                    tool_args.get('folder_id'),
                    tool_args.get('file_type')
                )
            elif tool_name == 'read_excel_file':
                result = read_excel_file(
                    tool_args.get('file_id'),
                    tool_args.get('sheet_name')
                )
            elif tool_name == 'read_pdf_file':
                result = read_pdf_file(
                    tool_args.get('file_id'),
                    tool_args.get('page_numbers')
                )
            elif tool_name == 'read_powerpoint_file':
                result = read_powerpoint_file(tool_args.get('file_id'))
            elif tool_name == 'read_word_file':
                result = read_word_file(tool_args.get('file_id'))
            elif tool_name == 'read_text_file':
                result = read_text_file(tool_args.get('file_id'))
            elif tool_name == 'get_file_metadata':
                result = get_file_metadata(tool_args.get('file_id'))
            elif tool_name == 'download_file_base64':
                result = download_file_base64(tool_args.get('file_id'))
            else:
                return create_error_response(f"Unknown tool: {tool_name}")
            
            return jsonify({"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]})
        
        except Exception as e:
            return create_error_response(str(e))
    
    return create_error_response("Unknown method")

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "google-drive-mcp"})

@app.route('/', methods=['GET'])
def root():
    """Root endpoint."""
    return jsonify({
        "service": "Google Drive MCP Server",
        "version": "1.0.0",
        "endpoints": {
            "/mcp": "MCP protocol endpoint",
            "/health": "Health check"
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
