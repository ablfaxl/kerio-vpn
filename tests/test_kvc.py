import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kerio_vpn import kvc  # noqa: E402


def shell_xor(password: str) -> str:
    """The exact loop from kerio-control-vpnclient's postinst."""
    script = ('XOR=""; for i in `printf %s "$1" | od -t d1 -A n`; do '
              'XOR=$(printf "%s%02x" "$XOR" $((i ^ 85))); done; printf %s "$XOR"')
    return subprocess.check_output(["sh", "-c", script, "sh", password]).decode()


class XorTest(unittest.TestCase):
    def test_matches_official_postinst(self):
        for pw in ("secret", "P@ss w0rd!", "a&b<c>\"'", "1234567890" * 5):
            self.assertEqual(kvc.xor_encode(pw), "XOR:" + shell_xor(pw))

    def test_roundtrip_unicode(self):
        for pw in ("secret", "pässwörd", "naïve€"):
            self.assertEqual(kvc.xor_decode(kvc.xor_encode(pw)), pw)

    def test_plain_and_broken(self):
        self.assertEqual(kvc.xor_decode("plain"), "plain")
        self.assertEqual(kvc.xor_decode("XOR:zz"), "")


class ConfigTest(unittest.TestCase):
    cfg = kvc.KvcConfig(server="vpn.example.com", port=4090, username="a.user",
                        password="s3cr&t<", fingerprint="0f:1e:2d:3c:4b:5a:69:78:87:96:a5:b4:c3:d2:e1:f0")

    def test_render_matches_wizard_layout(self):
        text = kvc.render_config(self.cfg)
        self.assertTrue(text.startswith('<config>\n  <connections>\n    <connection type="persistent">\n'))
        self.assertIn("<fingerprint>0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0</fingerprint>", text)
        self.assertIn("<active>1</active>", text)

    def test_roundtrip(self):
        parsed = kvc.parse_config(kvc.render_config(self.cfg))
        self.assertEqual(parsed.server, "vpn.example.com")
        self.assertEqual(parsed.password, "s3cr&t<")
        self.assertEqual(parsed.username, "a.user")

    def test_xml_injection_is_escaped(self):
        cfg = kvc.KvcConfig(**dict(vars(self.cfg), username="x</username><server>evil"))
        parsed = kvc.parse_config(kvc.render_config(cfg))
        self.assertEqual(parsed.server, "vpn.example.com")
        self.assertEqual(parsed.username, "x</username><server>evil")

    def test_validation(self):
        bad = [dict(server="bad host"), dict(server=""), dict(port=0), dict(port="x"),
               dict(username=""), dict(username="a\nb"), dict(password=""),
               dict(fingerprint="12:34")]
        for change in bad:
            with self.subTest(change=change):
                with self.assertRaises(kvc.ValidationError):
                    kvc.render_config(kvc.KvcConfig(**dict(vars(self.cfg), **change)))

    def test_hosts(self):
        for ok in ("vpn.example.com", "192.0.2.1", "2001:db8::1", "host-1"):
            kvc.validate_host(ok)

    def test_split_server(self):
        self.assertEqual(kvc.split_server("a.b:4091"), ("a.b", 4091))
        self.assertEqual(kvc.split_server("a.b"), ("a.b", 4090))
        self.assertEqual(kvc.split_server("[2001:db8::1]:5000"), ("2001:db8::1", 5000))

    def test_fingerprint_normalization(self):
        self.assertEqual(kvc.normalize_fingerprint("0f1e2d 3c4b5a69788796a5b4c3d2e1f0"),
                         "0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0")


if __name__ == "__main__":
    unittest.main()
