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
| Apps | `app_launch`, `app_list`, `app_get`, `app_logs`, `app_delete`, `app_wait` |
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

Useful for development, or for pointing at a deployment that has no MCP server of its own.

In stdio mode the token comes from the environment — there is no OAuth flow and no token
file. This follows the MCP specification, which says stdio implementations "SHOULD NOT"
run the authorization flow and should "retrieve credentials from the environment" instead.

```bash
# Install dependencies
cd projects/renku_mcp_server
poetry install

# Run against renkulab.io (default)
RENKU_ACCESS_TOKEN=<token> poetry run python -m renku_data_services.mcp_api.main

# Run against a different deployment
RENKU_BASE_URL=https://dev.renku.ch RENKU_ACCESS_TOKEN=<token> \
  poetry run python -m renku_data_services.mcp_api.main
```

Then configure Claude Code to use it:

```json
{
  "renku": {
    "command": "poetry",
    "args": ["run", "python", "-m", "renku_data_services.mcp_api.main"],
    "cwd": "/path/to/projects/renku_mcp_server",
    "env": {
      "RENKU_BASE_URL": "https://<deployment>",
      "RENKU_ACCESS_TOKEN": "<token>"
    }
  }
}
```

`RENKU_TOKEN` and `RENKU_CLI_ACCESS_TOKEN` are accepted as alternatives. The token is read
from the process environment, so a token that expires or changes needs the server restarted.
For everyday use prefer the deployed server over stdio mode: it handles login through OAuth
and refreshes without any of this.

## Development / testing

Use the MCP Inspector:

```bash
RENKU_BASE_URL=https://<deployment> poetry run mcp dev bases/renku_data_services/mcp_api/main.py
```

Run the unit tests (no external services required):

```bash
poetry run pytest test/bases/renku_data_services/mcp_api/
```

## Token handling

The MCP server does not validate tokens. It extracts the Bearer token from the
`Authorization` header and forwards it with every call to the Renku data API. The
data API is responsible for validating the token and enforcing permissions — if the
token is missing or invalid, the data API rejects the request and the tool returns an
error.

In HTTP mode, unauthenticated requests to `/mcp` receive a `401` response with a
`WWW-Authenticate` header pointing at the OAuth discovery endpoints. This is the
signal MCP clients use to trigger the OAuth flow; the flow itself happens entirely
between the client and Keycloak.

In stdio mode there is no OAuth flow: the token is read from the environment at startup.
The server reads no token files and no OS keyring, so nothing of the user's credentials is
touched beyond the variable they set for this process.

## Safety rules (enforced in code)

- **Admin accounts are blocked.** The server calls `GET /user` on each tool invocation
  and refuses if `is_admin=true`. The check runs once per tool call — repeated within
  a tool that polls (`session_wait`, `job_wait`, `build_wait`, `app_wait`) it would double that
  tool's request volume, and cached beyond the tool call it would both hold live
  tokens in memory and go stale. Set `RENKU_MCP_ALLOW_ADMIN=1` to override.
- **Credentials are never accepted as tool parameters.** Storage credentials (S3 keys,
  passwords) must be added through the Renku UI after creating a connector.
- **Apps stay the user's decision.** An app is public by definition: it needs a public
  project, and the data API refuses an `app` launcher in a private one. The tools surface
  that refusal rather than working around it — nothing changes a project's visibility on
  the user's behalf. Only public, credential-free data connectors are mounted into an app.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RENKU_BASE_URL` | `https://renkulab.io` | Target Renku deployment |
| `KEYCLOAK_ISSUER_URL` | — | Keycloak realm URL (set by Helm chart in HTTP mode) |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_HOST` | `0.0.0.0` | Bind host (HTTP mode) |
| `MCP_PORT` | `9000` | Bind port (HTTP mode) |
| `RENKU_ACCESS_TOKEN` | — | Bearer token, required in stdio mode (`RENKU_TOKEN` and `RENKU_CLI_ACCESS_TOKEN` also accepted) |
| `RENKU_MCP_ALLOW_ADMIN` | — | Set to `1` to allow admin accounts |
