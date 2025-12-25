"""
Google Drive MCP Server - Streamable HTTP transport for Claude.ai
"""
import os, json, io, uuid
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import pandas as pd
from PyPDF2 import PdfReader
from pptx import Presentation
from docx import Document

app = Flask(__name__)
CORS(app, resources={r"/mcp": {"origins": "*", "methods": ["POST", "OPTIONS"], "allow_headers": ["Content-Type", "Mcp-Session-Id"], "expose_headers": ["Mcp-Session-Id"]}})
sessions = {}
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json: raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON not set")
    return build('drive', 'v3', credentials=service_account.Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES))

TOOLS = [
    {"name": "list_folder_contents", "description": "List files in a folder", "inputSchema": {"type": "object", "properties": {"folder_id": {"type": "string"}, "page_size": {"type": "integer", "default": 50}}, "required": ["folder_id"]}},
    {"name": "search_files", "description": "Search files by name", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "folder_id": {"type": "string"}, "file_type": {"type": "string"}}, "required": ["query"]}},
    {"name": "read_excel_file", "description": "Read Excel/Sheets", "inputSchema": {"type": "object", "properties": {"file_id": {"type": "string"}, "sheet_name": {"type": "string"}}, "required": ["file_id"]}},
    {"name": "read_pdf_file", "description": "Extract PDF text", "inputSchema": {"type": "object", "properties": {"file_id": {"type": "string"}, "page_numbers": {"type": "array", "items": {"type": "integer"}}}, "required": ["file_id"]}},
    {"name": "read_powerpoint_file", "description": "Extract PowerPoint text", "inputSchema": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}},
    {"name": "read_word_file", "description": "Extract Word text", "inputSchema": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}},
    {"name": "read_text_file", "description": "Read text files", "inputSchema": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}},
    {"name": "get_file_metadata", "description": "Get file metadata", "inputSchema": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}}
]

def download_file(svc, fid):
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=fid))
    done = False
    while not done: _, done = dl.next_chunk()
    buf.seek(0)
    return buf

def export_file(svc, fid, mime):
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().export_media(fileId=fid, mimeType=mime))
    done = False
    while not done: _, done = dl.next_chunk()
    buf.seek(0)
    return buf

def list_folder_contents(folder_id, page_size=50):
    svc = get_drive_service()
    files = svc.files().list(q=f"'{folder_id}' in parents and trashed=false", pageSize=min(page_size, 100), fields="files(id,name,mimeType,size,modifiedTime)").execute().get('files', [])
    return {"files": [{"id": f['id'], "name": f['name'], "type": f['mimeType'], "size": f.get('size', 'N/A'), "modified": f.get('modifiedTime')} for f in files]}

def search_files(query, folder_id=None, file_type=None):
    svc = get_drive_service()
    q = f"name contains '{query}' and trashed=false"
    if folder_id: q += f" and '{folder_id}' in parents"
    mime_map = {"spreadsheet": "application/vnd.google-apps.spreadsheet", "document": "application/vnd.google-apps.document", "pdf": "application/pdf", "presentation": "application/vnd.google-apps.presentation", "folder": "application/vnd.google-apps.folder"}
    if file_type in mime_map: q += f" and mimeType='{mime_map[file_type]}'"
    return {"files": svc.files().list(q=q, pageSize=50, fields="files(id,name,mimeType,size)").execute().get('files', [])}

