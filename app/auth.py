"""Bearer authentication for the claudera MCP server.

Every MCP request must carry ``Authorization: Bearer <key>``. The key resolves,
via the per-user :class:`KeyStore`, to a Caldera username and their group. The
resolved identity scopes tool actions and attributes run-history events to a
person. A bad or missing key is rejected with HTTP 401 at the transport layer.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import KeyRecord, KeyStore


@dataclass
class Identity:
    username: str
    group: str
    key_id: str

    @classmethod
    def from_record(cls, rec: KeyRecord) -> "Identity":
        return cls(username=rec.username, group=rec.group, key_id=rec.key_id)


def extract_bearer(headers) -> str | None:
    """Pull the bearer token out of an Authorization header (case-insensitive scheme)."""
    value = None
    # Works for aiohttp CIMultiDict and Starlette Headers alike.
    for key in ("Authorization", "authorization"):
        try:
            value = headers.get(key)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            break
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def resolve_identity(keystore: KeyStore, headers) -> Identity | None:
    """Resolve the Authorization header to an :class:`Identity`, or None."""
    token = extract_bearer(headers)
    if not token:
        return None
    rec = keystore.validate(token)
    if rec is None:
        return None
    return Identity.from_record(rec)


def group_for_user(auth_svc, username: str) -> str | None:
    """Return the Caldera group for ``username`` from auth_svc.user_map, or None.

    The group is taken from the authoritative Caldera user map so a key can only
    ever map to a real user's real group.
    """
    user = getattr(auth_svc, "user_map", {}).get(username)
    if user is None:
        return None
    # user.permissions is like ('red', 'app'); the first entry is the group.
    perms = getattr(user, "permissions", ())
    return perms[0] if perms else None
