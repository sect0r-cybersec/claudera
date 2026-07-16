"""Authenticated REST endpoints backing the magma GUI panel.

The magma Vue component (``gui/views/claudera.vue``) calls these with the
Caldera session cookie (axios ``withCredentials``). Every handler is guarded by
Caldera's ``check_authorization`` (requires a logged-in Caldera user with app
access). Key management is scoped: a user manages their own keys; users listed
in ``payloads``-adjacent ``gui.admin_users`` config may manage anyone's.

This file is original to the claudera plugin (Apache-2.0). ``check_authorization``
is Caldera's own decorator (Apache-2.0).
"""

from __future__ import annotations

from aiohttp import web
from aiohttp_security import authorized_userid

from app.service.auth_svc import check_authorization

from .auth import group_for_user


class ClauderaGuiApi:
    def __init__(self, services: dict, store, config: dict | None = None):
        self.services = services
        self.auth_svc = services.get("auth_svc")  # required by check_authorization
        self.store = store
        self.config = config or {}
        self.admin_users = set((self.config.get("gui") or {}).get("admin_users") or [])

    async def _username(self, request) -> str | None:
        return await authorized_userid(request)

    def _is_admin(self, username: str | None) -> bool:
        return username in self.admin_users

    # -- run history -----------------------------------------------------------

    @check_authorization
    async def runs(self, request):
        return web.json_response(self.store.list_runs())

    @check_authorization
    async def events(self, request):
        session_id = request.query.get("session_id")
        return web.json_response(self.store.list_events(session_id=session_id))

    @check_authorization
    async def downloads(self, request):
        return web.json_response(self.store.list_downloads())

    # -- key admin -------------------------------------------------------------

    @check_authorization
    async def keys(self, request):
        user = await self._username(request)
        keys = self.store.list_keys() if self._is_admin(user) else self.store.list_keys(username=user)
        return web.json_response([k.to_dict() for k in keys])

    @check_authorization
    async def issue_key(self, request):
        user = await self._username(request)
        data = await request.json()
        target = data.get("username") or user
        if target != user and not self._is_admin(user):
            return web.json_response({"error": "not permitted to issue keys for another user"}, status=403)
        group = group_for_user(self.auth_svc, target)
        if not group:
            return web.json_response({"error": f"unknown Caldera user '{target}'"}, status=400)
        key_id, token = self.store.issue(target, group)
        return web.json_response({"key_id": key_id, "token": token, "username": target, "group": group})

    async def _owned_key_or_error(self, request):
        """Return (key_record, None) if the caller may manage the key, else (None, response)."""
        user = await self._username(request)
        data = await request.json()
        key_id = data.get("key_id")
        rec = self.store.get(key_id) if key_id else None
        if rec is None:
            return None, web.json_response({"error": "no such key"}, status=404)
        if rec.username != user and not self._is_admin(user):
            return None, web.json_response({"error": "not permitted to manage this key"}, status=403)
        return rec, None

    @check_authorization
    async def rotate_key(self, request):
        rec, err = await self._owned_key_or_error(request)
        if err:
            return err
        token = self.store.rotate(rec.key_id)
        return web.json_response({"key_id": rec.key_id, "token": token})

    @check_authorization
    async def revoke_key(self, request):
        rec, err = await self._owned_key_or_error(request)
        if err:
            return err
        self.store.revoke(rec.key_id)
        return web.json_response({"key_id": rec.key_id, "active": False})

    @check_authorization
    async def activate_key(self, request):
        rec, err = await self._owned_key_or_error(request)
        if err:
            return err
        self.store.set_active(rec.key_id, True)
        return web.json_response({"key_id": rec.key_id, "active": True})

    def register_routes(self, router) -> None:
        router.add_get("/plugin/claudera/api/runs", self.runs)
        router.add_get("/plugin/claudera/api/events", self.events)
        router.add_get("/plugin/claudera/api/downloads", self.downloads)
        router.add_get("/plugin/claudera/api/keys", self.keys)
        router.add_post("/plugin/claudera/api/keys/issue", self.issue_key)
        router.add_post("/plugin/claudera/api/keys/rotate", self.rotate_key)
        router.add_post("/plugin/claudera/api/keys/revoke", self.revoke_key)
        router.add_post("/plugin/claudera/api/keys/activate", self.activate_key)
