"""Payload find / download tools.

``find_payload`` searches local payloads first (real hashes) and classifies an
optional URL against the trusted allow-list — it downloads nothing.
``download_payload`` fetches an allow-listed URL (or an off-list URL only when
explicitly confirmed), verifies the sha256, stores it in the plugin payloads dir,
and logs the event. Nothing is executed; nothing is placed on an agent.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import os

from .. import payloads as payloadsvc
from . import Registry, ToolContext, ToolSpec


def _payload_cfg(ctx: ToolContext) -> dict:
    return (ctx.config.get("payloads") or {}) if ctx.config else {}


async def _find_payload(ctx: ToolContext, args: dict) -> dict:
    cfg = _payload_cfg(ctx)
    allow_list = payloadsvc.load_allow_list(cfg)
    hint = args.get("hint")
    url = args.get("url")

    local = await payloadsvc.search_local(ctx.services, hint)
    remote = []
    if url:
        source = payloadsvc.classify_url(url, allow_list)
        remote.append(
            {
                "candidate_id": url,
                "source": source or "off-list",
                "url": url,
                "sha256": None,  # unknown until downloaded
                "size": None,
                "requires_confirmation": source is None,
            }
        )
    return {
        "query": hint,
        "local_count": len(local),
        "local": local,
        "remote": remote,
        "trusted_sources": [
            {"name": e.name, "host": e.host, "path_prefix": e.path_prefix} for e in allow_list
        ],
        "note": (
            "Local hits carry a real sha256. Remote URLs are downloaded only via "
            "download_payload; off-list URLs (requires_confirmation=true) need confirm=true."
        ),
    }


async def _download_payload(ctx: ToolContext, args: dict) -> dict:
    cfg = _payload_cfg(ctx)
    allow_list = payloadsvc.load_allow_list(cfg)
    url = args["url"]
    expected = args.get("expected_sha256")
    confirm = bool(args.get("confirm", False))
    max_bytes = int(cfg.get("max_download_bytes", 52428800))
    dest_dir = os.path.join(ctx.plugin_dir or ".", cfg.get("download_dir", "payloads/downloaded"))

    source = payloadsvc.classify_url(url, allow_list)
    if source is None and not confirm:
        return {
            "status": "requires_confirmation",
            "requires_confirmation": True,
            "url": url,
            "message": (
                "This URL is not on the trusted allow-list. Re-call download_payload with "
                "confirm=true to fetch this specific URL."
            ),
        }

    def _log(status, sha256=None, size=None, dest_path=None):
        if ctx.store is not None:
            ctx.store.log_download(
                username=ctx.username, source=source or "off-list", url=url,
                sha256=sha256, size=size, dest_path=dest_path, status=status,
            )

    try:
        dest_path, sha256, size = await payloadsvc.fetch_and_store(url, dest_dir, max_bytes)
    except ValueError as e:
        _log("error")
        return {"status": "error", "url": url, "error": str(e)}

    if expected and expected.lower() != sha256.lower():
        try:
            os.remove(dest_path)
        except OSError:
            pass
        _log("hash_mismatch", sha256=sha256, size=size)
        return {
            "status": "hash_mismatch",
            "url": url,
            "expected_sha256": expected,
            "actual_sha256": sha256,
            "message": "Downloaded file removed; sha256 did not match expected.",
        }

    _log("ok", sha256=sha256, size=size, dest_path=dest_path)
    return {
        "status": "downloaded",
        "url": url,
        "source": source or "off-list (confirmed)",
        "filename": os.path.basename(dest_path),
        "sha256": sha256,
        "size": size,
        "note": "Stored in the plugin payloads dir; abilities can reference it by filename. Not executed.",
    }


def register(registry: Registry) -> None:
    registry.add(
        ToolSpec(
            name="find_payload",
            description=(
                "Find a payload by name/hint. Searches local payloads first (real sha256), then "
                "reports the trusted allow-list sources. Optionally classifies a specific URL as "
                "on- or off-list. Downloads nothing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hint": {"type": "string", "description": "Filename or substring to search for locally."},
                    "url": {"type": "string", "description": "Optional URL to classify against the allow-list."},
                },
                "additionalProperties": False,
            },
            handler=_find_payload,
        )
    )
    registry.add(
        ToolSpec(
            name="download_payload",
            description=(
                "Download a payload from a URL, verify its sha256, and store it in the plugin "
                "payloads dir (never executed, never placed on an agent). Allow-listed URLs fetch "
                "directly; off-list URLs require confirm=true. Supply expected_sha256 to enforce a hash."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "expected_sha256": {"type": "string", "description": "If given, the download is rejected on mismatch."},
                    "confirm": {"type": "boolean", "description": "Required (true) to fetch an off-list URL."},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=_download_payload,
            mutating=True,
        )
    )
