import os
import tempfile
import unittest
from unittest import mock

from kerio_vpn import macos


class MacOSIntegrationTests(unittest.TestCase):
    def test_reads_native_connections_without_password(self):
        xml = """<?xml version="1.0"?>
        <config><connections><connection type="user">
          <description>Office</description><server>vpn.example.com</server>
          <username>alice</username><password>D3S:secret</password>
          <persistent>1</persistent>
        </connection></connections></config>"""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(xml)
            path = f.name
        try:
            items = macos.read_connections(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Office")
        self.assertEqual(items[0].server, "vpn.example.com")
        self.assertTrue(items[0].persistent)
        self.assertFalse(hasattr(items[0], "password"))

    def test_malformed_config_is_safe(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("<broken")
            path = f.name
        try:
            self.assertEqual(macos.read_connections(path), [])
        finally:
            os.unlink(path)

    @mock.patch("kerio_vpn.macos.subprocess.run")
    @mock.patch("kerio_vpn.macos.os.path.exists", return_value=True)
    def test_open_client_uses_open(self, _exists, run):
        macos.open_client()
        self.assertEqual(run.call_args.args[0][0], "open")


if __name__ == "__main__":
    unittest.main()
