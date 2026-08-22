"""Command-line key administration for claudera.

Issue, list, revoke, and delete per-user MCP bearer keys from the shell. A key's
lifecycle is create -> revoke -> delete; there is no rotate. The GUI panel is the
primary admin path, and this CLI is handy for tests and automation.

The group for a key is taken from Caldera's own ``users`` config so a key can
only map to a real user's real group.

Run from the Caldera root with the Caldera venv, e.g.::

    python -m plugins.claudera.app.cli issue --user red
    python -m plugins.claudera.app.cli list
    python -m plugins.claudera.app.cli revoke --key-id <id>
    python -m plugins.claudera.app.cli delete --key-id <id>

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import argparse
import os
import sys

from app.utility.base_world import BaseWorld

from plugins.claudera.app.store import KeyStore

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "data", "claudera.db")


def _user_groups(config_path: str) -> dict[str, str]:
    """Map username -> group from a Caldera config file's ``users`` section."""
    config = BaseWorld.strip_yml(config_path)[0]
    mapping: dict[str, str] = {}
    for group, members in (config.get("users") or {}).items():
        for username in members:
            mapping[username] = group
    return mapping


def _cmd_issue(store: KeyStore, args) -> int:
    groups = _user_groups(args.config)
    group = args.group or groups.get(args.user)
    if group is None:
        print(
            f"error: user '{args.user}' not found in {args.config}. "
            f"Known users: {', '.join(sorted(groups)) or '(none)'}. "
            f"Pass --group to override.",
            file=sys.stderr,
        )
        return 2
    key_id, token = store.issue(args.user, group)
    print(f"Issued key for user '{args.user}' (group '{group}').")
    print(f"  key_id: {key_id}")
    print(f"  token : {token}")
    print("\nThis token is shown ONCE. Store it now; it cannot be recovered.")
    return 0


def _cmd_list(store: KeyStore, args) -> int:
    keys = store.list_keys(args.user)
    if not keys:
        print("No keys.")
        return 0
    print(f"{'key_id':14} {'user':12} {'group':8} {'active':7} {'created':21} last_used")
    for k in keys:
        print(
            f"{k.key_id:14} {k.username:12} {k.group:8} "
            f"{str(k.active):7} {k.created_at:21} {k.last_used_at or '-'}"
        )
    return 0


def _cmd_revoke(store: KeyStore, args) -> int:
    ok = store.revoke(args.key_id)
    print(f"Revoked '{args.key_id}' (permanent; delete it to remove)." if ok
          else f"error: no key with key_id '{args.key_id}'")
    return 0 if ok else 2


def _cmd_delete(store: KeyStore, args) -> int:
    ok = store.delete(args.key_id)
    print(f"Deleted '{args.key_id}'." if ok else f"error: no key with key_id '{args.key_id}'")
    return 0 if ok else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claudera-keyadmin", description="Manage claudera MCP bearer keys.")
    p.add_argument("--db", default=DEFAULT_DB, help="Path to claudera.db (default: plugin data dir).")
    p.add_argument("--config", default="conf/default.yml", help="Caldera config for user->group lookup.")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("issue", help="Issue a new key for a user.")
    pi.add_argument("--user", required=True)
    pi.add_argument("--group", help="Override group (default: from Caldera config).")
    pi.set_defaults(func=_cmd_issue)

    pl = sub.add_parser("list", help="List keys.")
    pl.add_argument("--user", help="Filter by user.")
    pl.set_defaults(func=_cmd_list)

    prv = sub.add_parser("revoke", help="Revoke a key permanently (cannot be reactivated).")
    prv.add_argument("--key-id", required=True)
    prv.set_defaults(func=_cmd_revoke)

    pd = sub.add_parser("delete", help="Delete a key permanently.")
    pd.add_argument("--key-id", required=True)
    pd.set_defaults(func=_cmd_delete)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    store = KeyStore(os.path.abspath(args.db))
    return args.func(store, args)


if __name__ == "__main__":
    raise SystemExit(main())
