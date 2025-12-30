"""
Sovereign Mind MCP Gateway v1.8.0
==========================
Unified MCP server that aggregates tools from multiple backend services.
Provides single connection point for Claude.ai, ElevenLabs ABBI, and future agents.

v1.8.0 - Added Google Drive tools (list, search, read, upload, move)
v1.7.0 - Added M365 Email/Calendar integration
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import uvicorn
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sm_gateway")

# ============================================================================
# CONFIGURATION
# ============================================================================

class GatewayConfig:
    """Central configuration loaded from environment variables."""
    
    # Snowflake
    SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT", "jga82554.east-us-2.azure")
    SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER", "JOHN_CLAUDE")
    SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD", "")
    SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "SOVEREIGN_MIND_WH")
    SNOWFLAKE_DATABASE = os.getenv("SNOWFLAKE_DATABASE", "SOVEREIGN_MIND")
    SNOWFLAKE_ROLE = os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
    
    # Asana - check both ASANA_TOKEN and ASANA_ACCESS_TOKEN
    ASANA_ACCESS_TOKEN = os.getenv("ASANA_TOKEN") or os.getenv("ASANA_ACCESS_TOKEN", "")
    ASANA_WORKSPACE_ID = os.getenv("ASANA_WORKSPACE_ID", "373563495855656")
    
    # Make.com
    MAKE_API_KEY = os.getenv("MAKE_API_KEY", "")
    MAKE_ORGANIZATION_ID = os.getenv("MAKE_ORGANIZATION_ID", "5726294")
    MAKE_TEAM_ID = os.getenv("MAKE_TEAM_ID", "1576120")
    
    # GitHub
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    
    # ElevenLabs
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
    
    # Google Cloud
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    
    # M365 / Microsoft Graph
    M365_TENANT_ID = os.getenv("M365_TENANT_ID", "")
    M365_CLIENT_ID = os.getenv("M365_CLIENT_ID", "")
    M365_CLIENT_SECRET = os.getenv("M365_CLIENT_SECRET", "")
    M365_DEFAULT_USER = os.getenv("M365_DEFAULT_USER", "john@middlegroundcapital.com")

config = GatewayConfig()

# ============================================================================
# SHARED UTILITIES
# ============================================================================

async def make_api_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    json_data: Optional[Dict] = None,
    params: Optional[Dict] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """Generic async HTTP request handler with error handling."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {
                "error": True,
                "status_code": e.response.status_code,
                "message": f"HTTP {e.response.status_code}: {e.response.text[:500]}"
            }
        except httpx.TimeoutException:
            return {"error": True, "message": "Request timed out"}
        except Exception as e:
            return {"error": True, "message": str(e)}

def format_error(message: str, suggestion: str = "") -> str:
    """Format error message with optional suggestion."""
    result = f"Error: {message}"
    if suggestion:
        result += f"\nSuggestion: {suggestion}"
    return result

# ============================================================================
# M365 TOKEN MANAGEMENT
# ============================================================================

_m365_token_cache = {"token": None, "expires_at": 0}

async def get_m365_token() -> str:
    """Get M365 access token using client credentials flow."""
    import time
    
    # Check cache
    if _m365_token_cache["token"] and time.time() < _m365_token_cache["expires_at"] - 60:
        return _m365_token_cache["token"]
    
    # Get new token
    token_url = f"https://login.microsoftonline.com/{config.M365_TENANT_ID}/oauth2/v2.0/token"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "client_id": config.M365_CLIENT_ID,
                "client_secret": config.M365_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials"
            }
        )
        response.raise_for_status()
        data = response.json()
        
        _m365_token_cache["token"] = data["access_token"]
        _m365_token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
        
        return data["access_token"]

