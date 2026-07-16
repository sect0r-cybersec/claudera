"""Tests for payload allow-list classification, local search, and hash verification
(including a deliberate mismatch)."""

import os
import tempfile
import unittest

from plugins.claudera.app import payloads as payloadsvc
from plugins.claudera.app.store import KeyStore
from plugins.claudera.app.tools import ToolContext
from plugins.claudera.app.tools.payloads import _download_payload, _find_payload

ALLOW = [{"name": "atomic-red-team", "host": "raw.githubusercontent.com",
          "path_prefix": "/redcanaryco/atomic-red-team/"}]
CFG = {"payloads": {"download_dir": "payloads/downloaded", "max_download_bytes": 1_000_000,
                    "allow_list": ALLOW}}
ARTURL = "https://raw.githubusercontent.com/redcanaryco/atomic-red-team/master/LICENSE.txt"


class _FakeDataSvc:
    async def locate(self, kind, match=None):
        return []


class TestClassify(unittest.TestCase):
    def test_allow_list(self):
        al = payloadsvc.load_allow_list({"allow_list": ALLOW})
        self.assertEqual(payloadsvc.classify_url(ARTURL, al), "atomic-red-team")
        self.assertIsNone(payloadsvc.classify_url("https://evil.example.com/x.exe", al))
        self.assertIsNone(payloadsvc.classify_url("ftp://host/x", al))


class TestLocalSearch(unittest.IsolatedAsyncioTestCase):
    async def test_search_local_hashes_files(self):
        d = tempfile.mkdtemp()
        pdir = os.path.join(d, "payloads")
        os.makedirs(pdir)
        with open(os.path.join(pdir, "mimikatz.exe"), "wb") as f:
            f.write(b"payload-bytes")

        class DS:
            async def locate(self, kind, match=None):
                return [type("P", (), {"name": "x", "enabled": True})()] if kind == "plugins" else []

        # point the search at our temp dir by monkeypatching _payload_dirs
        orig = payloadsvc._payload_dirs

        async def fake_dirs(services):
            return [pdir]

        payloadsvc._payload_dirs = fake_dirs
        try:
            hits = await payloadsvc.search_local({"data_svc": DS()}, "mimi")
        finally:
            payloadsvc._payload_dirs = orig
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["name"], "mimikatz.exe")
        self.assertEqual(len(hits[0]["sha256"]), 64)
        self.assertFalse(hits[0]["requires_confirmation"])


class TestDownload(unittest.IsolatedAsyncioTestCase):
    def _ctx(self):
        d = tempfile.mkdtemp()
        return ToolContext(services={"data_svc": _FakeDataSvc()}, username="red", group="red",
                           config=CFG, plugin_dir=d, store=KeyStore(os.path.join(d, "db.sqlite")))

    async def test_off_list_requires_confirmation(self):
        ctx = self._ctx()
        r = await _download_payload(ctx, {"url": "https://evil.example.com/x.exe"})
        self.assertEqual(r["status"], "requires_confirmation")

    async def test_hash_mismatch_deletes_and_logs(self):
        ctx = self._ctx()
        orig = payloadsvc.fetch_and_store

        async def fake_fetch(url, dest_dir, max_bytes):
            os.makedirs(dest_dir, exist_ok=True)
            p = os.path.join(dest_dir, payloadsvc.safe_filename(url))
            with open(p, "wb") as f:
                f.write(b"data")
            return p, "aaaa1111", 4

        payloadsvc.fetch_and_store = fake_fetch
        try:
            bad = await _download_payload(ctx, {"url": ARTURL, "expected_sha256": "deadbeef"})
            self.assertEqual(bad["status"], "hash_mismatch")
            dest = os.path.join(ctx.plugin_dir, "payloads/downloaded", "LICENSE.txt")
            self.assertFalse(os.path.exists(dest))  # deleted on mismatch

            ok = await _download_payload(ctx, {"url": ARTURL, "expected_sha256": "AAAA1111"})
            self.assertEqual(ok["status"], "downloaded")
            self.assertEqual(ok["sha256"], "aaaa1111")
        finally:
            payloadsvc.fetch_and_store = orig

        statuses = {d["status"] for d in ctx.store.list_downloads()}
        self.assertEqual(statuses, {"hash_mismatch", "ok"})


class TestFindPayload(unittest.IsolatedAsyncioTestCase):
    async def test_find_classifies_url(self):
        d = tempfile.mkdtemp()
        ctx = ToolContext(services={"data_svc": _FakeDataSvc()}, config=CFG, plugin_dir=d)
        out = await _find_payload(ctx, {"url": "https://evil.example.com/x"})
        self.assertTrue(out["remote"][0]["requires_confirmation"])
        self.assertIn("atomic-red-team", [s["name"] for s in out["trusted_sources"]])


if __name__ == "__main__":
    unittest.main()
