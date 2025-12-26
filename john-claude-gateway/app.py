"""
John Claude Unified MCP Gateway
"""
import os, json, uuid, requests
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import snowflake.connector

app = Flask(__name__)
CORS(app, resources={r"/mcp": {"origins": "*", "methods": ["POST", "OPTIONS"], "allow_headers": ["Content-Type", "Mcp-Session-Id"]}})

SERVICES = {"snowflake": {"url": None, "type": "internal"}, "google_drive": {"url": "https://google-drive-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"}, "elevenlabs": {"url": "https://elevenlabs-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp", "type": "http"}, "simli": {"url": "https://simli-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"}, "notebooklm": {"url": "https://notebooklm-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"}}
ALL_TOOLS, TOOL_REGISTRY = [], {}
GATEWAY_TOOLS = [{"name": "hive_mind_query", "description": "Query Hive Mind", "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["sql"]}}, {"name": "hive_mind_write", "description": "Write to Hive Mind", "inputSchema": {"type": "object", "properties": {"category": {"type": "string"}, "summary": {"type": "string"}}, "required": ["category", "summary"]}}, {"name": "list_services", "description": "List MCP services", "inputSchema": {"type": "object", "properties": {}}}]

def get_sf(): return snowflake.connector.connect(user=os.environ.get('SNOWFLAKE_USER','JOHN_CLAUDE'), password=os.environ.get('SNOWFLAKE_PASSWORD'), account=os.environ.get('SNOWFLAKE_ACCOUNT'), warehouse='SOVEREIGN_MIND_WH', database='SOVEREIGN_MIND', schema='RAW')

def exec_gw(n, a):
    if n == "hive_mind_query":
        try:
            c = get_sf(); cur = c.cursor(); sql = a.get('sql','')
            if 'LIMIT' not in sql.upper(): sql += f" LIMIT {a.get('limit',10)}"
            cur.execute(sql); r = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]; cur.close(); c.close()
            return {"success": True, "data": r}
        except Exception as e: return {"error": str(e)}
    elif n == "hive_mind_write":
        try:
            c = get_sf(); cur = c.cursor()
            cur.execute(f"INSERT INTO SHARED_MEMORY (SOURCE,CATEGORY,SUMMARY,STATUS) VALUES ('GATEWAY','{a.get('category','')}','{a.get('summary','').replace(chr(39),chr(39)+chr(39))}','ACTIVE')")
            c.commit(); cur.close(); c.close(); return {"success": True}
        except Exception as e: return {"error": str(e)}
    elif n == "list_services": return {"services": list(SERVICES.keys()), "tools": len(ALL_TOOLS)}
    return {"error": "Unknown"}

def discover(sn, cfg):
    if cfg["type"] == "internal": return []
    try:
        r = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}},"id":1}, timeout=10)
        if r.status_code == 200:
            tr = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}, timeout=10)
            if tr.status_code == 200:
                tools = []
                for t in tr.json().get("result",{}).get("tools",[]):
                    orig = t["name"]; t["name"] = f"{sn}_{orig}"; t["description"] = f"[{sn.upper()}] {t.get('description','')}"
                    TOOL_REGISTRY[t["name"]] = {"s": sn, "o": orig}; tools.append(t)
                return tools
    except: pass
    return []

def proxy(sn, orig, args):
    cfg = SERVICES.get(sn)
    if not cfg: return {"error": "Unknown"}
    try:
        r = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"tools/call","params":{"name":orig,"arguments":args},"id":3}, timeout=60)
        return r.json().get("result",{}) if r.status_code == 200 else {"error": str(r.status_code)}
    except Exception as e: return {"error": str(e)}

@app.route('/mcp', methods=['POST','OPTIONS'])
def mcp():
    global ALL_TOOLS
    if request.method == 'OPTIONS': return '', 204
    try: d = request.get_json(force=True)
    except: return jsonify({"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse"},"id":None})
    m, p, rid = d.get('method'), d.get('params',{}), d.get('id')
    sid = request.headers.get('Mcp-Session-Id') or str(uuid.uuid4())
    try:
        if m == 'initialize':
            if not ALL_TOOLS: ALL_TOOLS = [t for sn,cfg in SERVICES.items() for t in discover(sn,cfg)]
            result = {"protocolVersion":"2024-11-05","serverInfo":{"name":"john-claude-gateway","version":"1.0"},"capabilities":{"tools":{}}}
        elif m == 'notifications/initialized': return '', 204
        elif m == 'tools/list': result = {"tools": GATEWAY_TOOLS + ALL_TOOLS}
        elif m == 'tools/call':
            tn, ta = p.get('name'), p.get('arguments',{})
            if tn in [t["name"] for t in GATEWAY_TOOLS]: tr = exec_gw(tn, ta)
            elif tn in TOOL_REGISTRY: tr = proxy(TOOL_REGISTRY[tn]["s"], TOOL_REGISTRY[tn]["o"], ta)
            else: tr = {"error": f"Unknown: {tn}"}
            result = {"content":[{"type":"text","text":json.dumps(tr,default=str)}]}
        else: return jsonify({"jsonrpc":"2.0","error":{"code":-32601,"message":m},"id":rid})
        r = make_response(jsonify({"jsonrpc":"2.0","result":result,"id":rid}))
        r.headers['Access-Control-Expose-Headers'] = 'Mcp-Session-Id'; r.headers['Mcp-Session-Id'] = sid
        return r
    except Exception as e: return jsonify({"jsonrpc":"2.0","error":{"code":-32000,"message":str(e)},"id":rid})

@app.route('/health')
def health(): return jsonify({"status":"ok","tools":len(ALL_TOOLS)})

@app.route('/')
def root(): return jsonify({"service":"John Claude Gateway","endpoint":"/mcp","services":list(SERVICES.keys())})

if __name__ == '__main__':
    ALL_TOOLS = [t for sn,cfg in SERVICES.items() for t in discover(sn,cfg)]
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8080)))
