"""claudera plugin hook.

Registers an authenticated remote MCP server as a route on Caldera's own aiohttp
application. An external Claude client (Claude Code / Claude Desktop) connects
over the LAN via Streamable HTTP; Caldera exposes tools and Claude is the client.

This is the inverse of the bundled ``mcp`` plugin: no model API key lives in
Caldera. This plugin is a fresh build; only small, clearly-marked pieces are
vendored from Caldera (Apache-2.0) — see NOTICE.md and the README.

Plugin hook conventions (name/description/address/access + async enable) follow
Caldera 5.3.0 core plugins such as ``plugins/stockpile/hook.py``.
"""

import logging
import os

from aiohttp import web

from app.utility.base_world import BaseWorld

from plugins.claudera.app.mcp_server import CalderaMCP
from plugins.claudera.app.gui_api import ClauderaGuiApi

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PLUGIN_DIR, 'data', 'claudera.db')

name = 'claudera'
description = 'Authenticated remote MCP server exposing Caldera to an external Claude client'
address = '/plugin/claudera/gui'
access = BaseWorld.Access.APP

log = logging.getLogger('claudera')


async def _splash(request):
    """Minimal landing page. The full magma GUI panel arrives in a later step."""
    cfg = BaseWorld.get_config(prop='mcp', name='claudera') or {}
    path = cfg.get('path', '/mcp')
    body = (
        '<html><head><title>claudera</title></head><body style="font-family:sans-serif">'
        '<h2>claudera &mdash; Caldera remote MCP server</h2>'
        f'<p>MCP endpoint is served at <code>{path}</code> on this host/port.</p>'
        '<p>Point a Claude client at it with a bearer key (see the plugin README).</p>'
        '</body></html>'
    )
    return web.Response(text=body, content_type='text/html')


async def enable(services):
    BaseWorld.apply_config(
        'claudera',
        BaseWorld.strip_yml('plugins/claudera/conf/default.yml')[0],
    )
    plugin_cfg = BaseWorld.get_config(name='claudera') or {}
    path = (plugin_cfg.get('mcp') or {}).get('path', '/mcp')

    app = services.get('app_svc').application
    caldera_mcp = CalderaMCP(services, plugin_cfg, db_path=DB_PATH, plugin_dir=PLUGIN_DIR)

    # Single MCP endpoint. Streamable HTTP uses POST for requests, GET to open a
    # server->client stream, and DELETE to end a session, so route all methods.
    app.router.add_route('*', path, caldera_mcp.handle_http)
    app.router.add_route('GET', '/plugin/claudera/gui', _splash)

    # Authenticated REST endpoints backing the magma GUI panel.
    gui_api = ClauderaGuiApi(services, caldera_mcp.keystore, plugin_cfg)
    gui_api.register_routes(app.router)

    # Drive the MCP session-manager task group for the app's lifetime. enable()
    # runs during load_plugins, before AppRunner.setup(), so appending here is
    # safe — the cleanup context fires on startup/shutdown.
    app.cleanup_ctx.append(caldera_mcp.lifespan)

    log.info('claudera MCP server mounted at %s', path)