async def m365_graph_request(
    method: str,
    endpoint: str,
    json_data: Optional[Dict] = None,
    params: Optional[Dict] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """Make authenticated request to Microsoft Graph API."""
    try:
        token = await get_m365_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = f"https://graph.microsoft.com/v1.0{endpoint}"
        
        return await make_api_request(
            method=method,
            url=url,
            headers=headers,
            json_data=json_data,
            params=params,
            timeout=timeout
        )
    except Exception as e:
        return {"error": True, "message": str(e)}

# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================

@asynccontextmanager
async def gateway_lifespan():
    """Initialize shared resources for the gateway."""
    # Initialize Snowflake connection
    snowflake_conn = None
    try:
        import snowflake.connector
        snowflake_conn = snowflake.connector.connect(
            user=config.SNOWFLAKE_USER,
            password=config.SNOWFLAKE_PASSWORD,
            account=config.SNOWFLAKE_ACCOUNT,
            warehouse=config.SNOWFLAKE_WAREHOUSE,
            database=config.SNOWFLAKE_DATABASE,
            role=config.SNOWFLAKE_ROLE
        )
        logger.info("Snowflake connection established")
    except Exception as e:
        logger.warning(f"Snowflake connection failed: {e}")
    
    yield {"snowflake_conn": snowflake_conn}
    
    # Cleanup
    if snowflake_conn:
        snowflake_conn.close()
        logger.info("Snowflake connection closed")

# ============================================================================
# INITIALIZE MCP SERVER
# ============================================================================

mcp = FastMCP(
    "sovereign_mind_gateway",
    lifespan=gateway_lifespan
)

# ============================================================================
# SNOWFLAKE TOOLS
# ============================================================================

class SnowflakeQueryInput(BaseModel):
    """Input for Snowflake SQL queries."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    sql: str = Field(
        ..., 
        description="SQL query to execute against Snowflake",
        min_length=1,
        max_length=50000
    )
    database: Optional[str] = Field(
        default=None,
        description="Database to use (defaults to SOVEREIGN_MIND)"
    )

@mcp.tool(
    name="sm_query_snowflake",
    annotations={
        "title": "[SM] Execute SQL query on Snowflake as JOHN_CLAUDE",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def snowflake_query(params: SnowflakeQueryInput) -> str:
    """Execute a SQL query against Snowflake and return results.
    
    Supports all SQL operations including SELECT, INSERT, UPDATE, DELETE.
    Results are returned as JSON with column names and row data.
    """
    try:
        import snowflake.connector
        
        conn = snowflake.connector.connect(
            user=config.SNOWFLAKE_USER,
            password=config.SNOWFLAKE_PASSWORD,
            account=config.SNOWFLAKE_ACCOUNT,
            warehouse=config.SNOWFLAKE_WAREHOUSE,
            database=params.database or config.SNOWFLAKE_DATABASE,
            role=config.SNOWFLAKE_ROLE
        )
        
        cursor = conn.cursor()
        cursor.execute(params.sql)
        
        # Get column names
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        
        # Fetch results
        rows = cursor.fetchall()
        
        # Convert to list of dicts
        results = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Handle datetime and other non-serializable types
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                elif isinstance(value, bytes):
                    value = value.decode('utf-8', errors='replace')
                row_dict[col] = value
            results.append(row_dict)
        
        cursor.close()
        conn.close()
        
        return json.dumps({
            "success": True,
            "row_count": len(results),
            "data": results
        }, indent=2, default=str)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })

# ============================================================================
# M365 EMAIL TOOLS
# ============================================================================

class M365ReadEmailsInput(BaseModel):
    """Input for reading M365 emails."""
    user_email: str = Field(
        default="john@middlegroundcapital.com",
        description="User email to read from"
    )
    folder: str = Field(
        default="inbox",
        description="Folder to read from (inbox, sentitems, drafts, or folder ID)"
    )
    top: int = Field(
        default=25,
        description="Number of emails to retrieve",
        ge=1,
        le=100
    )
    filter: Optional[str] = Field(
        default=None,
        description="OData filter expression (e.g., \"isRead eq false\")"
    )
    search: Optional[str] = Field(
        default=None,
        description="Search query for email content"
    )

@mcp.tool(
    name="m365_read_emails",
    annotations={
        "title": "[M365] Read Emails",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def m365_read_emails(params: M365ReadEmailsInput) -> str:
    """Read emails from a user's mailbox.
    
    Returns emails with subject, sender, date, and preview.
    """
    endpoint = f"/users/{params.user_email}/mailFolders/{params.folder}/messages"
    
    query_params = {
        "$top": params.top,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments"
    }
    
    if params.filter:
        query_params["$filter"] = params.filter
    if params.search:
        query_params["$search"] = f'"{params.search}"'
    
    result = await m365_graph_request("GET", endpoint, params=query_params)
    
    # Simplify response
    if "value" in result:
        emails = []
        for email in result["value"]:
            emails.append({
                "id": email.get("id"),
                "subject": email.get("subject"),
                "from": email.get("from", {}).get("emailAddress", {}).get("address"),
                "from_name": email.get("from", {}).get("emailAddress", {}).get("name"),
                "received": email.get("receivedDateTime"),
                "isRead": email.get("isRead"),
                "preview": email.get("bodyPreview", "")[:200],
                "hasAttachments": email.get("hasAttachments")
            })
        return json.dumps({"success": True, "count": len(emails), "emails": emails}, indent=2)
    
    return json.dumps(result, indent=2)

class M365GetEmailInput(BaseModel):
    """Input for getting a specific email."""
    user_email: str = Field(default="john@middlegroundcapital.com")
    message_id: str = Field(..., description="Email message ID")

@mcp.tool(
    name="m365_get_email",
    annotations={
        "title": "[M365] Get Email Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def m365_get_email(params: M365GetEmailInput) -> str:
    """Get full details of a specific email including body."""
    endpoint = f"/users/{params.user_email}/messages/{params.message_id}"
    
    query_params = {
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,importance"
    }
    
    result = await m365_graph_request("GET", endpoint, params=query_params)
    return json.dumps(result, indent=2)

class M365SearchEmailsInput(BaseModel):
    """Input for searching emails."""
    user_email: str = Field(default="john@middlegroundcapital.com")
    query: str = Field(..., description="Search query")
    top: int = Field(default=25, ge=1, le=100)

@mcp.tool(
    name="m365_search_emails",
    annotations={
        "title": "[M365] Search Emails",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def m365_search_emails(params: M365SearchEmailsInput) -> str:
    """Search emails across all folders."""
    endpoint = f"/users/{params.user_email}/messages"
    
    query_params = {
        "$search": f'"{params.query}"',
        "$top": params.top,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,bodyPreview,parentFolderId"
    }
    
    result = await m365_graph_request("GET", endpoint, params=query_params)
    
    if "value" in result:
        emails = []
        for email in result["value"]:
            emails.append({
                "id": email.get("id"),
                "subject": email.get("subject"),
                "from": email.get("from", {}).get("emailAddress", {}).get("address"),
                "received": email.get("receivedDateTime"),
                "preview": email.get("bodyPreview", "")[:200],
                "folder": email.get("parentFolderId")
            })
        return json.dumps({"success": True, "count": len(emails), "emails": emails}, indent=2)
    
    return json.dumps(result, indent=2)

class M365ListFoldersInput(BaseModel):
    """Input for listing mail folders."""
    user_email: str = Field(default="john@middlegroundcapital.com")

@mcp.tool(
    name="m365_list_folders",
    annotations={
        "title": "[M365] List Mail Folders",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def m365_list_folders(params: M365ListFoldersInput) -> str:
    """List all mail folders for a user."""
    endpoint = f"/users/{params.user_email}/mailFolders"
    
    query_params = {
        "$select": "id,displayName,totalItemCount,unreadItemCount",
        "$top": 100
    }
    
    result = await m365_graph_request("GET", endpoint, params=query_params)
    
    if "value" in result:
        folders = []
        for folder in result["value"]:
            folders.append({
                "id": folder.get("id"),
                "name": folder.get("displayName"),
                "total": folder.get("totalItemCount"),
                "unread": folder.get("unreadItemCount")
            })
        return json.dumps({"success": True, "folders": folders}, indent=2)
    
    return json.dumps(result, indent=2)

class M365SendEmailInput(BaseModel):
    """Input for sending an email."""
    user_email: str = Field(default="john@middlegroundcapital.com")
    to: List[str] = Field(..., description="List of recipient email addresses")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (HTML supported)")
    cc: Optional[List[str]] = Field(default=None, description="CC recipients")
    importance: str = Field(default="normal", description="normal, high, or low")

@mcp.tool(
    name="m365_send_email",
    annotations={
        "title": "[M365] Send Email",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def m365_send_email(params: M365SendEmailInput) -> str:
    """Send an email on behalf of a user."""
    endpoint = f"/users/{params.user_email}/sendMail"
    
    message = {
        "subject": params.subject,
        "body": {
            "contentType": "HTML",
            "content": params.body
        },
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in params.to],
        "importance": params.importance
    }
    
    if params.cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in params.cc]
    
    result = await m365_graph_request("POST", endpoint, json_data={"message": message})
    
    if not result.get("error"):
        return json.dumps({"success": True, "message": "Email sent successfully"}, indent=2)
    
    return json.dumps(result, indent=2)

# ============================================================================
# M365 CALENDAR TOOLS
# ============================================================================

class M365ListEventsInput(BaseModel):
    """Input for listing calendar events."""
    user_email: str = Field(default="john@middlegroundcapital.com")
    start_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")
    top: int = Field(default=25, ge=1, le=100)

@mcp.tool(
    name="m365_list_events",
    annotations={
        "title": "[M365] List Calendar Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def m365_list_events(params: M365ListEventsInput) -> str:
    """List calendar events for a user."""
    from datetime import datetime, timedelta
    
    # Default to next 7 days if no dates specified
    if not params.start_date:
        start = datetime.utcnow()
        params.start_date = start.strftime("%Y-%m-%dT00:00:00Z")
    else:
        params.start_date = f"{params.start_date}T00:00:00Z"
    
    if not params.end_date:
        end = datetime.utcnow() + timedelta(days=7)
        params.end_date = end.strftime("%Y-%m-%dT23:59:59Z")
    else:
        params.end_date = f"{params.end_date}T23:59:59Z"
    
    endpoint = f"/users/{params.user_email}/calendarView"
    
    query_params = {
        "startDateTime": params.start_date,
        "endDateTime": params.end_date,
        "$top": params.top,
        "$orderby": "start/dateTime",
        "$select": "id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeetingUrl"
    }
    
    result = await m365_graph_request("GET", endpoint, params=query_params)
    
    if "value" in result:
        events = []
        for event in result["value"]:
            events.append({
                "id": event.get("id"),
                "subject": event.get("subject"),
                "start": event.get("start", {}).get("dateTime"),
                "end": event.get("end", {}).get("dateTime"),
                "location": event.get("location", {}).get("displayName"),
                "organizer": event.get("organizer", {}).get("emailAddress", {}).get("address"),
                "attendees": [a.get("emailAddress", {}).get("address") for a in event.get("attendees", [])],
                "isOnline": event.get("isOnlineMeeting"),
                "meetingUrl": event.get("onlineMeetingUrl")
            })
        return json.dumps({"success": True, "count": len(events), "events": events}, indent=2)
    
    return json.dumps(result, indent=2)

class M365CreateEventInput(BaseModel):
    """Input for creating a calendar event."""
    user_email: str = Field(default="john@middlegroundcapital.com")
    subject: str = Field(..., description="Event subject/title")
    start: str = Field(..., description="Start datetime (YYYY-MM-DDTHH:MM:SS)")
    end: str = Field(..., description="End datetime (YYYY-MM-DDTHH:MM:SS)")
    attendees: Optional[List[str]] = Field(default=None, description="Attendee email addresses")
    location: Optional[str] = Field(default=None, description="Event location")
    body: Optional[str] = Field(default=None, description="Event description")
    is_online: bool = Field(default=False, description="Create as Teams meeting")

@mcp.tool(
    name="m365_create_event",
    annotations={
        "title": "[M365] Create Calendar Event",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def m365_create_event(params: M365CreateEventInput) -> str:
    """Create a new calendar event."""
    endpoint = f"/users/{params.user_email}/events"
    
    event = {
        "subject": params.subject,
        "start": {"dateTime": params.start, "timeZone": "America/New_York"},
        "end": {"dateTime": params.end, "timeZone": "America/New_York"},
        "isOnlineMeeting": params.is_online
    }
    
    if params.is_online:
        event["onlineMeetingProvider"] = "teamsForBusiness"
    
    if params.attendees:
        event["attendees"] = [
            {"emailAddress": {"address": addr}, "type": "required"}
            for addr in params.attendees
        ]
    
    if params.location:
        event["location"] = {"displayName": params.location}
    
    if params.body:
        event["body"] = {"contentType": "HTML", "content": params.body}
    
    result = await m365_graph_request("POST", endpoint, json_data=event)
    return json.dumps(result, indent=2)

class M365ListUsersInput(BaseModel):
    """Input for listing M365 users."""
    top: int = Field(default=50, ge=1, le=100)

@mcp.tool(
    name="m365_list_users",
    annotations={
        "title": "[M365] List Organization Users",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def m365_list_users(params: M365ListUsersInput) -> str:
    """List users in the M365 organization."""
    endpoint = "/users"
    
    query_params = {
        "$top": params.top,
        "$select": "id,displayName,mail,jobTitle,department"
    }
    
    result = await m365_graph_request("GET", endpoint, params=query_params)
    
    if "value" in result:
        users = []
        for user in result["value"]:
            users.append({
                "id": user.get("id"),
                "name": user.get("displayName"),
                "email": user.get("mail"),
                "title": user.get("jobTitle"),
                "department": user.get("department")
            })
        return json.dumps({"success": True, "count": len(users), "users": users}, indent=2)
    
    return json.dumps(result, indent=2)

# ============================================================================
# ASANA TOOLS
# ============================================================================

ASANA_BASE_URL = "https://app.asana.com/api/1.0"

def get_asana_headers() -> Dict[str, str]:
    """Get Asana API headers."""
    return {
        "Authorization": f"Bearer {config.ASANA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

class AsanaGetTasksInput(BaseModel):
    """Input for getting Asana tasks."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    assignee: str = Field(
        default="me",
        description="User to get tasks for ('me' or user GID)"
    )
    project: Optional[str] = Field(
        default=None,
        description="Project GID to filter tasks"
    )
    completed: Optional[bool] = Field(
        default=False,
        description="Include completed tasks"
    )
    limit: int = Field(
        default=50,
        description="Maximum tasks to return",
        ge=1,
        le=100
    )

