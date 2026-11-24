"""Offline MCP protocol tests driven over the SDK's in-memory transport.

``Client`` connects straight to the ``Server`` object, so handler registration,
handler signatures and result types are exercised on the real dispatch path
without a Caldera host, a network or a bearer key. These are the tests that
catch an SDK API break: the v2 release removed the decorator API the plugin was
built on, and nothing in the offline suite noticed, because the only test that
spoke MCP at all was the env-gated live one.

``Client`` negotiates the newest protocol revision by default, so this also
covers the plugin serving a modern client.

This file is original to the claudera plugin (Apache-2.0).
"""

import os
import tempfile
import unittest
from types import SimpleNamespace

from mcp import MCPError
from mcp.client import Client

from plugins.claudera.app.mcp_server import RUN_KEY_PREFIX, CalderaMCP


def _server(db_path=None):
    """A server wired to the real registry.

    Without ``db_path`` there is no key store, so the per-call identity gate is
    off. That is what makes the tools reachable here: the in-memory transport
    carries no HTTP request, so there is no bearer key to resolve an identity
    from.
    """
    return CalderaMCP(services={}, config={}, db_path=db_path).server


class TestToolListing(unittest.IsolatedAsyncioTestCase):
    async def test_tools_are_listed_over_a_real_session(self):
        async with Client(_server()) as client:
            names = [tool.name for tool in (await client.list_tools()).tools]
        self.assertIn("list_agents", names)
        self.assertIn("delete_adversary", names)

    async def test_every_tool_advertises_an_object_schema(self):
        async with Client(_server()) as client:
            tools = (await client.list_tools()).tools
        self.assertTrue(tools)
        for tool in tools:
            self.assertEqual(tool.input_schema.get("type"), "object", tool.name)


class TestArgumentValidation(unittest.IsolatedAsyncioTestCase):
    """The SDK's lowlevel Server does not enforce a tool's declared schema."""

    async def test_wrong_type_for_array_argument_is_rejected(self):
        # Unvalidated, a bare string here reached the handler and was iterated
        # character by character, reporting four bogus missing abilities.
        async with Client(_server()) as client:
            result = await client.call_tool("export_abilities_bundle", {"ability_ids": "T1055"})
        self.assertTrue(result.is_error)
        self.assertIn("is not of type 'array'", result.content[0].text)

    async def test_missing_required_argument_is_rejected(self):
        async with Client(_server()) as client:
            result = await client.call_tool("delete_adversary", {})
        self.assertTrue(result.is_error)
        self.assertIn("required property", result.content[0].text)

    async def test_undeclared_argument_is_rejected(self):
        async with Client(_server()) as client:
            result = await client.call_tool(
                "delete_adversary", {"adversary_id": "x", "unexpected": 1})
        self.assertTrue(result.is_error)
        self.assertIn("Additional properties", result.content[0].text)

    async def test_unknown_tool_is_an_error_result(self):
        # An error result rather than a protocol error, so the calling model
        # sees the message and can re-list the tools.
        async with Client(_server()) as client:
            result = await client.call_tool("no_such_tool", {})
        self.assertTrue(result.is_error)
        self.assertIn("unknown tool", result.content[0].text)


class TestIdentityGate(unittest.IsolatedAsyncioTestCase):
    async def test_call_without_an_identity_is_refused_at_protocol_level(self):
        # With a key store configured, a call that resolves no Caldera identity
        # is rejected as a protocol error, not returned as a tool result: the
        # model cannot correct an authorisation failure.
        server = _server(db_path=os.path.join(tempfile.mkdtemp(), "keys.db"))
        async with Client(server) as client:
            with self.assertRaises(MCPError) as caught:
                await client.call_tool("list_agents", {})
        self.assertIn("unauthorized", str(caught.exception))


class TestRunGrouping(unittest.TestCase):
    """How run-history events are grouped when there is no transport session.

    From the 2026-07-28 revision the protocol has no session handshake, so no
    Mcp-Session-Id reaches the server and run history would otherwise collapse
    every modern client's events into a single NULL-keyed run.
    """

    def setUp(self):
        self.mcp = CalderaMCP(
            services={}, config={},
            db_path=os.path.join(tempfile.mkdtemp(), "keys.db"))
        self.key_id, self.token = self.mcp.keystore.issue("tester", "red")

    def _ctx(self, headers):
        return SimpleNamespace(request=SimpleNamespace(headers=headers))

    def test_absent_session_header_falls_back_to_the_bearer_key(self):
        tool_ctx = self.mcp._context_for_request(
            self._ctx({"Authorization": f"Bearer {self.token}"}))
        self.assertEqual(tool_ctx.username, "tester")
        self.assertEqual(tool_ctx.session_id, f"{RUN_KEY_PREFIX}{self.key_id}")

    def test_session_header_is_preferred_when_the_transport_supplies_one(self):
        tool_ctx = self.mcp._context_for_request(self._ctx({
            "Authorization": f"Bearer {self.token}",
            "mcp-session-id": "0123456789abcdef",
        }))
        self.assertEqual(tool_ctx.session_id, "0123456789abcdef")

    def test_unauthenticated_request_gets_no_run_key(self):
        tool_ctx = self.mcp._context_for_request(self._ctx({}))
        self.assertIsNone(tool_ctx.username)
        self.assertIsNone(tool_ctx.session_id)

    def test_events_group_into_one_run_per_key(self):
        store = self.mcp.keystore
        other_id, _other_token = store.issue("other", "red")
        mine = f"{RUN_KEY_PREFIX}{self.key_id}"
        theirs = f"{RUN_KEY_PREFIX}{other_id}"
        store.log_event(session_id=mine, username="tester",
                        tool="delete_adversary", result={})
        store.log_event(session_id=mine, username="tester",
                        tool="delete_ability", result={})
        store.log_event(session_id=theirs, username="other",
                        tool="delete_adversary", result={})

        runs = {run["session_id"]: run["event_count"] for run in store.list_runs()}
        self.assertEqual(runs[mine], 2)
        self.assertEqual(runs[theirs], 1)


if __name__ == "__main__":
    unittest.main()
