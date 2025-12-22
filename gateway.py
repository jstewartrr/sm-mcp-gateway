"""
Sovereign Mind MCP Gateway
==========================
Unified MCP server that aggregates tools from multiple backend services.
Provides single connection point for Claude.ai, ElevenLabs ABBI, and future agents.

Architecture:
- Central gateway exposes namespaced tools (e.g., snowflake_query, asana_create_task)
- Routes requests to appropriate backend MCP servers or APIs
- Handles authentication centrally via environment variables
- Supports both standard HTTP and SSE transports for different clients
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
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
    
    # Asana
    ASANA_ACCESS_TOKEN = os.getenv("ASANA_ACCESS_TOKEN", "")
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
    name="snowflake_query",
    annotations={
        "title": "Execute Snowflake Query",
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
    
    Args:
        params: Query parameters including SQL and optional database override
        
    Returns:
        JSON string with query results or error message
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
            "columns": columns,
            "data": results
        }, indent=2, default=str)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })

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
    """Get tasks from Asana for the specified user or project.
    
    Returns a list of tasks with their names, due dates, and status.
    
    Args:
        params: Filter parameters for task retrieval
        
    Returns:
        JSON string with task list
    """
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
    """Create a new task in Asana.
    
    Args:
        params: Task details including name, notes, due date
        
    Returns:
        JSON string with created task details
    """
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
    """Search for tasks in Asana by text.
    
    Args:
        params: Search parameters
        
    Returns:
        JSON string with matching tasks
    """
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
    """Mark an Asana task as complete.
    
    Args:
        params: Task ID to complete
        
    Returns:
        JSON string with updated task
    """
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
    """List all projects in the Asana workspace.
    
    Args:
        params: Filter parameters
        
    Returns:
        JSON string with project list
    """
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
    """List all scenarios in the Make.com team.
    
    Returns:
        JSON string with scenario list including IDs and names
    """
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
    """Execute a Make.com scenario.
    
    Args:
        params: Scenario ID and optional input data
        
    Returns:
        JSON string with execution result
    """
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
    """Get details of a specific Make.com scenario.
    
    Args:
        params: Scenario ID
        
    Returns:
        JSON string with scenario details
    """
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
    """List GitHub repositories for the authenticated user.
    
    Returns:
        JSON string with repository list
    """
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
        return json.dumps({"repos": simplified}, indent=2)
    
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
    """Get contents of a file from a GitHub repository.
    
    Args:
        params: Repository and file path details
        
    Returns:
        JSON string with file content (base64 decoded if text)
    """
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
    """List all conversational AI agents in ElevenLabs.
    
    Returns:
        JSON string with agent list
    """
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
    """Get details of a specific ElevenLabs agent.
    
    Args:
        params: Agent ID
        
    Returns:
        JSON string with agent configuration
    """
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
    """Write an entry to the Sovereign Mind Hive Mind shared memory.
    
    This allows AI instances to share context with each other.
    
    Args:
        params: Memory entry details
        
    Returns:
        Confirmation of write operation
    """
    sql = f"""
    INSERT INTO SOVEREIGN_MIND.RAW.SHARED_MEMORY 
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
    """Read recent entries from the Sovereign Mind Hive Mind.
    
    Returns shared memory entries from all AI instances.
    
    Args:
        params: Filter and limit parameters
        
    Returns:
        JSON string with memory entries
    """
    where_clauses = ["STATUS = 'ACTIVE'"]
    if params.source:
        where_clauses.append(f"SOURCE = '{params.source}'")
    if params.category:
        where_clauses.append(f"CATEGORY = '{params.category}'")
    
    where_sql = " AND ".join(where_clauses)
    
    sql = f"""
    SELECT SOURCE, CATEGORY, WORKSTREAM, SUMMARY, PRIORITY, CREATED_AT
    FROM SOVEREIGN_MIND.RAW.SHARED_MEMORY
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
    """Get the status of the Sovereign Mind MCP Gateway.
    
    Returns information about available services and their configuration status.
    
    Returns:
        JSON string with gateway status
    """
    status = {
        "gateway": "sovereign_mind_gateway",
        "version": "1.0.0",
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
            }
        },
        "tools": [
            "snowflake_query",
            "asana_get_tasks", "asana_create_task", "asana_search_tasks",
            "asana_complete_task", "asana_get_projects",
            "make_list_scenarios", "make_run_scenario", "make_get_scenario",
            "github_list_repos", "github_get_file",
            "elevenlabs_list_agents", "elevenlabs_get_agent",
            "hivemind_write", "hivemind_read",
            "gateway_status"
        ]
    }
    
    return json.dumps(status, indent=2)

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
        mcp.run(transport="streamable_http", port=port)
