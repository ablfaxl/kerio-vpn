#!/bin/sh
# Build dist/kerio-vpn_<version>_all.deb without debhelper.
set -eu
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import kerio_vpn; print(kerio_vpn.VERSION)")
PKG=kerio-vpn
ROOT=build/deb/${PKG}_${VERSION}_all
rm -rf "$ROOT"
make install DESTDIR="$ROOT" PREFIX=/usr >/dev/null
find "$ROOT" -name __pycache__ -type d -exec rm -rf {} +

install -d "$ROOT/DEBIAN" "$ROOT/usr/share/doc/$PKG"
install -m 644 README.md "$ROOT/usr/share/doc/$PKG/README.md"
install -m 644 packaging/copyright "$ROOT/usr/share/doc/$PKG/copyright"
SIZE=$(du -sk "$ROOT" | cut -f1)

cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Maintainer: Kerio VPN contributors <maintainers@kerio-vpn.invalid>
Installed-Size: $SIZE
Depends: python3 (>= 3.8), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, pkexec | policykit-1, iproute2
Recommends: kerio-control-vpnclient, gir1.2-ayatanaappindicator3-0.1 | gir1.2-appindicator3-0.1, gir1.2-notify-0.7, gir1.2-secret-1, nftables, openssl, iputils-ping
Suggests: gnome-shell-extension-appindicator
Conflicts: kerio-vpn-panel
Replaces: kerio-vpn-panel
Breaks: kerio-vpn-panel
Homepage: https://github.com/liimitedinfinity/kerio-vpn
Description: Desktop GUI and CLI for the Kerio Control VPN Client on Linux
 Kerio VPN is a desktop client for the official Kerio Control VPN
 Client for Linux (kvpncsvc), which only ships a command line wizard.
 .
 It manages several connection profiles with passwords in the desktop
 keyring, shows live status, traffic, routes and logs, verifies the server
 certificate fingerprint, stops retrying after failed logins, and offers
 split tunneling (bypass or force destinations), a kill switch, DNS
 integration with systemd-resolved, a tray icon and a CLI.
 .
 This is an unofficial tool, not affiliated with Kerio or GFI Software.
CONTROL

cat > "$ROOT/DEBIAN/postinst" <<'SCRIPT'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
    command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
fi
exit 0
SCRIPT

cat > "$ROOT/DEBIAN/prerm" <<'SCRIPT'
#!/bin/sh
set -e
# Never leave the machine without internet because of our firewall table.
if command -v nft >/dev/null; then
    for t in kerio_vpn kerio_vpn_panel; do
        nft list table inet $t >/dev/null 2>&1 && nft delete table inet $t || true
    done
fi
ip -4 route flush proto 233 2>/dev/null || true
exit 0
SCRIPT

cat > "$ROOT/DEBIAN/postrm" <<'SCRIPT'
#!/bin/sh
set -e
if [ "$1" = "purge" ]; then
    rm -rf /var/lib/kerio-vpn /var/lib/kerio-vpn-panel
fi
exit 0
SCRIPT
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postrm"

mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "dist/${PKG}_${VERSION}_all.deb" >/dev/null
echo "dist/${PKG}_${VERSION}_all.deb"
