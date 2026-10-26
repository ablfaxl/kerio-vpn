import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kerio_vpn import logparse as lp  # noqa: E402

SESSION = """\
[01/Jan/2026 10:55:46] {info} Kerio Control VPN Client Service 9.6.1 patch 1 build 9306 started.
[01/Jan/2026 10:55:46] {vpnCore} VPN driver opened, version = 2.1, ifIndex = 7 (0x7), MAC 02-00-00-00-00-01
[01/Jan/2026 10:55:46] {engine} Connect(User: a.user, Server vpn.example.com, id[0001]).
[01/Jan/2026 10:55:46] {vpnClient} VPNClient[0001] - server name resolved - 203.0.113.10
[01/Jan/2026 10:55:46] {vpnClient} VPNClient[0001] - SSL connection successfully established
[01/Jan/2026 10:55:48] {vpnClient} VPNClient[0001] - received R_IPCONFIG V3 message, IP = 10.66.0.19/255.255.255.0, DNS = 127.0.0.1, 0.0.0.0 'corp.local', WINS = 0.0.0.0, 0.0.0.0, flags = 01, CEP = 3600 s.
[01/Jan/2026 10:55:48] {vpnCore} Creating new VPN connection: local IP 10.66.0.19/255.255.255.0, DNS 10.66.0.1, 0.0.0.0
[01/Jan/2026 10:55:48] {engine} Callback StatusChanged called from libVpn(connected).
[01/Jan/2026 10:55:48] {vpnClient} VPNClient[0001] - received ROUTES message
[01/Jan/2026 10:55:48] {vpnCore} Route 10.67.0.0/255.255.0.0 gw 10.66.0.1 -> 10.66.0.19:7 added
[01/Jan/2026 10:55:48] {vpnClient} VPNClient[0001] - received ROUTES with default route flag
[01/Jan/2026 10:55:53] {vpnCore} IP packet 10.66.0.19 -> 198.51.100.7 handled.
"""

AUTH_FAIL = """\
[01/Jan/2026 10:50:07] {info} Kerio Control VPN Client Service 9.6.1 patch 1 build 9306 started.
[01/Jan/2026 10:50:07] {engine} Connect(User: a.user, Server vpn.example.com, id[0001]).
[01/Jan/2026 10:50:08] {engine} Callback StatusChanged called from libVpn(error 161).
[01/Jan/2026 10:50:41] {engine} Connect(User: a.user, Server vpn.example.com, id[0001]).
[01/Jan/2026 10:50:41] {engine} Callback StatusChanged called from libVpn(error 161).
"""


def feed(text):
    t = lp.StateTracker()
    t.feed_many(lp.parse_line(l) for l in text.splitlines())
    return t.info


class TrackerTest(unittest.TestCase):
    def test_connected_session(self):
        info = feed(SESSION)
        self.assertEqual(info.phase, lp.CONNECTED)
        self.assertEqual(info.server, "vpn.example.com")
        self.assertEqual(info.server_ip, "203.0.113.10")
        self.assertEqual(info.local_ip, "10.66.0.19")
        self.assertEqual(info.dns, ["10.66.0.1"])
        self.assertEqual(info.domain, "corp.local")
        self.assertEqual(info.if_index, 7)
        self.assertTrue(info.is_full_tunnel)
        self.assertEqual([str(r) for r in info.routes], ["10.67.0.0/16"])
        self.assertIsNotNone(info.connected_since)

    def test_auth_failure_counting(self):
        info = feed(AUTH_FAIL)
        self.assertEqual(info.phase, lp.RECONNECTING)
        self.assertEqual(info.last_error_code, 161)
        self.assertEqual(info.consecutive_errors, 2)

    def test_disconnect_and_stop(self):
        info = feed(SESSION + "[01/Jan/2026 10:55:55] {engine} VpnFSM: Sending status to Engine (disconnecting).\n"
                    "[01/Jan/2026 10:55:55] {engine} Callback StatusChanged called from libVpn(disconnected).\n")
        self.assertEqual(info.phase, lp.DISCONNECTING)
        info = feed(SESSION + "[01/Jan/2026 10:55:55] {info} Kerio Control VPN Client Service 9.6.1 patch 1 build 9306 stopped.\n")
        self.assertEqual(info.phase, lp.STOPPED)

    def test_unexpected_drop_then_reconnect(self):
        info = feed(SESSION + "[01/Jan/2026 10:00:00] {engine} Callback StatusChanged called from libVpn(error 146).\n")
        self.assertEqual(info.phase, lp.RECONNECTING)
        self.assertIsNone(info.connected_since)
        info = feed(SESSION + "[01/Jan/2026 10:00:00] {engine} Callback StatusChanged called from libVpn(error 146).\n"
                    "[01/Jan/2026 10:00:05] {engine} Callback StatusChanged called from libVpn(connected).\n")
        self.assertEqual(info.phase, lp.CONNECTED)
        self.assertEqual(info.consecutive_errors, 0)

    def test_noise_and_garbage(self):
        self.assertTrue(lp.parse_line("[01/Jan/2026 10:55:53] {vpnCore} IP packet 192.0.2.20 -> 198.51.100.20 handled.").noisy)
        line = lp.parse_line("garbage without timestamp")
        self.assertIsNone(line.ts)
        self.assertFalse(lp.StateTracker().feed(line))

    def test_error_log(self):
        e = lp.parse_error_line("[01/Jan/2026 10:50:41] libVPN: Authentication failed(161)")
        self.assertEqual((e.code, e.text), (161, "Authentication failed"))

    def test_macos_rpc_status(self):
        info = feed(
            '[01/Jan/2026 10:55:46] {vpnRpc} TinyDB RPC Client received notification packet '
            '(select connect("vpn.example.com", "alice", "********", 0)).\n'
            '[01/Jan/2026 10:55:47] {vpnRpc} TinyDB RPC Client received status packet '
            '(connecting, err: 0).\n'
            '[01/Jan/2026 10:55:48] {vpnRpc} TinyDB RPC Client received status packet '
            '(connected, err: 0).\n')
        self.assertEqual(info.phase, lp.CONNECTED)
        self.assertEqual(info.server, "vpn.example.com")
        self.assertEqual(info.username, "alice")
        self.assertIsNotNone(info.connected_since)


class LogTailTest(unittest.TestCase):
    def test_follow_truncate_rotate(self):
        from kerio_vpn.logtail import LogTail
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "debug.log")
            with open(path, "w") as f:
                f.write("a\nb\n")
            tail = LogTail(path)
            self.assertEqual(tail.initial(1024), ["a", "b"])
            with open(path, "a") as f:
                f.write("c\npart")
            self.assertEqual(tail.read_new(), ["c"])
            with open(path, "a") as f:
                f.write("ial\n")
            self.assertEqual(tail.read_new(), ["partial"])
            os.rename(path, path + ".1")
            with open(path, "w") as f:
                f.write("new\n")
            self.assertEqual(tail.read_new(), ["new"])
            with open(path, "w") as f:
                f.write("x\n")
            self.assertEqual(tail.read_new(), ["x"])


if __name__ == "__main__":
    unittest.main()
