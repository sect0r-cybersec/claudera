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
from .tools import ToolContext, build_registry

log = logging.getLogger("claudera")


class CalderaMCP:
    """Owns the MCP server, tool registry, and Streamable HTTP transport."""

    def __init__(self, services: dict, config: dict | None = None):
        self.services = services
        self.config = config or {}
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
            result = await spec.handler(ctx, arguments or {})
            return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    def _context_for_request(self) -> ToolContext:
        """Build the per-call context.

        Bearer auth (step 2) will resolve the user/group/session from the current
        request here; step 1 has no auth so the context is anonymous.
        """
        return ToolContext(services=self.services)

    # -- aiohttp integration ---------------------------------------------------

    async def handle_http(self, request: web.Request) -> web.StreamResponse:
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
