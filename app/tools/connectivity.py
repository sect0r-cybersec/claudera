"""Connectivity tools — prove the MCP transport end to end (step 1).

These carry no Caldera privileges and mutate nothing, so they are safe to expose
before bearer auth lands. They let a Claude client confirm ``initialize`` /
``tools/list`` / ``tools/call`` all work against the live server.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import time

from app.version import get_version as get_caldera_version

from . import Registry, ToolContext, ToolSpec

_STARTED_AT = time.time()


async def _server_info(ctx: ToolContext, arguments: dict) -> dict:
    return {
        "plugin": "claudera",
        "description": "Caldera authenticated remote MCP server",
        "caldera_version": get_caldera_version(),
        "authenticated_user": ctx.username,
        "group": ctx.group,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


async def _ping(ctx: ToolContext, arguments: dict) -> dict:
    return {
        "pong": True,
        "echo": arguments.get("message", ""),
        "server_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def register(registry: Registry) -> None:
    registry.add(
        ToolSpec(
            name="server_info",
            description=(
                "Return identifying information about this Caldera MCP server: "
                "plugin name, Caldera version, and the authenticated user/group "
                "(null until authentication is enabled)."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_server_info,
        )
    )
    registry.add(
        ToolSpec(
            name="ping",
            description="Connectivity check. Echoes an optional message and returns server time.",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Optional text to echo back."}
                },
                "additionalProperties": False,
            },
            handler=_ping,
        )
    )