@mcp.tool(
    name="asana_get_tasks",
    annotations={
        "title": "Get Asana Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def asana_get_tasks(params: AsanaGetTasksInput) -> str:
    """Get tasks from Asana for the specified user or project."""
    query_params = {
        "workspace": config.ASANA_WORKSPACE_ID,
        "assignee": params.assignee,
        "limit": params.limit,
        "opt_fields": "name,due_on,completed,notes,projects.name"
    }
    
    if params.project:
        query_params["project"] = params.project
        del query_params["assignee"]
    
    if not params.completed:
        query_params["completed_since"] = "now"
    
    result = await make_api_request(
        method="GET",
        url=f"{ASANA_BASE_URL}/tasks",
        headers=get_asana_headers(),
        params=query_params
    )
    
    return json.dumps(result, indent=2)

class AsanaCreateTaskInput(BaseModel):
    """Input for creating an Asana task."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    name: str = Field(
        ...,
        description="Task name/title",
        min_length=1,
        max_length=500
    )
    notes: Optional[str] = Field(
        default=None,
        description="Task description/notes"
    )
    due_on: Optional[str] = Field(
        default=None,
        description="Due date in YYYY-MM-DD format"
    )
    project: Optional[str] = Field(
        default=None,
        description="Project GID to add task to"
    )
    assignee: str = Field(
        default="me",
        description="User to assign task to"
    )

@mcp.tool(
    name="asana_create_task",
    annotations={
        "title": "Create Asana Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def asana_create_task(params: AsanaCreateTaskInput) -> str:
    """Create a new task in Asana."""
    data = {
        "data": {
            "name": params.name,
            "workspace": config.ASANA_WORKSPACE_ID,
            "assignee": params.assignee
        }
    }
    
    if params.notes:
        data["data"]["notes"] = params.notes
    if params.due_on:
        data["data"]["due_on"] = params.due_on
    if params.project:
        data["data"]["projects"] = [params.project]
    
    result = await make_api_request(
        method="POST",
        url=f"{ASANA_BASE_URL}/tasks",
        headers=get_asana_headers(),
        json_data=data
    )
    
    return json.dumps(result, indent=2)

class AsanaSearchTasksInput(BaseModel):
    """Input for searching Asana tasks."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    text: str = Field(
        ...,
        description="Search text to find in task names/descriptions",
        min_length=1
    )
    completed: Optional[bool] = Field(
        default=None,
        description="Filter by completion status"
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100
    )

@mcp.tool(
    name="asana_search_tasks",
    annotations={
        "title": "Search Asana Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def asana_search_tasks(params: AsanaSearchTasksInput) -> str:
    """Search for tasks in Asana by text."""
    query_params = {
        "text": params.text,
        "opt_fields": "name,due_on,completed,notes,assignee.name,projects.name",
        "limit": params.limit
    }
    
    if params.completed is not None:
        query_params["completed"] = str(params.completed).lower()
    
    result = await make_api_request(
        method="GET",
        url=f"{ASANA_BASE_URL}/workspaces/{config.ASANA_WORKSPACE_ID}/tasks/search",
        headers=get_asana_headers(),
        params=query_params
    )
    
    return json.dumps(result, indent=2)

class AsanaCompleteTaskInput(BaseModel):
    """Input for completing an Asana task."""
    task_id: str = Field(..., description="Task GID to mark complete")

@mcp.tool(
    name="asana_complete_task",
    annotations={
        "title": "Complete Asana Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def asana_complete_task(params: AsanaCompleteTaskInput) -> str:
    """Mark an Asana task as complete."""
    result = await make_api_request(
        method="PUT",
        url=f"{ASANA_BASE_URL}/tasks/{params.task_id}",
        headers=get_asana_headers(),
        json_data={"data": {"completed": True}}
    )
    
    return json.dumps(result, indent=2)

class AsanaGetProjectsInput(BaseModel):
    """Input for listing Asana projects."""
    archived: bool = Field(default=False, description="Include archived projects")
    limit: int = Field(default=50, ge=1, le=100)

@mcp.tool(
    name="asana_get_projects",
    annotations={
        "title": "List Asana Projects",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def asana_get_projects(params: AsanaGetProjectsInput) -> str:
    """List all projects in the Asana workspace."""
    result = await make_api_request(
        method="GET",
        url=f"{ASANA_BASE_URL}/projects",
        headers=get_asana_headers(),
        params={
            "workspace": config.ASANA_WORKSPACE_ID,
            "archived": str(params.archived).lower(),
            "limit": params.limit,
            "opt_fields": "name,owner.name,due_on,current_status"
        }
    )
    
    return json.dumps(result, indent=2)

# ============================================================================
# MAKE.COM TOOLS
# ============================================================================

MAKE_BASE_URL = "https://us1.make.com/api/v2"

def get_make_headers() -> Dict[str, str]:
    """Get Make.com API headers."""
    return {
        "Authorization": f"Token {config.MAKE_API_KEY}",
        "Content-Type": "application/json"
    }

class MakeListScenariosInput(BaseModel):
    """Input for listing Make.com scenarios."""
    limit: int = Field(default=50, ge=1, le=100)

@mcp.tool(
    name="make_list_scenarios",
    annotations={
        "title": "List Make.com Scenarios",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def make_list_scenarios(params: MakeListScenariosInput) -> str:
    """List all scenarios in the Make.com team."""
    result = await make_api_request(
        method="GET",
        url=f"{MAKE_BASE_URL}/scenarios",
        headers=get_make_headers(),
        params={
            "teamId": config.MAKE_TEAM_ID,
            "pg[limit]": params.limit
        }
    )
    
    return json.dumps(result, indent=2)

class MakeRunScenarioInput(BaseModel):
    """Input for running a Make.com scenario."""
    scenario_id: int = Field(..., description="Scenario ID to run")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional input data for the scenario"
    )

@mcp.tool(
    name="make_run_scenario",
    annotations={
        "title": "Run Make.com Scenario",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def make_run_scenario(params: MakeRunScenarioInput) -> str:
    """Execute a Make.com scenario."""
    json_data = {}
    if params.data:
        json_data["data"] = params.data
    
    result = await make_api_request(
        method="POST",
        url=f"{MAKE_BASE_URL}/scenarios/{params.scenario_id}/run",
        headers=get_make_headers(),
        json_data=json_data if json_data else None
    )
    
    return json.dumps(result, indent=2)

class MakeGetScenarioInput(BaseModel):
    """Input for getting Make.com scenario details."""
    scenario_id: int = Field(..., description="Scenario ID to retrieve")

@mcp.tool(
    name="make_get_scenario",
    annotations={
        "title": "Get Make.com Scenario",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def make_get_scenario(params: MakeGetScenarioInput) -> str:
    """Get details of a specific Make.com scenario."""
    result = await make_api_request(
        method="GET",
        url=f"{MAKE_BASE_URL}/scenarios/{params.scenario_id}",
        headers=get_make_headers()
    )
    
    return json.dumps(result, indent=2)

# ============================================================================
# GITHUB TOOLS
# ============================================================================

GITHUB_BASE_URL = "https://api.github.com"

def get_github_headers() -> Dict[str, str]:
    """Get GitHub API headers."""
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

class GitHubListReposInput(BaseModel):
    """Input for listing GitHub repos."""
    type: str = Field(default="owner", description="Type: all, owner, member")
    limit: int = Field(default=30, ge=1, le=100)

@mcp.tool(
    name="github_list_repos",
    annotations={
        "title": "List GitHub Repositories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def github_list_repos(params: GitHubListReposInput) -> str:
    """List GitHub repositories for the authenticated user."""
    result = await make_api_request(
        method="GET",
        url=f"{GITHUB_BASE_URL}/user/repos",
        headers=get_github_headers(),
        params={
            "type": params.type,
            "per_page": params.limit,
            "sort": "updated"
        }
    )
    
    # Simplify the response
    if isinstance(result, list):
        simplified = [
            {
                "name": repo.get("name"),
                "full_name": repo.get("full_name"),
                "description": repo.get("description"),
                "private": repo.get("private"),
                "url": repo.get("html_url"),
                "updated_at": repo.get("updated_at")
            }
            for repo in result
        ]
        return json.dumps({"success": True, "data": simplified}, indent=2)
    
    return json.dumps(result, indent=2)

class GitHubGetFileInput(BaseModel):
    """Input for getting a GitHub file."""
    owner: str = Field(..., description="Repository owner")
    repo: str = Field(..., description="Repository name")
    path: str = Field(..., description="File path in repository")

@mcp.tool(
    name="github_get_file",
    annotations={
        "title": "Get GitHub File",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def github_get_file(params: GitHubGetFileInput) -> str:
    """Get contents of a file from a GitHub repository."""
    result = await make_api_request(
        method="GET",
        url=f"{GITHUB_BASE_URL}/repos/{params.owner}/{params.repo}/contents/{params.path}",
        headers=get_github_headers()
    )
    
    # Decode base64 content if present
    if isinstance(result, dict) and "content" in result:
        import base64
        try:
            content = base64.b64decode(result["content"]).decode("utf-8")
            result["decoded_content"] = content
            del result["content"]  # Remove base64 to save space
        except Exception:
            pass
    
    return json.dumps(result, indent=2)

class GitHubUpdateFileInput(BaseModel):
    """Input for updating a GitHub file."""
    owner: str = Field(..., description="Repository owner")
    repo: str = Field(..., description="Repository name")
    path: str = Field(..., description="File path in repository")
    content: str = Field(..., description="New file content")
    message: str = Field(..., description="Commit message")
    sha: Optional[str] = Field(default=None, description="SHA of the file being replaced (required for updates)")

@mcp.tool(
    name="github_update_file",
    annotations={
        "title": "Update GitHub File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def github_update_file(params: GitHubUpdateFileInput) -> str:
    """Create or update a file in a GitHub repository."""
    import base64
    
    # If no SHA provided, try to get it (for updates)
    sha = params.sha
    if not sha:
        existing = await make_api_request(
            method="GET",
            url=f"{GITHUB_BASE_URL}/repos/{params.owner}/{params.repo}/contents/{params.path}",
            headers=get_github_headers()
        )
        if isinstance(existing, dict) and "sha" in existing:
            sha = existing["sha"]
    
    data = {
        "message": params.message,
        "content": base64.b64encode(params.content.encode()).decode()
    }
    
    if sha:
        data["sha"] = sha
    
    result = await make_api_request(
        method="PUT",
        url=f"{GITHUB_BASE_URL}/repos/{params.owner}/{params.repo}/contents/{params.path}",
        headers=get_github_headers(),
        json_data=data
    )
    
    return json.dumps(result, indent=2)

# ============================================================================
# ELEVENLABS TOOLS  
# ============================================================================

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"

def get_elevenlabs_headers() -> Dict[str, str]:
    """Get ElevenLabs API headers."""
    return {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }

class ElevenLabsListAgentsInput(BaseModel):
    """Input for listing ElevenLabs agents."""
    pass  # No parameters needed

@mcp.tool(
    name="elevenlabs_list_agents",
    annotations={
        "title": "List ElevenLabs Agents",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def elevenlabs_list_agents(params: ElevenLabsListAgentsInput) -> str:
    """List all conversational AI agents in ElevenLabs."""
    result = await make_api_request(
        method="GET",
        url=f"{ELEVENLABS_BASE_URL}/convai/agents",
        headers=get_elevenlabs_headers()
    )
    
    return json.dumps(result, indent=2)

class ElevenLabsGetAgentInput(BaseModel):
    """Input for getting ElevenLabs agent details."""
    agent_id: str = Field(..., description="Agent ID to retrieve")

@mcp.tool(
    name="elevenlabs_get_agent",
    annotations={
        "title": "Get ElevenLabs Agent",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def elevenlabs_get_agent(params: ElevenLabsGetAgentInput) -> str:
    """Get details of a specific ElevenLabs agent."""
    result = await make_api_request(
        method="GET",
        url=f"{ELEVENLABS_BASE_URL}/convai/agents/{params.agent_id}",
        headers=get_elevenlabs_headers()
    )
    
    return json.dumps(result, indent=2)

# ============================================================================
# HIVE MIND TOOLS (Sovereign Mind specific)
# ============================================================================

class HiveMindWriteInput(BaseModel):
    """Input for writing to Hive Mind shared memory."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    source: str = Field(
        ...,
        description="Source identifier (e.g., 'JOHN_CLAUDE', 'ABBI', 'GATEWAY')"
    )
    category: str = Field(
        ...,
        description="Category: CONTEXT, DECISION, ACTION_ITEM, PREFERENCE, MILESTONE"
    )
    workstream: str = Field(
        default="GENERAL",
        description="Workstream or project name"
    )
    summary: str = Field(
        ...,
        description="Clear summary of the memory entry",
        min_length=1,
        max_length=2000
    )
    priority: str = Field(
        default="MEDIUM",
        description="Priority: HIGH, MEDIUM, LOW"
    )

@mcp.tool(
    name="hivemind_write",
    annotations={
        "title": "Write to Hive Mind",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def hivemind_write(params: HiveMindWriteInput) -> str:
    """Write an entry to the Sovereign Mind Hive Mind shared memory."""
    sql = f"""
    INSERT INTO SOVEREIGN_MIND.RAW.HIVE_MIND 
    (SOURCE, CATEGORY, WORKSTREAM, SUMMARY, PRIORITY, STATUS)
    VALUES ('{params.source}', '{params.category}', '{params.workstream}', 
            '{params.summary.replace("'", "''")}', '{params.priority}', 'ACTIVE')
    """
    
    # Use the snowflake_query tool internally
    query_params = SnowflakeQueryInput(sql=sql)
    result = await snowflake_query(query_params)
    
    return json.dumps({
        "success": True,
        "message": f"Memory entry written from {params.source}",
        "category": params.category,
        "workstream": params.workstream
    }, indent=2)

class HiveMindReadInput(BaseModel):
    """Input for reading from Hive Mind."""
    limit: int = Field(default=10, ge=1, le=50)
    source: Optional[str] = Field(default=None, description="Filter by source")
    category: Optional[str] = Field(default=None, description="Filter by category")

@mcp.tool(
    name="hivemind_read",
    annotations={
        "title": "Read from Hive Mind",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def hivemind_read(params: HiveMindReadInput) -> str:
    """Read recent entries from the Sovereign Mind Hive Mind."""
    where_clauses = ["STATUS = 'ACTIVE'"]
    if params.source:
        where_clauses.append(f"SOURCE = '{params.source}'")
    if params.category:
        where_clauses.append(f"CATEGORY = '{params.category}'")
    
    where_sql = " AND ".join(where_clauses)
    
    sql = f"""
    SELECT SOURCE, CATEGORY, WORKSTREAM, SUMMARY, PRIORITY, CREATED_AT
    FROM SOVEREIGN_MIND.RAW.HIVE_MIND
    WHERE {where_sql}
    ORDER BY CREATED_AT DESC
    LIMIT {params.limit}
    """
    
    query_params = SnowflakeQueryInput(sql=sql)
    return await snowflake_query(query_params)

# ============================================================================
# GATEWAY STATUS TOOL
# ============================================================================

class GatewayStatusInput(BaseModel):
    """Input for gateway status check."""
    pass

@mcp.tool(
    name="gateway_status",
    annotations={
        "title": "Gateway Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def gateway_status(params: GatewayStatusInput) -> str:
    """Get the status of the Sovereign Mind MCP Gateway."""
    status = {
        "gateway": "sovereign_mind_gateway",
        "version": "1.7.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "snowflake": {
                "configured": bool(config.SNOWFLAKE_PASSWORD),
                "account": config.SNOWFLAKE_ACCOUNT,
                "database": config.SNOWFLAKE_DATABASE
            },
            "asana": {
                "configured": bool(config.ASANA_ACCESS_TOKEN),
                "workspace_id": config.ASANA_WORKSPACE_ID
            },
            "make": {
                "configured": bool(config.MAKE_API_KEY),
                "team_id": config.MAKE_TEAM_ID
            },
            "github": {
                "configured": bool(config.GITHUB_TOKEN)
            },
            "elevenlabs": {
                "configured": bool(config.ELEVENLABS_API_KEY)
            },
            "m365": {
                "configured": bool(config.M365_CLIENT_SECRET),
                "tenant_id": config.M365_TENANT_ID[:8] + "..." if config.M365_TENANT_ID else None,
                "default_user": config.M365_DEFAULT_USER
            }
        },
        "tools": [
            # Snowflake
            "sm_query_snowflake",
            # M365
            "m365_read_emails", "m365_get_email", "m365_search_emails",
            "m365_list_folders", "m365_send_email",
            "m365_list_events", "m365_create_event", "m365_list_users",
            # Asana
            "asana_get_tasks", "asana_create_task", "asana_search_tasks",
            "asana_complete_task", "asana_get_projects",
            # Make.com
            "make_list_scenarios", "make_run_scenario", "make_get_scenario",
            # GitHub
            "github_list_repos", "github_get_file", "github_update_file",
            # ElevenLabs
            "elevenlabs_list_agents", "elevenlabs_get_agent",
            # Hive Mind
            "hivemind_write", "hivemind_read",
            # Gateway
            "gateway_status"
        ]
    }
    
    return json.dumps(status, indent=2)

# ============================================================================
# MAC STUDIO TOOLS (via Tailscale Funnel)
# ============================================================================

MAC_STUDIO_URL = os.getenv("MAC_STUDIO_URL", "https://mac-studio-1556.tailfb6577.ts.net")

class MacRunCommandInput(BaseModel):
    """Input for running a command on Mac Studio."""
    command: str = Field(..., description="Shell command to execute on Mac Studio")

@mcp.tool(
    name="mac_run_command",
    annotations={
        "title": "[MAC] Run Command on Mac Studio",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def mac_run_command(params: MacRunCommandInput) -> str:
    """Execute a shell command on Mac Studio via Tailscale Funnel."""
    result = await make_api_request(
        method="POST",
        url=f"{MAC_STUDIO_URL}/run",
        headers={"Content-Type": "application/json"},
        json_data={"command": params.command},
        timeout=120.0
    )
    return json.dumps(result, indent=2)

class MacSSHCommandInput(BaseModel):
    """Input for running a command on Raspberry Pi via Mac Studio SSH."""
    command: str = Field(..., description="Command to execute on the Pi")
    host: str = Field(default="192.168.25.225", description="Pi IP address")
    user: str = Field(default="jstewartrr", description="SSH username")

@mcp.tool(
    name="mac_ssh_to_pi",
    annotations={
        "title": "[MAC] SSH Command to Raspberry Pi",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True
    }
)
async def mac_ssh_to_pi(params: MacSSHCommandInput) -> str:
    """Execute a command on Raspberry Pi via SSH through Mac Studio."""
    result = await make_api_request(
        method="POST",
        url=f"{MAC_STUDIO_URL}/ssh",
        headers={"Content-Type": "application/json"},
        json_data={"command": params.command, "host": params.host, "user": params.user},
        timeout=60.0
    )
    return json.dumps(result, indent=2)

class MacHealthInput(BaseModel):
    """Input for Mac Studio health check."""
    pass

@mcp.tool(
    name="mac_health",
    annotations={
        "title": "[MAC] Mac Studio Health Check",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def mac_health(params: MacHealthInput) -> str:
    """Check if Mac Studio is reachable."""
    result = await make_api_request(
        method="GET",
        url=f"{MAC_STUDIO_URL}/health",
        headers={},
        timeout=10.0
    )
    return json.dumps(result, indent=2)

# ============================================================================
# GOOGLE DRIVE TOOLS
# ============================================================================

# Google Drive backend URL
GOOGLE_DRIVE_MCP_URL = os.getenv("GOOGLE_DRIVE_MCP_URL", "https://google-drive-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io")

class DriveListSharedDrivesInput(BaseModel):
    """Input for listing shared drives."""
    pass

@mcp.tool(
    name="drive_list_shared_drives",
    annotations={
        "title": "[DRIVE] [DRIVE] List all Shared Drives accessible to the service account",
        "readOnlyHint": True
    }
)
async def drive_list_shared_drives(params: DriveListSharedDrivesInput) -> str:
    """List all Shared Drives accessible to the service account."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "list_shared_drives", "arguments": {}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveListFolderInput(BaseModel):
    """Input for listing folder contents."""
    folder_id: str = Field(..., description="Folder ID or Shared Drive ID")
    page_size: int = Field(default=50)

@mcp.tool(
    name="drive_list_folder_contents",
    annotations={
        "title": "[DRIVE] [DRIVE] List files in a folder (works with Shared Drives)",
        "readOnlyHint": True
    }
)
async def drive_list_folder_contents(params: DriveListFolderInput) -> str:
    """List files in a folder (works with Shared Drives)."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "list_folder_contents", "arguments": {"folder_id": params.folder_id, "page_size": params.page_size}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveSearchFilesInput(BaseModel):
    """Input for searching files."""
    query: str = Field(..., description="Search query")
    folder_id: Optional[str] = Field(default=None)
    file_type: Optional[str] = Field(default=None)

@mcp.tool(
    name="drive_search_files",
    annotations={
        "title": "[DRIVE] [DRIVE] Search files by name (includes Shared Drives)",
        "readOnlyHint": True
    }
)
async def drive_search_files(params: DriveSearchFilesInput) -> str:
    """Search files by name (includes Shared Drives)."""
    args = {"query": params.query}
    if params.folder_id:
        args["folder_id"] = params.folder_id
    if params.file_type:
        args["file_type"] = params.file_type
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "search_files", "arguments": args}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveGetFileMetadataInput(BaseModel):
    """Input for getting file metadata."""
    file_id: str

@mcp.tool(
    name="drive_get_file_metadata",
    annotations={
        "title": "[DRIVE] [DRIVE] Get file metadata",
        "readOnlyHint": True
    }
)
async def drive_get_file_metadata(params: DriveGetFileMetadataInput) -> str:
    """Get file metadata."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "get_file_metadata", "arguments": {"file_id": params.file_id}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveReadTextFileInput(BaseModel):
    """Input for reading text files."""
    file_id: str

@mcp.tool(
    name="drive_read_text_file",
    annotations={
        "title": "[DRIVE] [DRIVE] Read text files",
        "readOnlyHint": True
    }
)
async def drive_read_text_file(params: DriveReadTextFileInput) -> str:
    """Read text files."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "read_text_file", "arguments": {"file_id": params.file_id}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveReadExcelFileInput(BaseModel):
    """Input for reading Excel files."""
    file_id: str
    sheet_name: Optional[str] = Field(default=None)

@mcp.tool(
    name="drive_read_excel_file",
    annotations={
        "title": "[DRIVE] [DRIVE] Read Excel/Sheets",
        "readOnlyHint": True
    }
)
async def drive_read_excel_file(params: DriveReadExcelFileInput) -> str:
    """Read Excel/Sheets."""
    args = {"file_id": params.file_id}
    if params.sheet_name:
        args["sheet_name"] = params.sheet_name
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "read_excel_file", "arguments": args}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveReadPdfFileInput(BaseModel):
    """Input for reading PDF files."""
    file_id: str
    page_numbers: Optional[List[int]] = Field(default=None)

@mcp.tool(
    name="drive_read_pdf_file",
    annotations={
        "title": "[DRIVE] [DRIVE] Extract PDF text",
        "readOnlyHint": True
    }
)
async def drive_read_pdf_file(params: DriveReadPdfFileInput) -> str:
    """Extract PDF text."""
    args = {"file_id": params.file_id}
    if params.page_numbers:
        args["page_numbers"] = params.page_numbers
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "read_pdf_file", "arguments": args}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveReadWordFileInput(BaseModel):
    """Input for reading Word files."""
    file_id: str

@mcp.tool(
    name="drive_read_word_file",
    annotations={
        "title": "[DRIVE] [DRIVE] Extract Word text",
        "readOnlyHint": True
    }
)
async def drive_read_word_file(params: DriveReadWordFileInput) -> str:
    """Extract Word text."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "read_word_file", "arguments": {"file_id": params.file_id}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveReadPowerpointFileInput(BaseModel):
    """Input for reading PowerPoint files."""
    file_id: str

@mcp.tool(
    name="drive_read_powerpoint_file",
    annotations={
        "title": "[DRIVE] [DRIVE] Extract PowerPoint text",
        "readOnlyHint": True
    }
)
async def drive_read_powerpoint_file(params: DriveReadPowerpointFileInput) -> str:
    """Extract PowerPoint text."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "read_powerpoint_file", "arguments": {"file_id": params.file_id}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveCreateFolderInput(BaseModel):
    """Input for creating folders."""
    name: str = Field(..., description="Folder name")
    parent_folder_id: Optional[str] = Field(default=None, description="Parent folder ID")
    shared_drive_id: Optional[str] = Field(default=None, description="Shared Drive ID")

@mcp.tool(
    name="drive_create_folder",
    annotations={
        "title": "[DRIVE] Create a folder in Google Drive",
        "readOnlyHint": False
    }
)
async def drive_create_folder(params: DriveCreateFolderInput) -> str:
    """Create a folder in Google Drive."""
    args = {"name": params.name}
    if params.parent_folder_id:
        args["parent_folder_id"] = params.parent_folder_id
    if params.shared_drive_id:
        args["shared_drive_id"] = params.shared_drive_id
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "create_folder", "arguments": args}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveUploadFileInput(BaseModel):
    """Input for uploading files."""
    name: str = Field(..., description="File name")
    content_base64: str = Field(..., description="Base64-encoded file content")
    parent_folder_id: str = Field(..., description="Parent folder ID")
    mime_type: Optional[str] = Field(default=None, description="MIME type")

@mcp.tool(
    name="drive_upload_file",
    annotations={
        "title": "[DRIVE] Upload a file to Google Drive",
        "readOnlyHint": False
    }
)
async def drive_upload_file(params: DriveUploadFileInput) -> str:
    """Upload a file to Google Drive."""
    args = {
        "name": params.name,
        "content_base64": params.content_base64,
        "parent_folder_id": params.parent_folder_id
    }
    if params.mime_type:
        args["mime_type"] = params.mime_type
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "upload_file", "arguments": args}},
        timeout=120.0  # Longer timeout for uploads
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)

class DriveMoveFileInput(BaseModel):
    """Input for moving files."""
    file_id: str = Field(..., description="File ID to move")
    new_parent_id: str = Field(..., description="New parent folder ID")

@mcp.tool(
    name="drive_move_file",
    annotations={
        "title": "[DRIVE] Move a file to a different folder",
        "readOnlyHint": False
    }
)
async def drive_move_file(params: DriveMoveFileInput) -> str:
    """Move a file to a different folder."""
    result = await make_api_request(
        method="POST",
        url=f"{GOOGLE_DRIVE_MCP_URL}/mcp",
        headers={"Content-Type": "application/json"},
        json_data={"method": "tools/call", "params": {"name": "move_file", "arguments": {"file_id": params.file_id, "new_parent_id": params.new_parent_id}}}
    )
    if "result" in result:
        return json.dumps(result["result"], indent=2)
    return json.dumps(result, indent=2)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys
    
    # Support both stdio and HTTP transports
    transport = os.getenv("MCP_TRANSPORT", "streamable_http")
    port = int(os.getenv("PORT", "8000"))
    
    if transport == "stdio":
        mcp.run()
    else:
        # For HTTP transport, use uvicorn directly with the ASGI app
        app = mcp.get_app(transport="streamable-http")
        uvicorn.run(app, host="0.0.0.0", port=port)