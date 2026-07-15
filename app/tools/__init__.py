"""Tool registry for the claudera MCP server.

Each tool is a :class:`ToolSpec` — a name, a JSON-Schema for its arguments, a
description (which also carries naming rules the client should follow), and an
async handler ``(ctx, arguments) -> dict``. Handlers return plain dicts of
structured data (ids, names, status); the server serialises them to JSON. Tools
never return free prose.

Later build steps add their tools by defining specs and registering them via
:func:`Registry.add`. Step 1 ships only the two connectivity tools below.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolContext:
    """Per-call context handed to every tool handler.

    ``username``/``group`` are populated once bearer auth lands (step 2); until
    then they are ``None``. ``session_id`` is the MCP ``Mcp-Session-Id`` used to
    group run-history events (step 7).
    """

    services: dict
    username: str | None = None
    group: str | None = None
    session_id: str | None = None


ToolHandler = Callable[[ToolContext, dict], Awaitable[dict]]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    # Marks state-changing tools whose calls must be recorded in run history.
    mutating: bool = False


@dataclass
class Registry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())


def build_registry(services: dict) -> Registry:
    """Assemble the tool registry. Later steps extend this function."""
    registry = Registry()
    from . import connectivity

    connectivity.register(registry)
    return registry
