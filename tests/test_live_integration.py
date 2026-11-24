"""Optional live integration test against a running Caldera claudera endpoint.

Skipped unless both env vars are set (keeps the offline suite clean and avoids
side effects on the lab)::

    CLAUDERA_MCP_URL=http://127.0.0.1:8888/mcp \
    CLAUDERA_MCP_KEY=cald_xxxx.yyyy \
    /home/sam/.calderavenv/bin/python3 -m unittest plugins.claudera.tests.test_live_integration

Exercises the auth path and one read tool per client would use. Protocol-level
coverage that needs neither a host nor a key lives in test_mcp_protocol.py;
this test is about the real transport, a real bearer key and a real Caldera.
"""

import os
import unittest

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("CLAUDERA_MCP_URL")
KEY = os.environ.get("CLAUDERA_MCP_KEY")


def _client(key):
    """A ``Client`` over Streamable HTTP carrying *key* as its bearer token.

    The SDK takes no headers argument of its own: per-request headers belong to
    the ``httpx2`` client the transport is built with. ``Client`` accepts any
    transport, and ``streamable_http_client`` is one, which is also how it
    connects when handed a bare URL string.
    """
    http_client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx2.Timeout(30, read=300),
    )
    return Client(streamable_http_client(URL, http_client=http_client))


@unittest.skipUnless(URL and KEY, "set CLAUDERA_MCP_URL and CLAUDERA_MCP_KEY to run")
class TestLive(unittest.IsolatedAsyncioTestCase):
    async def test_valid_key_lists_tools_and_agents(self):
        async with _client(KEY) as client:
            tools = [tool.name for tool in (await client.list_tools()).tools]
            self.assertIn("list_agents", tools)
            res = await client.call_tool("list_agents", {})
            self.assertFalse(res.is_error)

    async def test_invalid_key_rejected(self):
        with self.assertRaises(Exception):
            async with _client("cald_bad.bad") as client:
                await client.list_tools()


if __name__ == "__main__":
    unittest.main()
