"""Execution-control and read-back tools.

Execution control drives Caldera's own operation state machine: pausing is the
operation blocking in ``apply()`` until state is RUNNING again; stopping sets the
FINISHED state, which the planner loop honours. ``run()`` is scheduled lazily on
first start (idempotent per operation) so created operations stay inert until
launched.

Read-back tools report operations, their per-ability results, and collected
facts. Everything returns structured data; nothing mutates on the read side.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from datetime import datetime

import yaml

from app.utility.base_world import BaseWorld

from . import Registry, ToolContext, ToolSpec

_LINK_STATUS = {
    -5: "high_viz", -4: "untrusted", -3: "executing", -2: "discarded",
    -1: "paused", 0: "success", 1: "error", 124: "timeout",
}


def _status_label(value) -> str:
    return _LINK_STATUS.get(value, str(value))


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value if value is None else str(value)


def _access(ctx: ToolContext):
    group = (ctx.group or "").lower()
    A = BaseWorld.Access
    return {"red": A.RED, "blue": A.BLUE}.get(group, A.RED)


def _visible(ctx: ToolContext, obj) -> bool:
    acc = getattr(obj, "access", None)
    if acc is None:
        return True
    A = BaseWorld.Access
    group = (ctx.group or "").lower()
    if group == "blue":
        return acc in (A.BLUE, A.APP)
    if group == "red":
        return acc in (A.RED, A.APP)
    return True


async def _get_operation(ctx: ToolContext, op_id: str):
    ops = await ctx.services["data_svc"].locate("operations", match=dict(id=op_id))
    if not ops:
        raise ValueError(f"unknown operation id: {op_id}")
    op = ops[0]
    if not _visible(ctx, op):
        raise ValueError(f"operation {op_id} is not accessible to group '{ctx.group}'")
    return op


# -- execution control --------------------------------------------------------

async def _ensure_running(op, ctx: ToolContext) -> None:
    if await op.is_finished():
        raise ValueError(f"operation {op.id} has already finished and cannot be (re)started")
    op.state = op.states["RUNNING"]
    if not getattr(op, "_claudera_run_scheduled", False):
        op._claudera_run_scheduled = True
        asyncio.get_running_loop().create_task(op.run(ctx.services))


async def _start_operation(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    await _ensure_running(op, ctx)
    return {"status": "running", "operation_id": op.id, "name": op.name, "state": op.state}


async def _resume_operation(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    await _ensure_running(op, ctx)
    return {"status": "resumed", "operation_id": op.id, "name": op.name, "state": op.state}


async def _pause_operation(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    if await op.is_finished():
        raise ValueError(f"operation {op.id} has already finished")
    op.state = op.states["PAUSED"]
    return {"status": "paused", "operation_id": op.id, "name": op.name, "state": op.state}


async def _stop_operation(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    op.state = op.states["FINISHED"]
    return {"status": "stopped", "operation_id": op.id, "name": op.name, "state": op.state}


async def _operation_status(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    chain = list(op.chain)
    by_status = Counter(_status_label(link.status) for link in chain)
    recent = [
        {
            "paw": link.paw,
            "host": link.host,
            "ability": getattr(link.ability, "name", None),
            "technique_id": getattr(link.ability, "technique_id", None),
            "status": _status_label(link.status),
            "finish_utc": _iso(link.finish),
        }
        for link in chain[-20:]
    ]
    return {
        "operation_id": op.id,
        "name": op.name,
        "state": op.state,
        "group": op.group,
        "adversary": getattr(op.adversary, "name", None),
        "planner": getattr(op.planner, "name", None),
        "start_utc": _iso(op.start),
        "finish_utc": _iso(op.finish),
        "agents": [a.paw for a in op.agents],
        "links_total": len(chain),
        "links_by_status": dict(by_status),
        "recent_links": recent,
    }


# -- read-back ----------------------------------------------------------------

def _read_output(ctx: ToolContext, link) -> str | None:
    if not getattr(link, "output", False):
        return None
    try:
        raw = ctx.services["file_svc"].read_result_file(link.unique)
        return BaseWorld.decode_bytes(raw)
    except Exception:  # noqa: BLE001
        return None


async def _operation_report(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    include_output = bool(args.get("include_output", False))
    steps = []
    for link in op.chain:
        entry = {
            "paw": link.paw,
            "host": link.host,
            "ability": getattr(link.ability, "name", None),
            "technique_id": getattr(link.ability, "technique_id", None),
            "command": link.raw_command,
            "status": _status_label(link.status),
            "pid": link.pid,
            "decide_utc": _iso(link.decide),
            "collect_utc": _iso(link.collect),
            "finish_utc": _iso(link.finish),
        }
        if include_output:
            entry["output"] = _read_output(ctx, link)
        steps.append(entry)
    return {
        "operation_id": op.id,
        "name": op.name,
        "state": op.state,
        "start_utc": _iso(op.start),
        "finish_utc": _iso(op.finish),
        "step_count": len(steps),
        "steps": steps,
    }


async def _query_facts(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    facts = await op.all_facts()
    rows = [
        {
            "trait": f.trait,
            "value": f.value,
            "score": f.score,
            "source": f.source,
            "origin_type": getattr(getattr(f, "origin_type", None), "name", None) or str(getattr(f, "origin_type", "")),
            "technique_id": getattr(f, "technique_id", None),
            "collected_by": list(getattr(f, "collected_by", []) or []),
        }
        for f in facts
    ]
    return {"operation_id": op.id, "name": op.name, "fact_count": len(rows), "facts": rows}


async def _list_abilities(ctx: ToolContext, args: dict) -> dict:
    abilities = await ctx.services["data_svc"].locate("abilities")
    tactic = (args.get("tactic") or "").lower() or None
    technique = args.get("technique_id") or None
    rows = []
    for a in abilities:
        if not _visible(ctx, a):
            continue
        if tactic and (a.tactic or "").lower() != tactic:
            continue
        if technique and a.technique_id != technique:
            continue
        rows.append(
            {
                "ability_id": a.ability_id,
                "name": a.name,
                "tactic": a.tactic,
                "technique_id": a.technique_id,
                "platforms": sorted({e.platform for e in a.executors}),
            }
        )
    rows.sort(key=lambda r: (r["tactic"] or "", r["name"] or ""))
    return {"count": len(rows), "abilities": rows}


async def _list_adversaries(ctx: ToolContext, args: dict) -> dict:
    advs = await ctx.services["data_svc"].locate("adversaries")
    rows = [
        {
            "adversary_id": a.adversary_id,
            "name": a.name,
            "description": a.description,
            "ability_count": len(a.atomic_ordering),
        }
        for a in advs
        if _visible(ctx, a)
    ]
    rows.sort(key=lambda r: r["name"] or "")
    return {"count": len(rows), "adversaries": rows}


async def _list_operations(ctx: ToolContext, args: dict) -> dict:
    ops = await ctx.services["data_svc"].locate("operations")
    rows = [
        {
            "operation_id": o.id,
            "name": o.name,
            "state": o.state,
            "group": o.group,
            "adversary": getattr(o.adversary, "name", None),
            "start_utc": _iso(o.start),
        }
        for o in ops
        if _visible(ctx, o)
    ]
    rows.sort(key=lambda r: r["start_utc"] or "", reverse=True)
    return {"count": len(rows), "operations": rows}


# -- delete -------------------------------------------------------------------

async def _locate_one(ctx: ToolContext, ram_key: str, match: dict, label: str):
    """Locate a single object the caller's group may see, or raise."""
    objs = [o for o in await ctx.services["data_svc"].locate(ram_key, match=match) if _visible(ctx, o)]
    if not objs:
        raise ValueError(f"unknown or inaccessible {label}: {next(iter(match.values()))}")
    return objs[0]


