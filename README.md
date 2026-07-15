# claudera

An **authenticated remote MCP server** plugin for [MITRE Caldera](https://github.com/mitre/caldera) v5 (targets 5.3.0).

`claudera` turns Caldera into a remote [Model Context Protocol](https://modelcontextprotocol.io) server that an **external Claude client** (Claude Code / Claude Desktop) drives over the LAN. Caldera exposes tools; Claude is the client. No model API key lives in Caldera — the intelligence sits in your Claude subscription.

This is the **inverse** of the bundled `mcp` plugin (which embeds an LLM inside Caldera). It is a fresh build; only small, clearly-marked pieces are vendored from Caldera under Apache-2.0 (see `NOTICE.md`).

> **Lab-only.** This plugin is intended for an isolated lab. Do not expose the MCP endpoint to untrusted networks.

## Status

Build in progress. Implemented so far:

- **Step 1 — skeleton.** MCP server mounted as a route on Caldera's own aiohttp app (no second web server, no extra dependency beyond the MCP Python SDK). Answers `initialize`, `tools/list`, and `tools/call` over Streamable HTTP. Ships two connectivity tools (`server_info`, `ping`). No auth yet.

## Architecture

- The MCP server is built with the official Python MCP SDK (`mcp`), using the low-level `Server` plus `StreamableHTTPSessionManager` (single endpoint, `POST` for requests, session tracked via the `Mcp-Session-Id` header; SSE-deprecated transport is not used).
- The session manager is an ASGI app. A small adapter (`app/asgi_bridge.py`) drives it from an aiohttp request handler, so the endpoint shares Caldera's process, event loop, and listening port. The route is registered in `hook.py:enable()`.
- Endpoint: `http://<caldera-host>:<caldera-port><mcp.path>` (default path `/mcp`).

## Enabling

1. Ensure the MCP Python SDK is present in Caldera's environment (`pip install "mcp>=1.28.0"` — already present in this lab venv).
2. Add `claudera` to the enabled plugins in your Caldera config (`plugins:` list in `conf/local.yml` / `conf/default.yml`).
3. Restart Caldera. On this lab box it runs as a systemd service:
   ```
   sudo systemctl stop caldera && sudo systemctl start caldera
   systemctl status caldera        # confirm it came back up
   journalctl -u caldera -e        # check the plugin loaded
   ```

## Client configuration

_Bearer auth lands in step 2; these configs are the target shape._

**Claude Code:**
```
claude mcp add --transport http caldera http://<caldera-host>:<port>/mcp \
  --header "Authorization: Bearer $CALDERA_MCP_KEY"
```

`.mcp.json` / `~/.claude.json` — note `"type": "http"` is required (a `url` with no `type` is read as stdio and fails):
```json
{
  "mcpServers": {
    "caldera": {
      "type": "http",
      "url": "http://<caldera-host>:<port>/mcp",
      "headers": { "Authorization": "Bearer ${CALDERA_MCP_KEY}" }
    }
  }
}
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`) — native streamable HTTP where supported, else the `mcp-remote` bridge:
```json
{
  "mcpServers": {
    "caldera": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://<caldera-host>:<port>/mcp",
               "--header", "Authorization: Bearer ${CALDERA_MCP_KEY}"]
    }
  }
}
```

## Configuration

`conf/default.yml`:

- `mcp.path` — endpoint path (default `/mcp`).
- `mcp.json_response` — return single JSON bodies for POST (default `true`).
- `mcp.security` — MCP DNS-rebinding / Host-header protection. Off by default for LAN use; set `enable_dns_rebinding_protection: true` and populate `allowed_hosts` / `allowed_origins` to harden.

## Licence

Apache-2.0 (`LICENSE`). Vendored Caldera components keep their original Apache headers; see `NOTICE.md`.
