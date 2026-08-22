"""Tests for the key store, auth resolution, and run/download logs."""

import os
import tempfile
import unittest

from plugins.claudera.app import auth
from plugins.claudera.app.store import KeyStore


class _Headers(dict):
    """Minimal case-insensitive-ish headers stand-in with .get()."""


class TestKeyStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = KeyStore(os.path.join(self.dir, "claudera.db"))

    def test_issue_and_validate(self):
        key_id, token = self.store.issue("red", "red")
        rec = self.store.validate(token)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.username, "red")
        self.assertEqual(rec.group, "red")
        self.assertEqual(rec.key_id, key_id)
        # last_used_at recorded
        self.assertIsNotNone(self.store.get(key_id).last_used_at)

    def test_invalid_key_rejected(self):
        self.store.issue("red", "red")
        self.assertIsNone(self.store.validate("cald_deadbeef.nope"))
        self.assertIsNone(self.store.validate("not-even-a-token"))
        self.assertIsNone(self.store.validate(""))

    def test_revoke_is_terminal(self):
        key_id, token = self.store.issue("red", "red")
        self.assertIsNotNone(self.store.validate(token))
        self.assertTrue(self.store.revoke(key_id))
        self.assertIsNone(self.store.validate(token))
        # Revocation is permanent: there is no reactivation path, and there is
        # no rotate path that could bring a key back to life.
        self.assertFalse(hasattr(self.store, "set_active"))
        self.assertFalse(hasattr(self.store, "rotate"))
        self.assertFalse(self.store.get(key_id).active)

    def test_delete_removes_key(self):
        key_id, token = self.store.issue("red", "red")
        self.assertTrue(self.store.delete(key_id))
        self.assertIsNone(self.store.get(key_id))
        self.assertIsNone(self.store.validate(token))
        # Deleting a missing key is a no-op that reports False.
        self.assertFalse(self.store.delete(key_id))

    def test_delete_of_active_key_revokes_first(self):
        # Deleting an active key must disable it as part of the same operation,
        # so a deleted key can never authenticate even mid-flight.
        key_id, token = self.store.issue("red", "red")
        self.assertTrue(self.store.get(key_id).active)
        self.assertTrue(self.store.delete(key_id))
        self.assertIsNone(self.store.validate(token))
        self.assertIsNone(self.store.get(key_id))

    def test_download_and_event_logs(self):
        self.store.log_download(username="red", source="atomic-red-team",
                                url="https://x/y", sha256="abc", size=10,
                                dest_path="/tmp/y", status="ok")
        downloads = self.store.list_downloads()
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]["status"], "ok")

        self.store.log_event(session_id="s1", username="red", tool="create_ability",
                             result={"ability_id": "a1", "name": "T1059_x", "status": "created"})
        events = self.store.list_events()
        self.assertEqual(events[0]["artefact_type"], "ability")
        self.assertEqual(events[0]["artefact_name"], "T1059_x")
        runs = self.store.list_runs()
        self.assertEqual(runs[0]["session_id"], "s1")
        self.assertEqual(runs[0]["event_count"], 1)


class TestAuthResolution(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = KeyStore(os.path.join(self.dir, "claudera.db"))

    def test_extract_bearer(self):
        self.assertEqual(auth.extract_bearer(_Headers({"Authorization": "Bearer abc"})), "abc")
        self.assertEqual(auth.extract_bearer(_Headers({"authorization": "bearer xyz"})), "xyz")
        self.assertIsNone(auth.extract_bearer(_Headers({"Authorization": "Basic abc"})))
        self.assertIsNone(auth.extract_bearer(_Headers({})))

    def test_resolve_identity(self):
        _, token = self.store.issue("blue", "blue")
        ident = auth.resolve_identity(self.store, _Headers({"Authorization": f"Bearer {token}"}))
        self.assertIsNotNone(ident)
        self.assertEqual((ident.username, ident.group), ("blue", "blue"))
        # bad + missing
        self.assertIsNone(auth.resolve_identity(self.store, _Headers({"Authorization": "Bearer bad"})))
        self.assertIsNone(auth.resolve_identity(self.store, _Headers({})))


if __name__ == "__main__":
    unittest.main()
