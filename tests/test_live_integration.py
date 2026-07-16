"""Optional live integration test against a running Caldera claudera endpoint.

Skipped unless both env vars are set (keeps the offline suite clean and avoids
side effects on the lab)::

    CLAUDERA_MCP_URL=http://127.0.0.1:8888/mcp \
    CLAUDERA_MCP_KEY=cald_xxxx.yyyy \
    /home/sam/.calderavenv/bin/python3 -m unittest plugins.claudera.tests.test_live_integration

Exercises the auth path and one read tool per client would use.
"""

import os
import unittest

URL = os.environ.get("CLAUDERA_MCP_URL")
KEY = os.environ.get("CLAUDERA_MCP_KEY")


@unittest.skipUnless(URL and KEY, "set CLAUDERA_MCP_URL and CLAUDERA_MCP_KEY to run")
class TestLive(unittest.IsolatedAsyncioTestCase):
    async def _session(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        return streamablehttp_client(URL, headers={"Authorization": f"Bearer {KEY}"})

    async def test_valid_key_lists_tools_and_agents(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(URL, headers={"Authorization": f"Bearer {KEY}"}) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = [t.name for t in (await s.list_tools()).tools]
                self.assertIn("list_agents", tools)
                res = await s.call_tool("list_agents", {})
                self.assertFalse(res.isError)

    async def test_invalid_key_rejected(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        with self.assertRaises(Exception):
            async with streamablehttp_client(URL, headers={"Authorization": "Bearer cald_bad.bad"}) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()


if __name__ == "__main__":
    unittest.main()
