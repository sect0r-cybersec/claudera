"""Build the claudera MCP server and its Streamable HTTP transport.

Wires the plugin tool registry into the MCP Python SDK's low-level ``Server`` and
wraps it in a ``StreamableHTTPSessionManager`` (single endpoint, POST for
requests, session tracked via the ``Mcp-Session-Id`` header). The manager is an
ASGI app; :mod:`asgi_bridge` mounts it onto Caldera's aiohttp router.

Handlers are registered through the SDK's ``on_*`` constructor parameters and
receive a ``ServerRequestContext`` per call. The transport-level Starlette
request hangs off ``ctx.request``, which is where the bearer identity is
resolved from.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import json
import logging

import mcp.types as types
from aiohttp import web
from jsonschema import Draft202012Validator
from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

from .asgi_bridge import serve_asgi
from .auth import resolve_identity
from .store import KeyStore
from .tools import ToolContext, build_registry

log = logging.getLogger("claudera")

MCP_SESSION_HEADER = "mcp-session-id"


def _tool_error(message: str) -> types.CallToolResult:
    """Return a failure the calling model can see and correct.

    The SDK's ``on_call_tool`` does not wrap handler exceptions: an exception
    becomes a top-level JSON-RPC error whose text the model never sees, so
    tool-level failures are returned as ``is_error=True`` results instead.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        is_error=True,
    )


class CalderaMCP:
    """Owns the MCP server, tool registry, key store, and transport."""

    def __init__(self, services: dict, config: dict | None = None, db_path: str | None = None,
                 plugin_dir: str | None = None):
        self.services = services
        # `config` is the full 'claudera' plugin config namespace.
        self.config = config or {}
        self.plugin_dir = plugin_dir
        self.keystore = KeyStore(db_path) if db_path else None
        self.registry = build_registry(services)
        # One compiled validator per tool. check_schema() runs at load time so a
        # malformed tool schema fails when the plugin starts rather than on the
        # first call that happens to exercise it.
        self._validators: dict[str, Draft202012Validator] = {}
        for spec in self.registry.specs():
            Draft202012Validator.check_schema(spec.input_schema)
            self._validators[spec.name] = Draft202012Validator(spec.input_schema)
        self.server: Server = Server(
            "claudera",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

        mcp_cfg = self.config.get("mcp") or {}
        sec_cfg = (mcp_cfg.get("security") or {})
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(
                sec_cfg.get("enable_dns_rebinding_protection", False)
            ),
            allowed_hosts=list(sec_cfg.get("allowed_hosts") or []),
            allowed_origins=list(sec_cfg.get("allowed_origins") or []),
        )
        self.manager = StreamableHTTPSessionManager(
            app=self.server,
            json_response=bool(mcp_cfg.get("json_response", True)),
            stateless=False,
            security_settings=security,
        )

    # -- MCP protocol handlers -------------------------------------------------

    async def _list_tools(self, ctx: ServerRequestContext,
                          params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                )
                for spec in self.registry.specs()
            ]
        )

    async def _call_tool(self, ctx: ServerRequestContext,
                         params: types.CallToolRequestParams) -> types.CallToolResult:
        name = params.name
        arguments = params.arguments or {}
        spec = self.registry.get(name)
        if spec is None:
            return _tool_error(f"unknown tool: {name}")

        tool_ctx = self._context_for_request(ctx)
        if self.keystore is not None and tool_ctx.username is None:
            # Defence in depth: handle_http already gated the request, but a
            # key could have been revoked mid-session. The model cannot correct
            # an authorisation failure, so reject the request at the protocol
            # level instead of returning it as a tool result.
            raise MCPError(
                types.INVALID_REQUEST,
                "unauthorized: no valid Caldera identity for this request",
            )

        invalid = self._validate(name, arguments)
        if invalid is not None:
            return _tool_error(invalid)

        try:
            result = await spec.handler(tool_ctx, arguments)
        except Exception as exc:  # noqa: BLE001 - surfaced to the model below
            log.warning("claudera tool %s failed: %s", name, exc)
            return _tool_error(f"{name} failed: {exc}")

        if spec.mutating and self.keystore is not None:
            self.keystore.log_event(
                session_id=tool_ctx.session_id, username=tool_ctx.username,
                tool=name, result=result if isinstance(result, dict) else None,
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, default=str))],
            is_error=False,
        )

    def _validate(self, name: str, arguments: dict) -> str | None:
        """Check *arguments* against the tool's declared JSON Schema.

        The SDK's low-level ``Server`` does not validate tool input against the
        declared schema, so claudera does it here: handlers index required keys
        directly and assume their declared types. Returns an error message, or
        ``None`` when the arguments are valid.
        """
        validator = self._validators.get(name)
        if validator is None:
            return None
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
        if not errors:
            return None
        first = errors[0]
        path = "/".join(str(part) for part in first.path)
        where = f" at {path}" if path else ""
        return f"invalid arguments for {name}{where}: {first.message}"

    def _context_for_request(self, ctx: ServerRequestContext) -> ToolContext:
        """Build the per-call context.

        Resolves the bearer identity from the Starlette request the MCP
        transport threads onto ``ctx``, so the user/group/session are available
        inside the tool handler. ``ctx.request`` is ``None`` on transports that
        carry no HTTP request (the in-memory client the offline protocol test
        uses), in which case the identity stays unresolved.
        """
        username = group = session_id = None
        request = getattr(ctx, "request", None)
        if self.keystore is not None and request is not None:
            identity = resolve_identity(self.keystore, request.headers)
            if identity is not None:
                username, group = identity.username, identity.group
            session_id = request.headers.get(MCP_SESSION_HEADER)
        return ToolContext(
            services=self.services,
            username=username,
            group=group,
            session_id=session_id,
            config=self.config,
            plugin_dir=self.plugin_dir,
            store=self.keystore,
        )

    # -- aiohttp integration ---------------------------------------------------

    async def handle_http(self, request: web.Request) -> web.StreamResponse:
        # Authenticate every MCP request at the transport edge. A bad or missing
        # key is rejected before any MCP session is created.
        if self.keystore is not None:
            identity = resolve_identity(self.keystore, request.headers)
            if identity is None:
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32001, "message": "Unauthorized: invalid or missing bearer key"},
                    },
                    status=401,
                    headers={"WWW-Authenticate": 'Bearer realm="caldera-mcp"'},
                )
        return await serve_asgi(request, self.manager.handle_request)

    async def lifespan(self, app: web.Application):
        """aiohttp cleanup_ctx entry that runs the session manager task group.

        This is a plain async generator (not an ``asynccontextmanager``): aiohttp
        drives it via ``__anext__`` for startup, then again for teardown.
        """
        async with self.manager.run():
            log.info("claudera MCP session manager started")
            yield
            log.info("claudera MCP session manager stopping")
