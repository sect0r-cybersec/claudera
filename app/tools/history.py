"""Run-history read tools.

A "run" is grouped by MCP session id. Every mutating tool call is recorded as an
event (ts, username, tool, artefact type/id/name, status), plus payload
downloads. These tools expose that log; the magma GUI panel consumes the same
store.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

from . import Registry, ToolContext, ToolSpec


async def _get_run_history(ctx: ToolContext, args: dict) -> dict:
    if ctx.store is None:
        return {"runs": [], "events": [], "note": "run-history store unavailable"}
    limit = int(args.get("limit", 100))
    session_id = args.get("session_id")
    return {
        "runs": ctx.store.list_runs(limit=limit),
        "events": ctx.store.list_events(session_id=session_id, limit=limit),
        "downloads": ctx.store.list_downloads(limit=limit),
    }


def register(registry: Registry) -> None:
    registry.add(
        ToolSpec(
            name="get_run_history",
            description=(
                "Return the claudera run history: runs (grouped by MCP session), the mutating "
                "tool-call events (created abilities/adversaries/operations, execution control), "
                "and payload downloads. Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Filter events to one MCP session."},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            handler=_get_run_history,
        )
    )
