"""
Asana MCP Server - Direct API access for project management
Version: 1.0.0
"""

import os
import json
import httpx
from flask import Flask, request, jsonify

app = Flask(__name__)

ASANA_TOKEN = os.environ.get("ASANA_TOKEN")
ASANA_WORKSPACE_ID = os.environ.get("ASANA_WORKSPACE_ID")
BASE_URL = "https://app.asana.com/api/1.0"

def get_headers():
    return {"Authorization": f"Bearer {ASANA_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}

def asana_request(method, endpoint, data=None, params=None):
    url = f"{BASE_URL}{endpoint}"
    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, headers=get_headers(), params=params)
            elif method == "POST":
                response = client.post(url, headers=get_headers(), json={"data": data} if data else None)
            elif method == "PUT":
                response = client.put(url, headers=get_headers(), json={"data": data} if data else None)
            elif method == "DELETE":
                response = client.delete(url, headers=get_headers())
            if response.status_code >= 400:
                return {"error": response.text, "status_code": response.status_code}
            return response.json() if response.text else {"success": True}
    except Exception as e:
        return {"error": str(e)}

TOOLS = [
    {"name": "list_projects", "description": "List all projects in the workspace", "inputSchema": {"type": "object", "properties": {"archived": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 50}}, "required": []}},
    {"name": "get_project", "description": "Get details of a specific project", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}},
    {"name": "create_project", "description": "Create a new project", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "notes": {"type": "string"}, "due_date": {"type": "string"}, "team": {"type": "string"}, "public": {"type": "boolean", "default": False}}, "required": ["name"]}},
    {"name": "list_tasks", "description": "List tasks with optional filters", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "assignee": {"type": "string"}, "completed": {"type": "boolean"}, "section": {"type": "string"}, "limit": {"type": "integer", "default": 50}}, "required": []}},
    {"name": "get_task", "description": "Get detailed information about a task", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "create_task", "description": "Create a new task", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "notes": {"type": "string"}, "project_id": {"type": "string"}, "section_id": {"type": "string"}, "assignee": {"type": "string"}, "due_date": {"type": "string"}, "due_at": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "parent": {"type": "string"}}, "required": ["name"]}},
    {"name": "update_task", "description": "Update an existing task", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "name": {"type": "string"}, "notes": {"type": "string"}, "assignee": {"type": "string"}, "due_date": {"type": "string"}, "due_at": {"type": "string"}, "completed": {"type": "boolean"}}, "required": ["task_id"]}},
    {"name": "complete_task", "description": "Mark a task as complete", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "add_comment", "description": "Add a comment to a task", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["task_id", "text"]}},
    {"name": "get_task_comments", "description": "Get comments on a task", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "list_sections", "description": "List sections in a project", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}},
    {"name": "create_section", "description": "Create a new section in a project", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["project_id", "name"]}},
    {"name": "move_task_to_section", "description": "Move a task to a different section", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "section_id": {"type": "string"}}, "required": ["task_id", "section_id"]}},
    {"name": "search_tasks", "description": "Search for tasks in the workspace", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "assignee": {"type": "string"}, "projects": {"type": "string"}, "completed": {"type": "boolean"}, "due_on": {"type": "string"}, "due_before": {"type": "string"}, "due_after": {"type": "string"}, "is_subtask": {"type": "boolean"}, "limit": {"type": "integer", "default": 25}}, "required": []}},
    {"name": "get_my_tasks", "description": "Get tasks assigned to the authenticated user", "inputSchema": {"type": "object", "properties": {"completed": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 50}}, "required": []}},
    {"name": "get_user", "description": "Get information about a user", "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string", "default": "me"}}, "required": []}},
    {"name": "list_workspace_users", "description": "List all users in the workspace", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100}}, "required": []}},
    {"name": "list_tags", "description": "List all tags in the workspace", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100}}, "required": []}},
    {"name": "add_task_to_project", "description": "Add an existing task to a project", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "project_id": {"type": "string"}, "section_id": {"type": "string"}}, "required": ["task_id", "project_id"]}},
    {"name": "delete_task", "description": "Delete a task permanently", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "get_subtasks", "description": "Get subtasks of a parent task", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "list_teams", "description": "List all teams in the workspace", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100}}, "required": []}}
]

def list_projects(args):
    params = {"workspace": ASANA_WORKSPACE_ID, "archived": args.get("archived", False), "limit": min(args.get("limit", 50), 100), "opt_fields": "name,notes,due_date,owner.name,public,archived"}
    result = asana_request("GET", "/projects", params=params)
    return result if "error" in result else {"success": True, "count": len(result.get("data", [])), "projects": result.get("data", [])}

