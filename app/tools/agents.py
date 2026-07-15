"""Agent read-back tools.

``list_agents`` reports the deployed Caldera agents (sandcat/manx beacons) as the
telemetry sees them: paw, host, addresses, platform, group, and last-seen time.
It mutates nothing. Results are scoped to the caller's group.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

from datetime import datetime

from . import Registry, ToolContext, ToolSpec


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value if value is None else str(value)


def _visible_to(ctx: ToolContext, agent) -> bool:
    """Scope agents to the caller's group.

    A blue caller sees only blue-group agents; red/admin (app) callers see all.
    Caldera agents are otherwise operator-visible, so this is a deliberately
    conservative default that can be tightened per deployment.
    """
    group = (ctx.group or "").lower()
    if group in ("blue",):
        return (agent.group or "").lower() == "blue"
    return True


async def _list_agents(ctx: ToolContext, arguments: dict) -> dict:
    data_svc = ctx.services.get("data_svc")
    agents = await data_svc.locate("agents")
    rows = []
    for a in agents:
        if not _visible_to(ctx, a):
            continue
        rows.append(
            {
                "paw": a.paw,
                "host": a.host,
                "display_name": getattr(a, "display_name", None),
                "ip_addrs": list(getattr(a, "host_ip_addrs", []) or []),
                "platform": a.platform,
                "architecture": getattr(a, "architecture", None),
                "username": a.username,
                "group": a.group,
                "contact": a.contact,
                "pid": getattr(a, "pid", None),
                "exe_name": getattr(a, "exe_name", None),
                "trusted": getattr(a, "trusted", None),
                "last_seen_utc": _iso(getattr(a, "last_seen", None)),
                "created_utc": _iso(getattr(a, "created", None)),
            }
        )
    rows.sort(key=lambda r: r["last_seen_utc"] or "", reverse=True)
    return {"count": len(rows), "scoped_to_group": ctx.group, "agents": rows}


def register(registry: Registry) -> None:
    registry.add(
        ToolSpec(
            name="list_agents",
            description=(
                "List deployed Caldera agents visible to the authenticated user: "
                "paw, host (as telemetry sees it), IP addresses, platform, group, "
                "username, contact, and last-seen UTC time. Read-only."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_list_agents,
        )
    )
