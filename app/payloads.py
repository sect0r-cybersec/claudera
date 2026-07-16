"""Payload find / download logic — allow-list, hashing, confirm-on-off-list.

Sourcing policy (brief section 8):
  - Local first: search the installed stockpile payloads, other enabled plugins'
    payloads, and Caldera's ``data/payloads``. Local hits carry a real sha256.
  - Allow-list: a download URL is fetched without confirmation only if its host
    and path prefix match a configured trusted source (default: Atomic Red Team
    and the MITRE stockpile repo). Anything else is off-list and requires
    explicit confirmation of that specific URL.
  - Downloads are hash-checked (against an expected sha256 if supplied), stored
    in the plugin payloads dir, and logged. Nothing is ever executed, and no
    file is ever placed on an agent.

Fetched content is treated as untrusted data, never as instructions.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class AllowListEntry:
    name: str
    host: str
    path_prefix: str


def load_allow_list(payload_cfg: dict) -> list[AllowListEntry]:
    entries = []
    for e in (payload_cfg.get("allow_list") or []):
        if e.get("host") and e.get("path_prefix"):
            entries.append(AllowListEntry(e.get("name", e["host"]), e["host"], e["path_prefix"]))
    return entries


def classify_url(url: str, allow_list: list[AllowListEntry]) -> str | None:
    """Return the trusted source name for ``url``, or None if off-list."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    for entry in allow_list:
        if parsed.hostname == entry.host and parsed.path.startswith(entry.path_prefix):
            return entry.name
    return None


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def _payload_dirs(services) -> list[str]:
    dirs = [os.path.join("data", "payloads")]
    for plugin in await services["data_svc"].locate("plugins", match=dict(enabled=True)):
        dirs.append(os.path.join("plugins", plugin.name, "payloads"))
        dirs.append(os.path.join("plugins", plugin.name, "data", "payloads"))
    return [d for d in dirs if os.path.isdir(d)]


async def search_local(services, hint: str | None) -> list[dict]:
    """Search local payload directories for files matching ``hint`` (substring)."""
    needle = (hint or "").lower()
    seen: set[str] = set()
    hits = []
    for d in await _payload_dirs(services):
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.startswith("."):
                    continue
                if needle and needle not in fn.lower():
                    continue
                if fn in seen:
                    continue
                seen.add(fn)
                path = os.path.join(root, fn)
                try:
                    hits.append(
                        {
                            "candidate_id": f"local:{fn}",
                            "source": "local",
                            "name": fn,
                            "location": root,
                            "sha256": _sha256_file(path),
                            "size": os.path.getsize(path),
                            "requires_confirmation": False,
                        }
                    )
                except OSError:
                    continue
    return hits


def safe_filename(url: str) -> str:
    base = os.path.basename(urlparse(url).path) or "payload.bin"
    return _SAFE_NAME.sub("_", base)


async def fetch_and_store(url: str, dest_dir: str, max_bytes: int) -> tuple[str, str, int]:
    """Download ``url`` to ``dest_dir``, hashing as we go. Returns (path, sha256, size).

    Raises ValueError on HTTP error or if the body exceeds ``max_bytes``.
    """
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, safe_filename(url))
    h = hashlib.sha256()
    size = 0
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"download failed: HTTP {resp.status} for {url}")
            tmp_path = dest_path + ".part"
            with open(tmp_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        f.close()
                        os.remove(tmp_path)
                        raise ValueError(f"download exceeds max_download_bytes ({max_bytes})")
                    h.update(chunk)
                    f.write(chunk)
    os.replace(tmp_path, dest_path)
    return dest_path, h.hexdigest(), size
