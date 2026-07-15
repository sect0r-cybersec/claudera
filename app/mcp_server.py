"""Build the claudera MCP server and its Streamable HTTP transport.

Wires the plugin tool registry into the MCP Python SDK's low-level ``Server`` and
wraps it in a ``StreamableHTTPSessionManager`` (single endpoint, POST for
requests, session tracked via the ``Mcp-Session-Id`` header). The manager is an
ASGI app; :mod:`asgi_bridge` mounts it onto Caldera's aiohttp router.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import json
import logging

import mcp.types as types
from aiohttp import web
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

from .asgi_bridge import serve_asgi
from .auth import resolve_identity
from .store import KeyStore
from .tools import ToolContext, build_registry

log = logging.getLogger("claudera")

MCP_SESSION_HEADER = "mcp-session-id"


class CalderaMCP:
    """Owns the MCP server, tool registry, key store, and transport."""

    def __init__(self, services: dict, config: dict | None = None, db_path: str | None = None):
        self.services = services
        self.config = config or {}
        self.keystore = KeyStore(db_path) if db_path else None
        self.registry = build_registry(services)
        self.server: Server = Server("claudera")
        self._register_handlers()

        sec_cfg = (self.config.get("security") or {})
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(
                sec_cfg.get("enable_dns_rebinding_protection", False)
            ),
            allowed_hosts=list(sec_cfg.get("allowed_hosts") or []),
            allowed_origins=list(sec_cfg.get("allowed_origins") or []),
        )
        self.manager = StreamableHTTPSessionManager(
            app=self.server,
            json_response=bool(self.config.get("json_response", True)),
            stateless=False,
            security_settings=security,
        )

    # -- MCP protocol handlers -------------------------------------------------

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def _list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=spec.input_schema,
                )
                for spec in self.registry.specs()
            ]

        @self.server.call_tool()
        async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
            spec = self.registry.get(name)
            if spec is None:
                raise ValueError(f"unknown tool: {name}")
            ctx = self._context_for_request()
            if self.keystore is not None and ctx.username is None:
                # Defence in depth: handle_http already gated the request, but a
                # key could have been revoked mid-session.
                raise ValueError("unauthorized: no valid Caldera identity for this request")
            result = await spec.handler(ctx, arguments or {})
            return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    def _context_for_request(self) -> ToolContext:
        """Build the per-call context.

        Resolves the bearer identity from the Starlette request the MCP transport
        threads into ``request_context`` for the current JSON-RPC message, so the
        user/group/session are available inside the tool handler.
        """
        username = group = session_id = None
        if self.keystore is not None:
            try:
                req = self.server.request_context.request
            except LookupError:
                req = None
            if req is not None:
                identity = resolve_identity(self.keystore, req.headers)
                if identity is not None:
                    username, group = identity.username, identity.group
                session_id = req.headers.get(MCP_SESSION_HEADER)
        return ToolContext(
            services=self.services,
            username=username,
            group=group,
            session_id=session_id,
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