async def _delete_operation(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    name = op.name
    # rest_svc.delete_operation also clears the operation's source, result
    # files, and fact yml files.
    await ctx.services["rest_svc"].delete_operation({"id": op.id})
    return {"status": "deleted", "operation_id": op.id, "name": name}


async def _delete_ability(ctx: ToolContext, args: dict) -> dict:
    ab = await _locate_one(ctx, "abilities", dict(ability_id=args["ability_id"]), "ability id")
    name = ab.name
    await ctx.services["rest_svc"].delete_ability({"ability_id": ab.ability_id})
    return {"status": "deleted", "ability_id": ab.ability_id, "name": name}


async def _delete_adversary(ctx: ToolContext, args: dict) -> dict:
    adv = await _locate_one(ctx, "adversaries", dict(adversary_id=args["adversary_id"]), "adversary id")
    name = adv.name
    await ctx.services["rest_svc"].delete_adversary({"adversary_id": adv.adversary_id})
    return {"status": "deleted", "adversary_id": adv.adversary_id, "name": name}


# -- export -------------------------------------------------------------------

async def _on_disk_yaml(ctx: ToolContext, obj_id: str, fallback_display: dict) -> str:
    """Return the object's on-disk YAML (byte-for-byte how Caldera stores it),
    falling back to a schema dump for objects that live only in memory."""
    try:
        _, path = await ctx.services["file_svc"].find_file_path(f"{obj_id}.yml", location="data")
    except Exception:
        path = None
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return yaml.safe_dump([fallback_display], sort_keys=False, allow_unicode=True)


async def _export_ability(ctx: ToolContext, args: dict) -> dict:
    ab = await _locate_one(ctx, "abilities", dict(ability_id=args["ability_id"]), "ability id")
    content = await _on_disk_yaml(ctx, ab.ability_id, ab.display)
    return {"status": "exported", "ability_id": ab.ability_id, "name": ab.name,
            "format": "yaml", "filename": f"{ab.ability_id}.yml", "content": content}


async def _export_adversary(ctx: ToolContext, args: dict) -> dict:
    adv = await _locate_one(ctx, "adversaries", dict(adversary_id=args["adversary_id"]), "adversary id")
    content = await _on_disk_yaml(ctx, adv.adversary_id, adv.display)
    return {"status": "exported", "adversary_id": adv.adversary_id, "name": adv.name,
            "format": "yaml", "filename": f"{adv.adversary_id}.yml", "content": content}


async def _export_operation(ctx: ToolContext, args: dict) -> dict:
    op = await _get_operation(ctx, args["operation_id"])
    report = await op.report(ctx.services["file_svc"], ctx.services["data_svc"],
                             output=bool(args.get("include_output", False)))
    content = json.dumps(report, indent=2, default=str)
    return {"status": "exported", "operation_id": op.id, "name": op.name,
            "format": "json", "filename": f"{op.name}.json", "content": content}


# -- registration -------------------------------------------------------------

def _op_id_schema(extra: dict | None = None) -> dict:
    props = {"operation_id": {"type": "string"}}
    if extra:
        props.update(extra)
    return {"type": "object", "properties": props, "required": ["operation_id"], "additionalProperties": False}


def register(registry: Registry) -> None:
    control = [
        ("start_operation", "Launch a defined (paused) operation.", _start_operation, {}),
        ("resume_operation", "Resume a paused operation.", _resume_operation, {}),
        ("pause_operation", "Pause a running operation.", _pause_operation, {}),
        ("stop_operation", "Stop (finish) an operation.", _stop_operation, {}),
    ]
    for tool_name, desc, handler, extra in control:
        registry.add(ToolSpec(name=tool_name, description=desc, input_schema=_op_id_schema(extra),
                              handler=handler, mutating=True))

    registry.add(ToolSpec(
        name="get_operation_status",
        description="Poll an operation: state, agents, and per-link status counts.",
        input_schema=_op_id_schema(), handler=_operation_status,
    ))
    registry.add(ToolSpec(
        name="get_operation_report",
        description=("Per-ability report for an operation: host, resolved command, decide/collect/finish "
                     "UTC times, status, and (optionally) output."),
        input_schema=_op_id_schema({"include_output": {"type": "boolean", "description": "Include command output (default false)."}}),
        handler=_operation_report,
    ))
    registry.add(ToolSpec(
        name="query_facts",
        description="List the facts an operation has collected (trait, value, score, source, technique).",
        input_schema=_op_id_schema(), handler=_query_facts,
    ))
    registry.add(ToolSpec(
        name="list_abilities",
        description="List abilities, optionally filtered by tactic or technique_id.",
        input_schema={"type": "object", "properties": {
            "tactic": {"type": "string"}, "technique_id": {"type": "string"}},
            "additionalProperties": False},
        handler=_list_abilities,
    ))
    registry.add(ToolSpec(
        name="list_adversaries", description="List adversary profiles.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_list_adversaries,
    ))
    registry.add(ToolSpec(
        name="list_operations", description="List operations, newest first.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_list_operations,
    ))

    # -- delete (mutating) ----------------------------------------------------
    registry.add(ToolSpec(
        name="delete_operation",
        description="Permanently delete an operation (and its results, source, and collected facts). Irreversible.",
        input_schema=_op_id_schema(), handler=_delete_operation, mutating=True,
    ))
    registry.add(ToolSpec(
        name="delete_ability",
        description="Permanently delete an ability by id (removes it from memory and disk). Irreversible.",
        input_schema={"type": "object", "properties": {"ability_id": {"type": "string"}},
                      "required": ["ability_id"], "additionalProperties": False},
        handler=_delete_ability, mutating=True,
    ))
    registry.add(ToolSpec(
        name="delete_adversary",
        description="Permanently delete an adversary profile by id (removes it from memory and disk). Irreversible.",
        input_schema={"type": "object", "properties": {"adversary_id": {"type": "string"}},
                      "required": ["adversary_id"], "additionalProperties": False},
        handler=_delete_adversary, mutating=True,
    ))

    # -- export (read-only) ---------------------------------------------------
    registry.add(ToolSpec(
        name="export_ability",
        description=("Fetch an ability's full definition as Caldera stores it (YAML). Returns "
                     "'content' (the file body), 'filename', and 'format' so the client can save it "
                     "and commit it to GitHub or share it."),
        input_schema={"type": "object", "properties": {"ability_id": {"type": "string"}},
                      "required": ["ability_id"], "additionalProperties": False},
        handler=_export_ability,
    ))
    registry.add(ToolSpec(
        name="export_adversary",
        description=("Fetch an adversary profile's full definition as Caldera stores it (YAML). Returns "
                     "'content', 'filename', and 'format' so the client can save it and share it. Note the "
                     "profile references ability ids; export those separately to reproduce it elsewhere."),
        input_schema={"type": "object", "properties": {"adversary_id": {"type": "string"}},
                      "required": ["adversary_id"], "additionalProperties": False},
        handler=_export_adversary,
    ))
    registry.add(ToolSpec(
        name="export_operation",
        description=("Fetch an operation's full report as JSON. Returns 'content' (the file body), "
                     "'filename', and 'format' so the client can save it. Set include_output to embed "
                     "command output."),
        input_schema=_op_id_schema({"include_output": {"type": "boolean",
                     "description": "Include command output in the report (default false)."}}),
        handler=_export_operation,
    ))
