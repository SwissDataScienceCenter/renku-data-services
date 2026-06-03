# Renku MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server for the Renku data
science platform. Exposes Renku projects, sessions, data connectors, and compute resources as
typed tools that AI agents can call.

## Tools

| Category | Tools |
|---|---|
| Auth / platform | `auth_status`, `resource_classes`, `namespaces`, `global_environments` |
| Projects | `project_list`, `project_get`, `project_create`, `project_delete`, `project_update`, `project_repo_add`, `project_get_documentation` |
| Data connectors | `connector_list`, `connector_get`, `connector_create`, `connector_link`, `connector_patch`, `connector_unlink`, `connector_delete`, `renku_connector_project_links`, `renku_project_data_connector_links` |
| Session launchers | `launcher_list`, `launcher_project_list`, `launcher_get`, `launcher_create`, `launcher_patch`, `launcher_delete` |
| Sessions | `session_launch`, `session_list`, `session_get`, `session_logs`, `session_delete`, `session_delete_if_failed`, `session_wait` |
| Jobs | `job_run`, `job_list`, `job_wait` |
| Builds | `build_list`, `build_get`, `build_logs`, `build_wait` |
| Groups | `renku_group_members` |

## Connecting to a deployed instance

### Claude Code

```bash
claude mcp add --transport http \
  --client-id renku-mcp \
  --callback-port 8484 \
  renku https://<deployment>/mcp
```

### pi

Add to your `.pi/mcp.json`:

```json
{
  "mcpServers": {
    "renku": {
      "type": "http",
      "url": "https://<deployment>/mcp",
      "oauth": {
        "clientId": "renku-mcp",
        "redirectUri": "http://localhost:8484"
      }
    }
  }
}
```

Both clients will open a browser to complete the Keycloak login on first connect.

## Running locally (stdio mode)

Useful for development or pointing at a remote deployment without managing tokens manually.

```bash
# Authenticate once
rnk login

# Install dependencies
cd projects/renku_mcp_server
poetry install

# Run against renkulab.io (default)
poetry run renku-mcp

# Run against a different deployment
RENKU_BASE_URL=https://dev.renku.ch poetry run renku-mcp
```

Then configure Claude Code to use it:

```json
{
  "renku": {
    "command": "poetry",
    "args": ["run", "renku-mcp"],
    "cwd": "/path/to/projects/renku_mcp_server",
    "env": {
      "RENKU_BASE_URL": "https://<deployment>"
    }
  }
}
```

The server discovers your token automatically from the `rnk` CLI token file — no `RENKU_ACCESS_TOKEN`
needed after `rnk login`.

## Development / testing

Use the MCP Inspector:

```bash
RENKU_BASE_URL=https://<deployment> poetry run mcp dev bases/renku_data_services/mcp_api/main.py
```

Run the unit tests (no external services required):

```bash
poetry run pytest test/bases/renku_data_services/mcp_api/
```

## Safety rules (enforced in code)

- **Admin accounts are blocked.** The server calls `GET /user` on startup and refuses all tool
  calls if `is_admin=true`. Set `RENKU_MCP_ALLOW_ADMIN=1` to override.
- **Credentials are never accepted as tool parameters.** Storage credentials (S3 keys,
  passwords) must be added through the Renku UI after creating a connector.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RENKU_BASE_URL` | `https://renkulab.io` | Target Renku deployment |
| `KEYCLOAK_ISSUER_URL` | — | Keycloak realm URL (set by Helm chart in HTTP mode) |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_HOST` | `0.0.0.0` | Bind host (HTTP mode) |
| `MCP_PORT` | `9000` | Bind port (HTTP mode) |
| `RENKU_ACCESS_TOKEN` | — | Bearer token (stdio mode; auto-discovered if unset) |
| `RENKU_MCP_ALLOW_ADMIN` | — | Set to `1` to allow admin accounts |
