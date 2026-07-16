"""Correlation-key emitter — the thin closed-loop handoff.

For each *executed* ability in an operation, emit the join key a separate
Sentinel/Elastic/Defender connector needs to line the red-team action up with
the telemetry it produced:

    { resolved_command, utc_start, utc_stop, technique_id, telemetry_hostname }

``telemetry_hostname`` is the host's name as telemetry sees it (DeviceName /
host.name / Sysmon Computer), taken from the Caldera agent that ran the link —
not the paw. This plugin does not query any SIEM; it only emits the keys.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

from . import Registry, ToolContext, ToolSpec
from .operations import _get_operation, _iso, _status_label

# Statuses that mean the command actually ran on the host.
_EXECUTED = {0, 1, 124}  # SUCCESS, ERROR, TIMEOUT


async def _get_correlation_keys(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    agents = {a.paw: a for a in await ctx.services["data_svc"].locate("agents")}

    keys = []
    for link in op.chain:
        if link.status not in _EXECUTED and link.finish is None:
            continue  # not an executed ability
        agent = agents.get(link.paw)
        telemetry_hostname = (getattr(agent, "host", None) or link.host)
        keys.append(
            {
                "resolved_command": link.raw_command,
                "utc_start": _iso(link.decide),
                "utc_stop": _iso(link.finish),
                "technique_id": getattr(link.ability, "technique_id", None),
                "telemetry_hostname": telemetry_hostname,
                "agent_paw": link.paw,
                "host_ip_addrs": list(getattr(agent, "host_ip_addrs", []) or []),
                "status": _status_label(link.status),
            }
        )
    return {
        "operation_id": op.id,
        "name": op.name,
        "key_count": len(keys),
        "correlation_keys": keys,
    }


def register(registry: Registry) -> None:
    registry.add(
        ToolSpec(
            name="get_correlation_keys",
            description=(
                "Emit SIEM join keys for each executed ability in an operation: resolved_command, "
                "utc_start, utc_stop, technique_id, and telemetry_hostname (the host as telemetry sees "
                "it, mapped from the Caldera agent, not the paw). Use these to correlate red-team "
                "actions with SIEM telemetry; this tool does not query any SIEM."
            ),
            input_schema={
                "type": "object",
                "properties": {"operation_id": {"type": "string"}},
                "required": ["operation_id"],
                "additionalProperties": False,
            },
            handler=_get_correlation_keys,
        )
    )
