import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kerio_vpn import helper, splitroute  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(splitroute.classify("192.0.2.10"), ("net", "192.0.2.10/32"))
        self.assertEqual(splitroute.classify("10.1.2.3/8"), ("net", "10.0.0.0/8"))
        self.assertEqual(splitroute.classify("Example.COM."), ("host", "example.com"))

    def test_rejects(self):
        for bad in ("", "999.1.1.1", "0.0.0.0/0", "::1", "bad host", "a_b", "192.0.2.10; rm"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                splitroute.classify(bad)

    def test_resolve(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("203.0.113.34", 0))]):
            nets, failed = splitroute.resolve(["10.0.0.0/8", "example.com", "10.0.0.0/8", "bad host"])
        self.assertEqual(nets, ["10.0.0.0/8", "203.0.113.34/32"])
        self.assertEqual(failed, [])


class HelperRoutesTest(unittest.TestCase):
    def call(self, payload):
        out = io.StringIO()
        cmds = []

        def fake_run(cmd, stdin=None, timeout=30, check=True):
            cmds.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch("os.geteuid", return_value=0), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("sys.stdout", out), mock.patch.object(helper, "_run", fake_run):
            rc = helper.main("control", ["routes-set"])
        return rc, json.loads(out.getvalue()), cmds

    def test_routes_commands(self):
        rc, reply, cmds = self.call({"exclude": ["198.51.100.8/32"], "include": ["172.20.0.0/16"],
                                     "uplink_gw": "192.0.2.1", "uplink_dev": "eth0",
                                     "iface": "kvnet", "vpn_gw": "10.66.0.1"})
        self.assertEqual(rc, 0, reply)
        self.assertIn(["ip", "-4", "route", "flush", "proto", "233"], cmds)
        self.assertIn(["ip", "-4", "route", "add", "198.51.100.8/32", "via", "192.0.2.1",
                       "dev", "eth0", "proto", "233"], cmds)
        self.assertIn(["ip", "-4", "route", "add", "172.20.0.0/16", "via", "10.66.0.1",
                       "dev", "kvnet", "proto", "233"], cmds)

    def test_routes_validation(self):
        for payload in ({"exclude": ["198.51.100.8 dev lo"]},
                        {"exclude": ["198.51.100.8/32"], "uplink_gw": "x", "uplink_dev": "eth0"},
                        {"exclude": ["198.51.100.8/32"], "uplink_gw": "198.51.100.9", "uplink_dev": "a b"},
                        {"include": ["0.0.0.0/0"], "iface": "kvnet"}):
            with self.subTest(payload=payload):
                rc, reply, _ = self.call(payload)
                self.assertFalse(reply["ok"])

    def test_killswitch_bypass(self):
        rules = helper.build_killswitch_ruleset(["192.0.2.10"], ["kvnet"], False, ["198.51.100.8/32"])
        self.assertIn("ip daddr { 198.51.100.8/32 } accept", rules)


if __name__ == "__main__":
    unittest.main()
