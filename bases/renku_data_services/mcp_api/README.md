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

In HTTP mode the server verifies the Bearer token before doing anything with it:
signature against the Keycloak realm's JWKS, issuer, expiry, and that `renku-mcp` is
among the token's audiences. The MCP specification requires a server to establish that
a token was issued *for it* — without the audience check, a token minted for the Renku
UI or CLI would be accepted here and grant the full tool surface.

This requires an **audience mapper on the `renku-mcp` Keycloak client** that adds
`renku-mcp` to the access token. The mapper must *add* to the audiences already there,
not replace them: the same token is forwarded to the Renku data API, which requires one
of `renku`, `renku-ui`, `renku-cli`, `swagger`. A correctly configured access token
therefore carries both:

```json
"aud": ["renku", "renku-mcp"]
```

Deploy the mapper before deploying a server that checks for it, or every tool call will
be rejected with a 401.

Beyond that check the token is forwarded unchanged with every call to the data API,
which validates it again and enforces all permissions. The MCP server grants nothing the
user does not already have. Forwarding the caller's token rather than exchanging it is a
deliberate choice — the specification would prefer a token exchange, which would also let
the data API tell agent-initiated calls apart from the user's own; that is not
implemented.

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
- **Credentials are refused, not ignored.** `connector_create` and `connector_patch` reject
  any payload carrying a field rclone marks sensitive, before the request is made. The data
  API would replace such values with a `<sensitive>` placeholder anyway, but by then the
  secret has already passed through the agent's context and the logs in between. The field
  list is copied from `rclone_schema.autogenerated.json`; a test fails if the schema gains a
  sensitive option the list does not cover, so it cannot drift silently.
- **Destructive operations ask the user.** Deleting a project, connector, launcher, session
  or app goes through MCP elicitation, so the client prompts the user and the agent cannot
  proceed on its own. Clients that do not support elicitation are refused and told to
  confirm with the user and retry with `confirm=true` — weaker, since an agent can assert
  it, but deliberate and visible in the call. `session_delete_if_failed` is exempt: a
  terminal session has nothing left to lose.
- **Unlinked connectors are confirmed, not blocked.** `connector_create` without a
  `project_id` asks first, since a connector that belongs to no project is unusual but
  legitimate.
- **Apps stay the user's decision.** An app is public by definition: it needs a public
  project, and the data API refuses an `app` launcher in a private one. The tools surface
  that refusal rather than working around it — nothing changes a project's visibility on
  the user's behalf. Only public, credential-free data connectors are mounted into an app.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RENKU_BASE_URL` | `https://renkulab.io` | Target Renku deployment |
| `KEYCLOAK_ISSUER_URL` | — | Keycloak realm URL; required in HTTP mode, since tokens are verified against its JWKS |
| `RENKU_MCP_AUDIENCE` | `renku-mcp` | Audience an access token must carry to be accepted |
| `RENKU_MCP_ALLOW_UNVERIFIED_TOKENS` | — | Set to `1` to run HTTP mode without `KEYCLOAK_ISSUER_URL`, forwarding tokens unverified (local development only) |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_HOST` | `0.0.0.0` | Bind host (HTTP mode) |
| `MCP_PORT` | `9000` | Bind port (HTTP mode) |
| `RENKU_ACCESS_TOKEN` | — | Bearer token, required in stdio mode (`RENKU_TOKEN` and `RENKU_CLI_ACCESS_TOKEN` also accepted) |
| `RENKU_MCP_ALLOW_ADMIN` | — | Set to `1` to allow admin accounts |
