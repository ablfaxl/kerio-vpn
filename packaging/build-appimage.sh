#!/bin/sh
# Build dist/kerio-vpn-<version>-x86_64.AppImage.
#
# The AppImage uses the host's python3 and GTK 3 (PyGObject), like the .deb does.
# It cannot install a polkit policy, so privileged actions always ask for the
# administrator password; the .deb remains the recommended install.
#
# Requires appimagetool in PATH (or APPIMAGETOOL=/path/to/appimagetool).
set -eu
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import kerio_vpn; print(kerio_vpn.VERSION)")
APPDIR=build/appimage/KerioVPN.AppDir
TOOL=${APPIMAGETOOL:-appimagetool}
rm -rf build/appimage
make install DESTDIR="$APPDIR" PREFIX=/usr >/dev/null
find "$APPDIR" -name __pycache__ -type d -exec rm -rf {} +
# Icons are looked up next to the package when it is not installed system-wide.
mkdir -p "$APPDIR/usr/lib/kerio-vpn/data"
cp -r data/icons "$APPDIR/usr/lib/kerio-vpn/data/"

cp data/kerio-vpn.desktop "$APPDIR/kerio-vpn.desktop"
cp data/icons/kerio-vpn.svg "$APPDIR/kerio-vpn.svg"
ln -sf kerio-vpn.svg "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
if ! command -v python3 >/dev/null 2>&1 || \
   ! python3 -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null; then
    msg="Kerio VPN needs python3 and GTK 3 (PyGObject):
  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
    command -v zenity >/dev/null 2>&1 && zenity --error --text="$msg" 2>/dev/null
    echo "$msg" >&2
    exit 1
fi
exec python3 "$HERE/usr/lib/kerio-vpn/bin/kerio-vpn" "$@"
APPRUN
chmod 755 "$APPDIR/AppRun"

mkdir -p dist
ARCH=x86_64 "$TOOL" --no-appstream "$APPDIR" "dist/kerio-vpn-${VERSION}-x86_64.AppImage" >/dev/null
echo "dist/kerio-vpn-${VERSION}-x86_64.AppImage"