def get_project(args):
    result = asana_request("GET", f"/projects/{args['project_id']}", params={"opt_fields": "name,notes,due_date,owner.name,public,archived,team.name,members.name"})
    return result if "error" in result else {"success": True, "project": result.get("data")}

def create_project(args):
    data = {"name": args["name"], "workspace": ASANA_WORKSPACE_ID}
    for k in ["notes", "due_date", "team"]: 
        if args.get(k): data[k if k != "due_date" else "due_date"] = args[k]
    if "public" in args: data["public"] = args["public"]
    result = asana_request("POST", "/projects", data=data)
    return result if "error" in result else {"success": True, "project": result.get("data")}

def list_tasks(args):
    params = {"limit": min(args.get("limit", 50), 100), "opt_fields": "name,notes,assignee.name,due_on,due_at,completed,tags.name,projects.name"}
    if args.get("project_id"): params["project"] = args["project_id"]
    if args.get("section"): params["section"] = args["section"]
    if args.get("assignee"): params["assignee"], params["workspace"] = args["assignee"], ASANA_WORKSPACE_ID
    if "completed" in args and not args["completed"]: params["completed_since"] = "now"
    result = asana_request("GET", "/tasks", params=params)
    return result if "error" in result else {"success": True, "count": len(result.get("data", [])), "tasks": result.get("data", [])}

def get_task(args):
    result = asana_request("GET", f"/tasks/{args['task_id']}", params={"opt_fields": "name,notes,assignee.name,due_on,due_at,completed,tags.name,projects.name,parent.name,custom_fields"})
    return result if "error" in result else {"success": True, "task": result.get("data")}

def create_task(args):
    data = {"name": args["name"]}
    if args.get("notes"): data["notes"] = args["notes"]
    if args.get("assignee"): data["assignee"] = args["assignee"]
    if args.get("due_date"): data["due_on"] = args["due_date"]
    if args.get("due_at"): data["due_at"] = args["due_at"]
    if args.get("project_id"): data["projects"] = [args["project_id"]]
    if args.get("tags"): data["tags"] = args["tags"]
    if args.get("parent"): data["parent"] = args["parent"]
    if not args.get("project_id") and not args.get("parent"): data["workspace"] = ASANA_WORKSPACE_ID
    result = asana_request("POST", "/tasks", data=data)
    if "error" in result: return result
    task = result.get("data")
    if args.get("section_id") and task: asana_request("POST", f"/sections/{args['section_id']}/addTask", data={"task": task["gid"]})
    return {"success": True, "task": task}

def update_task(args):
    task_id = args.pop("task_id")
    data = {}
    if args.get("name"): data["name"] = args["name"]
    if args.get("notes"): data["notes"] = args["notes"]
    if args.get("assignee"): data["assignee"] = args["assignee"]
    if args.get("due_date"): data["due_on"] = args["due_date"]
    if args.get("due_at"): data["due_at"] = args["due_at"]
    if "completed" in args: data["completed"] = args["completed"]
    result = asana_request("PUT", f"/tasks/{task_id}", data=data)
    return result if "error" in result else {"success": True, "task": result.get("data")}

def complete_task(args):
    result = asana_request("PUT", f"/tasks/{args['task_id']}", data={"completed": True})
    return result if "error" in result else {"success": True, "task": result.get("data"), "message": "Task marked complete"}

def add_comment(args):
    result = asana_request("POST", f"/tasks/{args['task_id']}/stories", data={"text": args["text"]})
    return result if "error" in result else {"success": True, "comment": result.get("data")}

def get_task_comments(args):
    result = asana_request("GET", f"/tasks/{args['task_id']}/stories", params={"opt_fields": "text,created_at,created_by.name,type"})
    if "error" in result: return result
    stories = [s for s in result.get("data", []) if s.get("type") == "comment"]
    return {"success": True, "count": len(stories), "comments": stories}

def list_sections(args):
    result = asana_request("GET", f"/projects/{args['project_id']}/sections")
    return result if "error" in result else {"success": True, "sections": result.get("data", [])}

def create_section(args):
    result = asana_request("POST", f"/projects/{args['project_id']}/sections", data={"name": args["name"]})
    return result if "error" in result else {"success": True, "section": result.get("data")}

def move_task_to_section(args):
    result = asana_request("POST", f"/sections/{args['section_id']}/addTask", data={"task": args["task_id"]})
    return result if "error" in result else {"success": True, "message": "Task moved to section"}

