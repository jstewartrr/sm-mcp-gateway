# Sovereign Mind MCP Gateway

Unified MCP (Model Context Protocol) server that aggregates tools from multiple backend services into a single connection point.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLIENT APPLICATIONS                          │
│         (Claude.ai, ElevenLabs ABBI, Future Agents)             │
└─────────────────────────┬───────────────────────────────────────┘
                          │ Single Connection
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                  SOVEREIGN MIND MCP GATEWAY                      │
│                                                                  │
│  Unified Tool Catalog:                                          │
│  • snowflake_query                                              │
│  • asana_get_tasks, asana_create_task, asana_search_tasks, ...  │
│  • make_list_scenarios, make_run_scenario, ...                  │
│  • github_list_repos, github_get_file, ...                      │
│  • elevenlabs_list_agents, elevenlabs_get_agent, ...            │
│  • hivemind_write, hivemind_read                                │
│  • gateway_status                                               │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Single Connection Point**: All tools accessible through one MCP URL
- **Namespaced Tools**: Clear prefixes prevent conflicts (e.g., `asana_`, `github_`)
- **Dual Transport Support**: 
  - Streamable HTTP for Claude.ai
  - SSE for ElevenLabs/ABBI
- **Centralized Auth**: All credentials managed via environment variables
- **Hive Mind Integration**: Built-in tools for Sovereign Mind shared memory

## Available Tools

### Snowflake
| Tool | Description |
|------|-------------|
| `snowflake_query` | Execute SQL queries against Snowflake |

### Asana
| Tool | Description |
|------|-------------|
| `asana_get_tasks` | Get tasks for user or project |
| `asana_create_task` | Create a new task |
| `asana_search_tasks` | Search tasks by text |
| `asana_complete_task` | Mark task as complete |
| `asana_get_projects` | List workspace projects |

### Make.com
| Tool | Description |
|------|-------------|
| `make_list_scenarios` | List all scenarios |
| `make_run_scenario` | Execute a scenario |
| `make_get_scenario` | Get scenario details |

### GitHub
| Tool | Description |
|------|-------------|
| `github_list_repos` | List user repositories |
| `github_get_file` | Get file contents |

### ElevenLabs
| Tool | Description |
|------|-------------|
| `elevenlabs_list_agents` | List conversational AI agents |
| `elevenlabs_get_agent` | Get agent configuration |

### Hive Mind (Sovereign Mind)
| Tool | Description |
|------|-------------|
| `hivemind_write` | Write to shared memory |
| `hivemind_read` | Read from shared memory |

### Gateway
| Tool | Description |
|------|-------------|
| `gateway_status` | Check gateway health and config |

## Deployment

### Build and Push to ACR
```bash
az acr build --registry sovereignmindacr --image sm-mcp-gateway:v1 --image sm-mcp-gateway:latest .
```

### Deploy Container App (HTTP Transport - Claude.ai)
```bash
az containerapp create \
  --name sm-mcp-gateway \
  --resource-group SovereignMind-RG \
  --image sovereignmindacr.azurecr.io/sm-mcp-gateway:latest \
  --registry-server sovereignmindacr.azurecr.io \
  --target-port 8000 \
  --ingress external
```

### Deploy Container App (SSE Transport - ElevenLabs)
```bash
az containerapp create \
  --name sm-mcp-gateway-sse \
  --resource-group SovereignMind-RG \
  --image sovereignmindacr.azurecr.io/sm-mcp-gateway:latest \
  --registry-server sovereignmindacr.azurecr.io \
  --target-port 8000 \
  --ingress external \
  --command "python" "gateway_sse.py"
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SNOWFLAKE_ACCOUNT` | Yes | Snowflake account identifier |
| `SNOWFLAKE_USER` | Yes | Snowflake username |
| `SNOWFLAKE_PASSWORD` | Yes | Snowflake password |
| `SNOWFLAKE_WAREHOUSE` | Yes | Snowflake warehouse |
| `SNOWFLAKE_DATABASE` | Yes | Default database |
| `SNOWFLAKE_ROLE` | No | Snowflake role (default: ACCOUNTADMIN) |
| `ASANA_ACCESS_TOKEN` | Yes | Asana personal access token |
| `ASANA_WORKSPACE_ID` | Yes | Asana workspace GID |
| `MAKE_API_KEY` | Yes | Make.com API key |
| `MAKE_TEAM_ID` | Yes | Make.com team ID |
| `GITHUB_TOKEN` | Yes | GitHub personal access token |
| `ELEVENLABS_API_KEY` | Yes | ElevenLabs API key |

## Endpoints

| Transport | Endpoint | Client |
|-----------|----------|--------|
| Streamable HTTP | `https://{fqdn}/mcp` | Claude.ai |
| SSE | `https://{fqdn}/sse` | ElevenLabs |
| Health | `https://{fqdn}/health` | Monitoring |

## Version History

- **v1.0.0**: Initial release with Snowflake, Asana, Make.com, GitHub, ElevenLabs, Hive Mind

---

*Part of the Sovereign Mind AI Second Brain System*
