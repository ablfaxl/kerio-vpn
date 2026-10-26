"""`kerio-vpn` command line interface (works over SSH and in scripts)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time

from . import VERSION, certs, kvc, logparse, privileged, system
from .profiles import Profile, ProfileStore, Settings

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _color(text: str, color: str) -> str:
    return color + text + RESET if sys.stdout.isatty() else text


def _session_info():
    tail = logparse.StateTracker()
    try:
        with open(kvc.DEBUG_LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4 * 1024 * 1024))
            lines = [logparse.parse_line(l.decode("utf-8", "replace")) for l in f]
    except OSError:
        lines = []
    start = max((i for i, l in enumerate(lines) if logparse.P_STARTED.search(l.message)),
                default=0)
    tail.feed_many(lines[start:])
    return tail.info


def cmd_status(args) -> int:
    st = system.service_state()
    info = _session_info()
    if not st.installed:
        state = logparse.NOT_INSTALLED
    elif not st.running:
        state = logparse.STOPPED
    elif info.phase == logparse.STOPPED:
        state = logparse.CONNECTING
    else:
        state = info.phase
    iface = system.guess_vpn_interface(info.if_index) if st.running else None
    data = {
        "state": state, "service": st.active, "enabled": st.enabled,
        "server": info.server, "server_ip": info.server_ip, "username": info.username,
        "vpn_ip": info.local_ip if state == logparse.CONNECTED else "",
        "dns": info.dns, "domain": info.domain, "full_tunnel": info.is_full_tunnel,
        "interface": iface, "connected_since": info.connected_since,
        "last_error": info.last_error_code, "error_count": info.consecutive_errors,
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0 if state == logparse.CONNECTED else 3
    color = {logparse.CONNECTED: GREEN, logparse.RECONNECTING: YELLOW,
             logparse.STOPPED: DIM}.get(state, YELLOW)
    print(_color("● " + state.upper(), color))
    if not st.installed:
        print("  kerio-control-vpnclient is not installed")
        return 4
    rows = [("Service", "%s (%s at boot)" % (st.active, st.enabled))]
    if info.server:
        rows.append(("Server", "%s %s" % (info.server, "(%s)" % info.server_ip
                                          if info.server_ip != info.server else "")))
        rows.append(("User", info.username))
    if state == logparse.CONNECTED:
        rows.append(("VPN IP", "%s/%s" % (info.local_ip, info.netmask)))
        rows.append(("DNS", "%s %s" % (", ".join(info.dns), info.domain)))
        rows.append(("Routing", "full tunnel" if info.is_full_tunnel else "split tunnel"))
        if info.connected_since:
            rows.append(("Uptime", time.strftime("%H:%M:%S", time.gmtime(
                time.time() - info.connected_since))))
        if iface:
            c = system.interface_counters(iface) or (0, 0)
            rows.append(("Interface", "%s rx %d B, tx %d B" % (iface, c[0], c[1])))
    if info.last_error_code and state != logparse.CONNECTED:
        rows.append(("Last error", _color("%s (%d) x%d" % (
            kvc.describe_error(info.last_error_code), info.last_error_code,
            info.consecutive_errors), RED)))
    for k, v in rows:
        print("  %-10s %s" % (k, v))
    return 0 if state == logparse.CONNECTED else 3


def _find_profile(store: ProfileStore, settings: Settings, name):
    if not name:
        return store.get(settings.default_profile) or (store.profiles[0] if store.profiles else None)
    return next((p for p in store.profiles if p.name == name or p.id == name), None)


def cmd_connect(args) -> int:
    if sys.platform == "darwin":
        from .macos import open_client
        try:
            open_client()
        except RuntimeError as e:
            print("error: %s" % e, file=sys.stderr)
            return 4
        print("Opened Kerio Control VPN Client. Choose the connection and click Connect.")
        return 0
    from .controller import NeedPassword, activate_profile
    store, settings = ProfileStore(), Settings.load()
    profile = _find_profile(store, settings, args.profile)
    if not profile:
        print("No such profile. Use `kerio-vpn profiles` or add one in the GUI.", file=sys.stderr)
        return 2
    password = None
    if args.ask_password:
        password = getpass.getpass("Password for %s@%s: " % (profile.username, profile.server))
    try:
        try:
            activate_profile(settings, store, profile, password)
        except NeedPassword:
            password = getpass.getpass("Password for %s@%s: " % (profile.username,
                                                                profile.server))
            activate_profile(settings, store, profile, password, remember=False)
    except (privileged.PrivilegeError, kvc.ValidationError, RuntimeError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    settings.default_profile = profile.id
    settings.save()
    print("Connecting to %s…" % profile.name)
    if args.wait:
        deadline = time.time() + args.wait
        while time.time() < deadline:
            time.sleep(1)
            info = _session_info()
            if info.phase == logparse.CONNECTED:
                print(_color("Connected: %s" % info.local_ip, GREEN))
                return 0
            if info.last_error_code == 161:
                print(_color("Authentication failed", RED), file=sys.stderr)
                privileged.control("stop")
                return 1
        print("Timed out waiting for the tunnel", file=sys.stderr)
        return 3
    return 0


def cmd_simple(action: str):
    def run(_args) -> int:
        if sys.platform == "darwin":
            from .macos import open_client
            try:
                open_client()
            except RuntimeError as e:
                print("error: %s" % e, file=sys.stderr)
                return 4
            print("Opened Kerio Control VPN Client for %s." % action)
            return 0
        try:
            privileged.control(action)
            if action == "stop":
                privileged.control("killswitch-disable")
        except privileged.PrivilegeError as e:
            print("error: %s" % e, file=sys.stderr)
            return 1
        return 0
    return run


def cmd_profiles(_args) -> int:
    if sys.platform == "darwin":
        from .macos import read_connections
        connections = read_connections()
        if not connections:
            print("No native Kerio connections.")
        for connection in connections:
            suffix = " (persistent)" if connection.persistent else ""
            print("  %-24s %s@%s%s" % (connection.name, connection.username,
                                       connection.server, suffix))
        return 0
    store, settings = ProfileStore(), Settings.load()
    if not store.profiles:
        print("No profiles.")
    for p in store.profiles:
        mark = "*" if p.id == settings.default_profile else " "
        print("%s %-24s %s@%s" % (mark, p.name, p.username, p.address))
    return 0


def cmd_logs(args) -> int:
    path = kvc.ERROR_LOG if args.errors else kvc.DEBUG_LOG
    if not os.access(path, os.R_OK):
        print("cannot read %s" % path, file=sys.stderr)
        return 1
    from .logtail import LogTail
    tail = LogTail(path)
    lines = tail.initial(2 * 1024 * 1024)

    def show(raw_lines):
        for raw in raw_lines:
            line = logparse.parse_line(raw)
            if args.all or not line.noisy:
                print(raw, flush=True)
    filtered = [r for r in lines if args.all or not logparse.parse_line(r).noisy]
    show(filtered[-args.lines:])
    try:
        while args.follow:
            time.sleep(1)
            show(tail.read_new())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_fingerprint(args) -> int:
    host, port = kvc.split_server(args.server)
    try:
        info = certs.fetch(host, port)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    print("MD5:     %s\nSHA-256: %s\nSubject: %s\nExpires: %s" % (
        info.md5, info.sha256, info.subject, info.not_after))
    return 0


def cmd_add(args) -> int:
    host, port = kvc.split_server(args.server)
    store = ProfileStore()
    fp = args.fingerprint
    if not fp:
        info = certs.fetch(host, port)
        print("Server certificate MD5 fingerprint: %s" % info.md5)
        if input("Trust it? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
        fp = info.md5
    p = Profile(name=args.name or host, server=host, port=port, username=args.username,
                fingerprint=kvc.normalize_fingerprint(fp), save_password=False)
    try:
        p.validate()
    except kvc.ValidationError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    store.upsert(p)
    print("Added %s" % p.name)
    return 0


def cmd_install_client(args) -> int:
    if sys.platform == "darwin":
        print("Install the official macOS .dmg from Kerio/GFI; .deb packages are Linux-only.",
              file=sys.stderr)
        return 2
    from . import installer
    reason = installer.supported()
    if reason:
        print("error: %s" % reason, file=sys.stderr)
        return 2
    try:
        path = args.file
        if not path:
            release = installer.latest_release()
            print("Downloading Kerio VPN Client %s…" % release.label)
            path = installer.download(release, installer.cache_dir())
        info = installer.package_info(path)
        print("Installing %s %s…" % (info["Package"], info.get("Version", "")))
        privileged.configure("install-client", {"path": os.path.abspath(path)})
    except (installer.InstallError, privileged.PrivilegeError) as e:
        print("error: %s" % e, file=sys.stderr)
        if not args.file:
            print("Download the package from %s and run:\n  kerio-vpn install-client "
                  "--file <package.deb>" % installer.DOWNLOAD_PAGE, file=sys.stderr)
        return 1
    print("Kerio VPN Client installed.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kerio-vpn", epilog="Run without a command to open the graphical interface.",
                                 description="Control the Kerio Control VPN Client.")
    ap.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="show tunnel state")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("connect", help="connect a profile (default profile if omitted)")
    s.add_argument("profile", nargs="?")
    s.add_argument("-p", "--ask-password", action="store_true",
                   help="prompt for the password instead of using the keyring")
    s.add_argument("-w", "--wait", type=int, default=30, metavar="SEC",
                   help="wait until connected (0 = do not wait)")
    s.set_defaults(func=cmd_connect)

    sub.add_parser("disconnect", help="stop the tunnel").set_defaults(func=cmd_simple("stop"))
    sub.add_parser("restart", help="restart the tunnel").set_defaults(
        func=cmd_simple("restart"))
    sub.add_parser("profiles", help="list profiles").set_defaults(func=cmd_profiles)

    s = sub.add_parser("add", help="add a profile")
    s.add_argument("server", help="host[:port]")
    s.add_argument("username")
    s.add_argument("--name")
    s.add_argument("--fingerprint", help="MD5 fingerprint (detected if omitted)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("logs", help="show logs")
    s.add_argument("-f", "--follow", action="store_true")
    s.add_argument("-n", "--lines", type=int, default=50)
    s.add_argument("-e", "--errors", action="store_true", help="error.log instead of debug.log")
    s.add_argument("-a", "--all", action="store_true", help="include packet noise")
    s.set_defaults(func=cmd_logs)

    s = sub.add_parser("fingerprint", help="show a server certificate fingerprint")
    s.add_argument("server", help="host[:port]")
    s.set_defaults(func=cmd_fingerprint)

    s = sub.add_parser("install-client", help="install the official Kerio VPN Client package")
    s.add_argument("--file", help="use a downloaded kerio-control-vpnclient .deb")
    s.set_defaults(func=cmd_install_client)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        args = ap.parse_args(["status"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
