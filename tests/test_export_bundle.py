"""Tests for the export bundle tools (adversary+abilities zip, flat abilities zip).

Run from the Caldera root:

    /home/sam/.calderavenv/bin/python3 -m unittest discover -s plugins/claudera/tests
"""

import asyncio
import base64
import io
import os
import tempfile
import unittest
import zipfile

from plugins.claudera.app.tools import ToolContext
from plugins.claudera.app.tools.operations import (
    _export_abilities_bundle,
    _export_adversary_bundle,
    _safe_filename,
)


class _Ability:
    def __init__(self, ability_id, name):
        self.ability_id = ability_id
        self.name = name
        self.access = None  # visible to any group
        self.display = {"ability_id": ability_id, "name": name}


class _Adversary:
    def __init__(self, adversary_id, name, ordering):
        self.adversary_id = adversary_id
        self.name = name
        self.atomic_ordering = ordering
        self.access = None
        self.display = {"adversary_id": adversary_id, "name": name, "atomic_ordering": ordering}


class _FakeDataSvc:
    def __init__(self, adversaries=None, abilities=None):
        self._store = {"adversaries": adversaries or [], "abilities": abilities or []}

    async def locate(self, ram_key, match=None):
        rows = self._store.get(ram_key, [])
        if not match:
            return list(rows)
        key, val = next(iter(match.items()))
        return [o for o in rows if getattr(o, key, None) == val]


class _FakeFileSvc:
    """Serves on-disk YAML from a temp dir keyed by ``<id>.yml`` if present."""

    def __init__(self, root):
        self.root = root

    async def find_file_path(self, name, location="data"):
        path = os.path.join(self.root, name)
        return (name, path if os.path.exists(path) else None)


def _ctx(root, adversaries=None, abilities=None):
    return ToolContext(
        services={"data_svc": _FakeDataSvc(adversaries, abilities),
                  "file_svc": _FakeFileSvc(root)},
        username="red", group="red",
    )


def _read_zip(b64):
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


class TestExportBundle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # On-disk YAML for one ability, to prove byte-for-byte passthrough.
        self.disk_yaml = "- id: a1\n  name: T1688_arm_bcd\n  # kept verbatim\n"
        with open(os.path.join(self.dir, "a1.yml"), "w", encoding="utf-8") as fh:
            fh.write(self.disk_yaml)

    def test_adversary_bundle_layout_and_naming(self):
        abilities = [
            _Ability("a1", "T1688_arm_bcd_safeboot_network_no_reboot"),
            _Ability("a2", "T1057_process_discovery"),
        ]
        adv = _Adversary("adv1", "hyadina_ransomware_chain", ["a1", "a2"])
        ctx = _ctx(self.dir, [adv], abilities)

        res = asyncio.run(_export_adversary_bundle(ctx, {"adversary_id": "adv1"}))

        self.assertEqual(res["format"], "zip")
        self.assertEqual(res["filename"], "hyadina_ransomware_chain.zip")
        self.assertEqual(res["ability_count"], 2)
        self.assertNotIn("abilities_missing", res)

        members = _read_zip(res["content_base64"])
        self.assertEqual(set(members), {
            "hyadina_ransomware_chain.yml",
            "abilities/T1688_arm_bcd_safeboot_network_no_reboot.yml",
            "abilities/T1057_process_discovery.yml",
        })
        # On-disk YAML passes through byte-for-byte.
        self.assertEqual(members["abilities/T1688_arm_bcd_safeboot_network_no_reboot.yml"], self.disk_yaml)
        # Tree lists every member and the archive name.
        self.assertIn("hyadina_ransomware_chain.zip", res["tree"])
        self.assertIn("abilities/T1057_process_discovery.yml", res["tree"])

    def test_adversary_bundle_reports_missing_abilities(self):
        adv = _Adversary("adv1", "chain", ["a1", "ghost"])
        ctx = _ctx(self.dir, [adv], [_Ability("a1", "keep")])
        res = asyncio.run(_export_adversary_bundle(ctx, {"adversary_id": "adv1"}))
        self.assertEqual(res["ability_count"], 1)
        self.assertEqual(res["abilities_missing"], ["ghost"])

    def test_abilities_bundle_is_flat(self):
        abilities = [_Ability("a1", "keep_one"), _Ability("a2", "keep_two")]
        ctx = _ctx(self.dir, [], abilities)
        res = asyncio.run(_export_abilities_bundle(
            ctx, {"ability_ids": ["a1", "a2"], "archive_name": "my picks!"}))
        members = _read_zip(res["content_base64"])
        self.assertEqual(set(members), {"keep_one.yml", "keep_two.yml"})
        self.assertEqual(res["filename"], "my_picks.zip")

    def test_collision_disambiguated_by_id(self):
        abilities = [_Ability("aaaabbbb1111", "same"), _Ability("ccccdddd2222", "same")]
        ctx = _ctx(self.dir, [], abilities)
        res = asyncio.run(_export_abilities_bundle(ctx, {"ability_ids": ["aaaabbbb1111", "ccccdddd2222"]}))
        members = _read_zip(res["content_base64"])
        self.assertEqual(set(members), {"same.yml", "same_ccccdddd.yml"})

    def test_empty_abilities_bundle_raises(self):
        ctx = _ctx(self.dir, [], [])
        with self.assertRaises(ValueError):
            asyncio.run(_export_abilities_bundle(ctx, {"ability_ids": ["nope"]}))

    def test_safe_filename(self):
        self.assertEqual(_safe_filename("a/b c:d", "fb"), "a_b_c_d")
        self.assertEqual(_safe_filename("   ", "fallback"), "fallback")
        self.assertEqual(_safe_filename("T1688_arm_bcd", "fb"), "T1688_arm_bcd")


if __name__ == "__main__":
    unittest.main()
