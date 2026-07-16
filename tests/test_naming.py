"""Tests for the deterministic naming helper. Run from the Caldera root:

    /home/sam/.calderavenv/bin/python3 -m unittest discover -s plugins/claudera/tests
"""

import unittest

from plugins.claudera.app import naming


class TestNaming(unittest.TestCase):
    def test_ability_name(self):
        self.assertEqual(
            naming.ability_name("1059.001", "PowerShell Download Cradle!!"),
            "T1059.001_powershell_download_cradle",
        )
        self.assertEqual(naming.ability_name("T1053", "scheduled task"), "T1053_scheduled_task")

    def test_normalize_technique_id(self):
        self.assertEqual(naming.normalize_technique_id("t1059.001"), "T1059.001")
        self.assertEqual(naming.normalize_technique_id("1082"), "T1082")
        with self.assertRaises(ValueError):
            naming.normalize_technique_id("nope")
        with self.assertRaises(ValueError):
            naming.normalize_technique_id("T10590")  # 5 digits

    def test_adversary_name(self):
        self.assertEqual(naming.adversary_name("Hyadina", "ransomware chain"), "hyadina_ransomware_chain")

    def test_operation_name_shape(self):
        name = naming.operation_name("hyadina_ransomware_chain", "red")
        self.assertRegex(name, r"^op_hyadina_ransomware_chain_red_\d{8}-\d{4}$")

    def test_deduplicate(self):
        self.assertEqual(naming.deduplicate("x", []), "x")
        self.assertEqual(naming.deduplicate("x", ["x"]), "x_2")
        self.assertEqual(naming.deduplicate("x", ["x", "x_2"]), "x_3")


if __name__ == "__main__":
    unittest.main()
