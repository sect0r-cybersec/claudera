"""Minimal ASGI-to-aiohttp adapter.

Caldera's web layer is aiohttp; the MCP Python SDK's Streamable HTTP transport
(``StreamableHTTPSessionManager``) is an ASGI application. Rather than stand up
a second web server (uvicorn on a separate port) we drive the ASGI callable
directly from an aiohttp request handler, so the MCP endpoint shares Caldera's
process, event loop, and listening port.

Only the ``http`` ASGI scope is implemented — that is all the MCP transport
uses. The adapter streams the response so both single-shot JSON responses and
long-lived ``text/event-stream`` responses work.

This file is original to the claudera plugin (Apache-2.0).
"""

import asyncio

from aiohttp import web
from multidict import CIMultiDict

# Response headers we must not copy verbatim onto an aiohttp StreamResponse:
# aiohttp manages framing (chunked vs. content-length) itself, and copying these
# from the ASGI side produces conflicting/duplicated framing headers.
_SKIP_RESPONSE_HEADERS = {b"content-length", b"transfer-encoding"}


def _build_scope(request: web.Request) -> dict:
    """Translate an aiohttp request into an ASGI ``http`` scope."""
    server_host = request.url.host or "localhost"
    server_port = request.url.port or 0
    client = (request.remote, 0) if request.remote else None
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": request.version.major and "1.1" or "1.1",
        "method": request.method,
        "scheme": request.scheme,
        "path": request.path,
        "raw_path": request.raw_path.encode("latin-1"),
        "query_string": request.query_string.encode("latin-1"),
        "root_path": "",
        "headers": [
            (k.encode("latin-1").lower(), v.encode("latin-1"))
            for k, v in request.headers.items()
        ],
        "client": client,
        "server": (server_host, server_port),
        "state": {},
    }


async def serve_asgi(request: web.Request, asgi) -> web.StreamResponse:
    """Serve an aiohttp request by driving an ASGI callable.

    ``asgi`` is any ``async (scope, receive, send)`` callable — here the MCP
    session manager's ``handle_request`` bound method.
    """
    scope = _build_scope(request)
    body = await request.read()

    disconnected = asyncio.Event()
    request_sent = False
    response: web.StreamResponse | None = None
    prepared = asyncio.Event()

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # After the request body is delivered, block until the response is
        # finished (or the peer goes away) so long-lived streams stay open.
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        nonlocal response
        msg_type = message["type"]
        if msg_type == "http.response.start":
            headers = CIMultiDict()
            for raw_key, raw_val in message.get("headers", []):
                if raw_key.lower() in _SKIP_RESPONSE_HEADERS:
                    continue
                headers.add(raw_key.decode("latin-1"), raw_val.decode("latin-1"))
            response = web.StreamResponse(status=message["status"], headers=headers)
            await response.prepare(request)
            prepared.set()
        elif msg_type == "http.response.body":
            if response is None:
                return
            data = message.get("body", b"")
            if data:
                await response.write(data)
            if not message.get("more_body", False):
                disconnected.set()

    try:
        await asgi(scope, receive, send)
    finally:
        disconnected.set()

    if response is None:
        # ASGI app produced no response start (shouldn't happen) — fail loudly.
        return web.Response(status=500, text="MCP transport produced no response")
    await response.write_eof()
    return response