def search_tasks(args):
    params = {"workspace": ASANA_WORKSPACE_ID, "opt_fields": "name,assignee.name,due_on,completed,projects.name"}
    if args.get("text"): params["text"] = args["text"]
    if args.get("assignee"): params["assignee.any"] = args["assignee"]
    if args.get("projects"): params["projects.any"] = args["projects"]
    if "completed" in args: params["completed"] = args["completed"]
    if args.get("due_on"): params["due_on"] = args["due_on"]
    if args.get("due_before"): params["due_on.before"] = args["due_before"]
    if args.get("due_after"): params["due_on.after"] = args["due_after"]
    if "is_subtask" in args: params["is_subtask"] = args["is_subtask"]
    result = asana_request("GET", f"/workspaces/{ASANA_WORKSPACE_ID}/tasks/search", params=params)
    return result if "error" in result else {"success": True, "count": len(result.get("data", [])), "tasks": result.get("data", [])}

def get_my_tasks(args):
    user_result = asana_request("GET", "/users/me")
    if "error" in user_result: return user_result
    user_gid = user_result.get("data", {}).get("gid")
    params = {"assignee": user_gid, "workspace": ASANA_WORKSPACE_ID, "limit": min(args.get("limit", 50), 100), "opt_fields": "name,due_on,due_at,completed,projects.name,notes"}
    if not args.get("completed", False): params["completed_since"] = "now"
    result = asana_request("GET", "/tasks", params=params)
    return result if "error" in result else {"success": True, "count": len(result.get("data", [])), "tasks": result.get("data", [])}

def get_user(args):
    result = asana_request("GET", f"/users/{args.get('user_id', 'me')}", params={"opt_fields": "name,email,photo,workspaces.name"})
    return result if "error" in result else {"success": True, "user": result.get("data")}

def list_workspace_users(args):
    result = asana_request("GET", f"/workspaces/{ASANA_WORKSPACE_ID}/users", params={"limit": min(args.get("limit", 100), 100), "opt_fields": "name,email"})
    return result if "error" in result else {"success": True, "users": result.get("data", [])}

def list_tags(args):
    result = asana_request("GET", "/tags", params={"workspace": ASANA_WORKSPACE_ID, "limit": min(args.get("limit", 100), 100)})
    return result if "error" in result else {"success": True, "tags": result.get("data", [])}

def add_task_to_project(args):
    data = {"project": args["project_id"]}
    if args.get("section_id"): data["section"] = args["section_id"]
    result = asana_request("POST", f"/tasks/{args['task_id']}/addProject", data=data)
    return result if "error" in result else {"success": True, "message": "Task added to project"}

def delete_task(args):
    result = asana_request("DELETE", f"/tasks/{args['task_id']}")
    return result if "error" in result else {"success": True, "message": f"Task {args['task_id']} deleted"}

def get_subtasks(args):
    result = asana_request("GET", f"/tasks/{args['task_id']}/subtasks", params={"opt_fields": "name,completed,assignee.name,due_on"})
    return result if "error" in result else {"success": True, "subtasks": result.get("data", [])}

def list_teams(args):
    result = asana_request("GET", f"/workspaces/{ASANA_WORKSPACE_ID}/teams", params={"limit": min(args.get("limit", 100), 100)})
    return result if "error" in result else {"success": True, "teams": result.get("data", [])}

TOOL_HANDLERS = {"list_projects": list_projects, "get_project": get_project, "create_project": create_project, "list_tasks": list_tasks, "get_task": get_task, "create_task": create_task, "update_task": update_task, "complete_task": complete_task, "add_comment": add_comment, "get_task_comments": get_task_comments, "list_sections": list_sections, "create_section": create_section, "move_task_to_section": move_task_to_section, "search_tasks": search_tasks, "get_my_tasks": get_my_tasks, "get_user": get_user, "list_workspace_users": list_workspace_users, "list_tags": list_tags, "add_task_to_project": add_task_to_project, "delete_task": delete_task, "get_subtasks": get_subtasks, "list_teams": list_teams}

@app.route("/", methods=["GET"])
def health():
    return jsonify({"service": "asana-mcp", "version": "1.0.0", "status": "healthy", "workspace_id": ASANA_WORKSPACE_ID, "token_configured": bool(ASANA_TOKEN)})

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    data = request.get_json()
    method, req_id, params = data.get("method"), data.get("id"), data.get("params", {})
    if method == "initialize":
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "asana-mcp", "version": "1.0.0"}, "capabilities": {"tools": {"listChanged": False}}}})
    elif method == "tools/list":
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        tool_name, arguments = params.get("name"), params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}], "isError": True}})
        try:
            result = handler(arguments)
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}})
        except Exception as e:
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}})
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