def read_excel_file(file_id, sheet_name=None):
    svc = get_drive_service()
    meta = svc.files().get(fileId=file_id, fields="mimeType,name").execute()
    buf = export_file(svc, file_id, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') if 'spreadsheet' in meta.get('mimeType', '') else download_file(svc, file_id)
    if sheet_name:
        df = pd.read_excel(buf, sheet_name=sheet_name)
        return {"file_name": meta['name'], "sheet": sheet_name, "columns": list(df.columns), "row_count": len(df), "data": df.head(100).to_dict(orient='records')}
    xlsx = pd.ExcelFile(buf)
    return {"file_name": meta['name'], "sheets": xlsx.sheet_names, "data": {s: {"columns": list((df := pd.read_excel(xlsx, sheet_name=s)).columns), "rows": len(df), "data": df.head(50).to_dict(orient='records')} for s in xlsx.sheet_names[:5]}}

def read_pdf_file(file_id, page_numbers=None):
    svc = get_drive_service()
    meta = svc.files().get(fileId=file_id, fields="name").execute()
    reader = PdfReader(download_file(svc, file_id))
    pages = page_numbers or range(min(len(reader.pages), 20))
    return {"file_name": meta['name'], "total_pages": len(reader.pages), "content": [{"page": p+1, "text": reader.pages[p].extract_text()} for p in pages if 0 <= p < len(reader.pages)]}

def read_powerpoint_file(file_id):
    svc = get_drive_service()
    meta = svc.files().get(fileId=file_id, fields="mimeType,name").execute()
    buf = export_file(svc, file_id, 'application/vnd.openxmlformats-officedocument.presentationml.presentation') if 'presentation' in meta.get('mimeType', '') else download_file(svc, file_id)
    prs = Presentation(buf)
    return {"file_name": meta['name'], "slides": [{"num": i+1, "text": "\n".join([s.text for s in sl.shapes if hasattr(s, "text")])} for i, sl in enumerate(prs.slides)]}

def read_word_file(file_id):
    svc = get_drive_service()
    meta = svc.files().get(fileId=file_id, fields="mimeType,name").execute()
    buf = export_file(svc, file_id, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') if 'document' in meta.get('mimeType', '') else download_file(svc, file_id)
    return {"file_name": meta['name'], "paragraphs": [p.text for p in Document(buf).paragraphs if p.text.strip()][:100]}

def read_text_file(file_id):
    svc = get_drive_service()
    meta = svc.files().get(fileId=file_id, fields="name").execute()
    return {"file_name": meta['name'], "content": download_file(svc, file_id).read().decode('utf-8', errors='replace')[:50000]}

def get_file_metadata(file_id):
    svc = get_drive_service()
    f = svc.files().get(fileId=file_id, fields="id,name,mimeType,size,createdTime,modifiedTime,owners,webViewLink").execute()
    return {"id": f['id'], "name": f['name'], "type": f['mimeType'], "size": f.get('size'), "created": f.get('createdTime'), "modified": f.get('modifiedTime'), "owner": f.get('owners', [{}])[0].get('emailAddress'), "link": f.get('webViewLink')}

def execute_tool(name, args):
    dispatch = {"list_folder_contents": lambda: list_folder_contents(args.get('folder_id'), args.get('page_size', 50)), "search_files": lambda: search_files(args.get('query'), args.get('folder_id'), args.get('file_type')), "read_excel_file": lambda: read_excel_file(args.get('file_id'), args.get('sheet_name')), "read_pdf_file": lambda: read_pdf_file(args.get('file_id'), args.get('page_numbers')), "read_powerpoint_file": lambda: read_powerpoint_file(args.get('file_id')), "read_word_file": lambda: read_word_file(args.get('file_id')), "read_text_file": lambda: read_text_file(args.get('file_id')), "get_file_metadata": lambda: get_file_metadata(args.get('file_id'))}
    if name not in dispatch: raise ValueError(f"Unknown tool: {name}")
    return dispatch[name]()

@app.route('/mcp', methods=['POST', 'OPTIONS'])
def mcp():
    if request.method == 'OPTIONS':
        r = make_response('', 204)
        r.headers['Access-Control-Allow-Origin'] = '*'
        r.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        r.headers['Access-Control-Allow-Headers'] = 'Content-Type, Mcp-Session-Id'
        r.headers['Access-Control-Expose-Headers'] = 'Mcp-Session-Id'
        return r
    try: data = request.get_json()
    except: return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    if not data: return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    method, params, rid = data.get('method'), data.get('params', {}), data.get('id')
    sid = request.headers.get('Mcp-Session-Id')
    if not sid and method == "initialize": sid = str(uuid.uuid4()); sessions[sid] = True
    try:
        if method == 'initialize': result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "google-drive-mcp", "version": "2.3.0"}, "capabilities": {"tools": {}}}
        elif method == 'notifications/initialized': return '', 204
        elif method == 'tools/list': result = {"tools": TOOLS}
        elif method == 'tools/call': result = {"content": [{"type": "text", "text": json.dumps(execute_tool(params.get('name'), params.get('arguments', {})), indent=2, default=str)}]}
        else: return jsonify({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Unknown: {method}"}, "id": rid})
        r = make_response(jsonify({"jsonrpc": "2.0", "result": result, "id": rid}))
        r.headers['Access-Control-Expose-Headers'] = 'Mcp-Session-Id'
        if sid: r.headers['Mcp-Session-Id'] = sid
        return r
    except Exception as e: return jsonify({"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)}, "id": rid})

@app.route('/health')
def health(): return jsonify({"status": "healthy"})

@app.route('/')
def root(): return jsonify({"service": "Google Drive MCP", "version": "2.3.0", "endpoint": "/mcp"})

if __name__ == '__main__': app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
