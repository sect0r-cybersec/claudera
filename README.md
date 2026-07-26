<div align="center">

![Licence](https://img.shields.io/github/license/sect0r-cybersec/claudera)
![Language](https://img.shields.io/github/languages/top/sect0r-cybersec/claudera)
![Status](https://img.shields.io/badge/status-beta%20(lab--only)-orange)
![Last commit](https://img.shields.io/github/last-commit/sect0r-cybersec/claudera)

# claudera

**Drive MITRE Caldera from Claude, over your LAN, with no model API key inside Caldera.**

</div>

`claudera` turns [MITRE Caldera](https://github.com/mitre/caldera) v5 into an authenticated remote [Model Context Protocol](https://modelcontextprotocol.io) server. An external Claude client (Claude Code or Claude Desktop) connects across the LAN, Caldera exposes the tools, and Claude is the client. The intelligence lives in your Claude subscription, so no model API key is ever stored in Caldera.

This is the inverse of Caldera's bundled `mcp` plugin, which embeds an LLM inside Caldera. `claudera` is a fresh build; only small, clearly marked pieces are vendored from Caldera under Apache-2.0 (see [`NOTICE.md`](NOTICE.md)).

> **Beta, lab-only.** Built and verified against a live Caldera 5.3.0 lab. Do not expose the MCP endpoint to untrusted networks.

<div align="center">

![claudera CLI issuing an MCP bearer key and a Claude client connecting](docs/mockup.png)

</div>

## Features

- **Runs inside Caldera.** The MCP server mounts as a route on Caldera's own aiohttp app: no second web server, no extra port, and only the MCP Python SDK on top of Caldera's runtime.
- **Authenticated by default.** Every request carries `Authorization: Bearer <key>`. A bad or missing key is rejected with HTTP 401 before any session starts.
- **Per-user keys, scoped to real groups.** Keys map to a Caldera username and group taken from Caldera's own config, so a key can only act as a real user. Tokens are stored hashed (argon2); the raw token is shown once.
- **20 structured tools.** Create abilities, adversaries and operations, drive the full operation lifecycle, read results back, and emit SIEM correlation keys. Every tool returns JSON, never free prose.
- **Deterministic, ATT&CK-aligned naming.** Artefacts get names like `T1059.001_desc` and persist to disk exactly like ones made in the Caldera UI.
- **Safe payload handling.** Downloads are limited to a trusted allow-list (Atomic Red Team and the MITRE stockpile by default), verified by sha256, never executed, and never placed on an agent.
- **GUI panel and run history.** A magma Vue panel shows runs, events and downloads, and manages keys. Every mutating call is attributed to a user and logged.

## Tools

| Group | Tools |
|-------|-------|
| Connectivity | `server_info`, `ping` |
| Read agents | `list_agents` |
| Creation | `create_ability`, `create_adversary`, `create_operation` |
| Execution control | `start_operation`, `pause_operation`, `resume_operation`, `stop_operation`, `get_operation_status` |
| Read-back | `get_operation_report`, `query_facts`, `list_abilities`, `list_adversaries`, `list_operations` |
| Correlation | `get_correlation_keys` |
| Payloads | `find_payload`, `download_payload` |
| Run history | `get_run_history` |

## Quick start

1. Install the MCP Python SDK into Caldera's environment:
   ```bash
   pip install "mcp>=1.28.0"
   ```
2. Drop this plugin into Caldera's `plugins/claudera` directory and add `claudera` to the `plugins:` list in your Caldera config (`conf/local.yml` or `conf/default.yml`).
3. Build the magma GUI so the **claudera** panel appears in the nav (once, and after any change to `gui/`):
   ```bash
   cd plugins/magma && npm run build
   ```
4. Restart Caldera and confirm the plugin loaded:
   ```bash
   sudo systemctl stop caldera && sudo systemctl start caldera
   journalctl -u caldera -e
   ```

## Usage

Issue a per-user key from the Caldera root (the group is resolved from Caldera's config), then point a Claude client at the endpoint.

```bash
# Issue a key for a user
python -m plugins.claudera.app.cli issue --user red

# List, rotate, revoke, or re-activate
python -m plugins.claudera.app.cli list
python -m plugins.claudera.app.cli rotate   --key-id <id>
python -m plugins.claudera.app.cli revoke   --key-id <id>
python -m plugins.claudera.app.cli activate --key-id <id>
```

The token format is `cald_<key_id>.<secret>` and is shown only once at issue time. Keys can also be issued, rotated and revoked from the **claudera** GUI panel.

**Claude Code:**
```bash
claude mcp add --transport http caldera http://<caldera-host>:<port>/mcp \
  --header "Authorization: Bearer $CALDERA_MCP_KEY"
```

`.mcp.json` or `~/.claude.json`. The `"type": "http"` field is required (a `url` with no `type` is read as stdio and fails):
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

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`), native streamable HTTP where supported, else the `mcp-remote` bridge:
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

Set in `conf/default.yml`:

- `mcp.path` sets the endpoint path (default `/mcp`).
- `mcp.json_response` returns single JSON bodies for POST (default `true`).
- `mcp.security` controls DNS-rebinding and Host-header protection. Off by default for LAN use; set `enable_dns_rebinding_protection: true` and populate `allowed_hosts` / `allowed_origins` to harden.
- `payloads.allow_list` is the trusted set of remote sources (host plus `path_prefix`). An off-list URL needs `confirm=true`. Defaults: Atomic Red Team and the MITRE stockpile.
- `payloads.download_dir` is where fetched payloads land (default `payloads/downloaded`, gitignored). `payloads.max_download_bytes` caps size (default 50 MiB).
- `gui.admin_users` lists Caldera users who may manage anyone's keys from the GUI (default: none; users manage their own).

## Security notes

- Lab-only, no public exposure. TLS is optional on the LAN; put it behind Caldera's own TLS (the `ssl` plugin) if enabled.
- Keys are hashed at rest (argon2, per-key salt); the raw token is shown once at issue.
- Tool arguments and any fetched payload content are treated as untrusted data, never as instructions, and never drive control flow.
- The payload allow-list, with confirm-on-off-list, is the hard boundary on fetching. Downloads are never executed and never placed on an agent.

## Support

Questions and bug reports go to [GitHub Issues](https://github.com/sect0r-cybersec/claudera/issues).

## Contributors and developers

### Architecture

- The MCP server uses the official Python MCP SDK (`mcp`), with the low-level `Server` plus `StreamableHTTPSessionManager`: a single endpoint, `POST` for requests, session tracked via the `Mcp-Session-Id` header. The SSE-deprecated transport is not used.
- The session manager is an ASGI app. A small adapter (`app/asgi_bridge.py`) drives it from an aiohttp request handler, so the endpoint shares Caldera's process, event loop and listening port. The route is registered in `hook.py`.
- Creation and execution reuse Caldera's own v2 API managers and rest service, so artefacts persist to disk like UI-made ones. Operations are created paused; `run()` is scheduled lazily on first start.
- `get_correlation_keys` emits, per executed ability, `{resolved_command, utc_start, utc_stop, technique_id, telemetry_hostname}`, the join key for a separate SIEM connector. This plugin does not query any SIEM.

### Layout

```
app/         MCP server, auth, key store, naming, payloads, CLI
app/tools/   the 20 tool implementations, grouped by concern
gui/views/   the magma Vue panel (claudera.vue)
conf/        default configuration
tests/       stdlib unittest suite
```

### Tests

A stdlib `unittest` suite with no extra dependencies. Run from the Caldera root with the Caldera venv:

```bash
python -m unittest discover -s plugins/claudera/tests -t .
```

It covers the naming helper, the key store and auth resolution (valid, invalid, revoked, rotated), the run-history and download logs, and payload allow-list classification and hash verification (including a deliberate mismatch). An optional live integration test runs against a running endpoint when `CLAUDERA_MCP_URL` and `CLAUDERA_MCP_KEY` are set:

```bash
CLAUDERA_MCP_URL=http://<host>:8888/mcp CLAUDERA_MCP_KEY=cald_... \
  python -m unittest plugins.claudera.tests.test_live_integration
```

## Licence

Apache-2.0 (see [`LICENSE`](LICENSE)). Vendored Caldera components keep their original Apache headers; see [`NOTICE.md`](NOTICE.md).
