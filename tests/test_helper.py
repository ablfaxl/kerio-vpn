import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kerio_vpn import helper, kvc  # noqa: E402

ARGS = {"server": "vpn.example.com", "port": 4090, "username": "a.user", "password": "pw",
        "fingerprint": "0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0", "tag": "t1"}


class HelperTest(unittest.TestCase):
    def run_main(self, level, action, payload):
        out = io.StringIO()
        with mock.patch("os.geteuid", return_value=0), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("sys.stdout", out):
            rc = helper.main(level, [action])
        return rc, json.loads(out.getvalue())

    def test_apply_writes_config_and_state(self):
        with tempfile.TemporaryDirectory() as d:
            conf, state = os.path.join(d, "kerio-kvc.conf"), os.path.join(d, "state")
            calls = []
            with mock.patch.object(kvc, "CONFIG_PATH", conf), \
                    mock.patch.object(helper, "STATE_DIR", state), \
                    mock.patch.object(helper, "APPLIED_FILE", state + "/applied.json"), \
                    mock.patch.object(helper, "_service", calls.append), \
                    mock.patch.object(helper, "_is_active", return_value=False):
                rc, reply = self.run_main("configure", "apply", ARGS)
                self.assertEqual(rc, 0, reply)
                self.assertEqual(calls, ["start"])
                self.assertEqual(os.stat(conf).st_mode & 0o777, 0o600)
                self.assertEqual(kvc.parse_config(open(conf).read()).password, "pw")
                applied = json.load(open(state + "/applied.json"))
                self.assertEqual(applied["tag"], "t1")
                self.assertEqual(applied["config"]["size"], os.stat(conf).st_size)
                # a second apply keeps the original backup untouched
                rc, _ = self.run_main("configure", "apply", dict(ARGS, password="pw2"))
                self.assertEqual(kvc.parse_config(open(conf + ".kerio-vpn.orig").read()).password, "pw")

    def test_apply_rejects_invalid(self):
        with mock.patch.object(helper, "_write_atomic") as w:
            rc, reply = self.run_main("configure", "apply", dict(ARGS, server="a b"))
        self.assertEqual(rc, 1)
        self.assertFalse(reply["ok"])
        w.assert_not_called()

    def test_control_cannot_configure(self):
        for action in ("apply", "read-config", "boot"):
            rc, reply = self.run_main("control", action, {})
            self.assertEqual(rc, 2)

    def test_requires_root(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("os.geteuid", return_value=1000):
            self.assertEqual(helper.main("control", ["status"]), 2)

    def test_bad_json(self):
        out = io.StringIO()
        with mock.patch("os.geteuid", return_value=0), mock.patch("sys.stdout", out), \
                mock.patch("sys.stdin", io.StringIO("[1,2]")):
            self.assertEqual(helper.main("control", ["stop"]), 2)

    def test_killswitch_rules(self):
        rules = helper.build_killswitch_ruleset(["192.0.2.10", "2001:db8::1"], ["kvnet"], False)
        self.assertIn("ip daddr { 192.0.2.10 } accept", rules)
        self.assertIn("ip6 daddr { 2001:db8::1 } accept", rules)
        self.assertNotIn("192.168.0.0/16", rules)
        self.assertTrue(rules.rstrip().endswith("}"))
        with self.assertRaises(ValueError):
            helper.build_killswitch_ruleset(["192.0.2.10 }"], [], True)
        with self.assertRaises(helper.HelperError):
            helper.build_killswitch_ruleset(["192.0.2.10"], ['x" accept'], True)


if __name__ == "__main__":
    unittest.main()
