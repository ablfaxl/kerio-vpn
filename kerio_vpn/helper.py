"""Privileged helper, executed as root through pkexec.

Two entry points exist so polkit can grant them different defaults:

* ``kerio-vpn-control``   - start/stop the tunnel, DNS, kill switch.
                                  Allowed for the active local session.
* ``kerio-vpn-configure`` - write /etc/kerio-kvc.conf, read it back,
                                  change boot behaviour. Requires admin auth.

Protocol: ``<entry> <action>``; parameters are passed as one JSON object on
stdin (never on the command line, where passwords would be visible in ps),
and the result is printed as one JSON object on stdout.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from . import kvc, splitroute

STATE_DIR = "/var/lib/kerio-vpn"
APPLIED_FILE = STATE_DIR + "/applied.json"
NFT_TABLE = "kerio_vpn"
MAX_INPUT = 64 * 1024
IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}\*?$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]{0,253}$")
LAN_V4 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
          "224.0.0.0/4", "255.255.255.255/32")
LAN_V6 = ("fe80::/10", "fc00::/7", "ff00::/8")

SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}


class HelperError(Exception):
    pass


def _run(cmd, stdin=None, timeout=30, check=True):
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                           timeout=timeout, env=SAFE_ENV)
    except FileNotFoundError:
        raise HelperError("%s is not installed" % cmd[0])
    except subprocess.TimeoutExpired:
        raise HelperError("%s timed out" % " ".join(cmd[:2]))
    if check and p.returncode != 0:
        raise HelperError((p.stderr or p.stdout).strip() or "%s failed" % cmd[0])
    return p


def _systemd() -> bool:
    return os.path.isdir("/run/systemd/system")


def _service(verb: str) -> None:
    if not os.path.exists(kvc.DAEMON):
        raise HelperError("Kerio Control VPN Client is not installed")
    if _systemd():
        if verb in ("start", "restart"):
            _run(["systemctl", "reset-failed", kvc.SERVICE], check=False)
        _run(["systemctl", verb, kvc.SERVICE], timeout=60)
    else:
        _run([kvc.INIT_SCRIPT, verb], timeout=60)


def _is_active() -> bool:
    if _systemd():
        p = _run(["systemctl", "is-active", kvc.SERVICE], check=False)
        return p.stdout.strip() in ("active", "activating", "reloading")
    return _run(["pgrep", "-x", "kvpncsvc"], check=False).returncode == 0


def _write_atomic(path: str, data: str, mode: int = 0o600) -> None:
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".kvp-", dir=directory)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _config_stat():
    try:
        st = os.stat(kvc.CONFIG_PATH)
        return {"mtime_ns": st.st_mtime_ns, "size": st.st_size, "ino": st.st_ino}
    except OSError:
        return None


# ---------------------------------------------------------------- actions

def act_status(_args):
    return {
        "active": _is_active(),
        "config": _config_stat(),
        "killswitch": _killswitch_active(),
    }


def act_start(_args):
    _service("start")
    return {}


def act_stop(_args):
    if _is_active():
        _service("stop")
    return {}


def act_restart(_args):
    _service("restart")
    return {}


def act_apply(args):
    """Write the connection config and (re)start the daemon."""
    cfg = kvc.KvcConfig(
        server=args.get("server", ""),
        port=args.get("port", kvc.DEFAULT_PORT),
        username=args.get("username", ""),
        password=args.get("password", ""),
        fingerprint=args.get("fingerprint", ""),
        active=True,
    )
    try:
        text = kvc.render_config(cfg)
    except kvc.ValidationError as e:
        raise HelperError("%s: %s" % (e.field, e))
    tag = str(args.get("tag", ""))[:128]

    backup = kvc.CONFIG_PATH + ".kerio-vpn.orig"
    if os.path.exists(kvc.CONFIG_PATH) and not os.path.exists(backup):
        with open(kvc.CONFIG_PATH) as f:
            _write_atomic(backup, f.read())

    _write_atomic(kvc.CONFIG_PATH, text)
    os.makedirs(STATE_DIR, mode=0o755, exist_ok=True)
    _write_atomic(APPLIED_FILE, json.dumps({"tag": tag, "config": _config_stat(),
                                            "time": time.time()}), mode=0o644)
    if args.get("connect", True):
        _service("restart" if _is_active() else "start")
    return {"config": _config_stat()}


def act_read_config(_args):
    try:
        with open(kvc.CONFIG_PATH) as f:
            cfg = kvc.parse_config(f.read())
    except FileNotFoundError:
        return {"config": None}
    except OSError as e:
        raise HelperError("Cannot read %s: %s" % (kvc.CONFIG_PATH, e))
    except Exception as e:  # malformed XML
        raise HelperError("Cannot parse %s: %s" % (kvc.CONFIG_PATH, e))
    if cfg is None:
        return {"config": None}
    return {"config": {"server": cfg.server, "port": cfg.port, "username": cfg.username,
                       "password": cfg.password, "fingerprint": cfg.fingerprint}}


def act_install_client(args):
    """Install the official kerio-control-vpnclient .deb chosen by the user."""
    src = args.get("path")
    if not isinstance(src, str) or not src.endswith(".deb") or not os.path.isabs(src):
        raise HelperError("Invalid package path")
    st = os.stat(src)
    if not stat.S_ISREG(st.st_mode) or st.st_size > 200 * 1024 * 1024:
        raise HelperError("Invalid package file")
    # Work on a private copy so the file cannot change between checks and install.
    workdir = tempfile.mkdtemp(prefix="kerio-vpn-pkg-")
    try:
        pkg = os.path.join(workdir, "kerio-control-vpnclient.deb")
        with open(src, "rb") as fin, open(pkg, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        os.chmod(pkg, 0o644)
        os.chmod(workdir, 0o755)   # apt drops privileges to _apt for local files
        fields = _run(["dpkg-deb", "-f", pkg, "Package", "Architecture", "Version"]).stdout
        info = dict(line.split(": ", 1) for line in fields.splitlines() if ": " in line)
        if info.get("Package") != kvc.DEB_PACKAGE:
            raise HelperError("This file is not the Kerio Control VPN Client package")
        arch = _run(["dpkg", "--print-architecture"]).stdout.strip()
        if info.get("Architecture") not in (arch, "all"):
            raise HelperError("Package architecture %s does not match this system (%s)"
                              % (info.get("Architecture"), arch))
        had_config = os.path.exists(kvc.CONFIG_PATH)
        env = dict(SAFE_ENV, DEBIAN_FRONTEND="noninteractive")
        try:
            p = subprocess.run(["apt-get", "install", "-y", "--no-install-recommends", pkg],
                               capture_output=True, text=True, timeout=900, env=env)
        except subprocess.TimeoutExpired:
            raise HelperError("Installation timed out")
        if p.returncode != 0:
            raise HelperError((p.stderr or p.stdout).strip()[-2000:] or "apt-get failed")
        if not had_config:
            # The package starts the daemon with an empty configuration; keep it off
            # until the user connects from the app.
            _run(["systemctl", "stop", kvc.SERVICE], check=False)
            _run(["systemctl", "disable", kvc.SERVICE], check=False)
        return {"version": info.get("Version", "")}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def act_boot(args):
    if not _systemd():
        raise HelperError("Start at boot can only be changed on systemd systems")
    verb = "enable" if args.get("enabled") else "disable"
    _run(["systemctl", verb, kvc.SERVICE])
    return {}


# ---- DNS (systemd-resolved)

def _iface(name) -> str:
    if not isinstance(name, str) or not IFACE_RE.match(name) or name.endswith("*"):
        raise HelperError("Invalid interface name")
    if _run(["ip", "link", "show", "dev", name], check=False).returncode != 0:
        raise HelperError("Interface %s does not exist" % name)
    return name


def act_dns_set(args):
    iface = _iface(args.get("iface"))
    servers = [str(ipaddress.ip_address(s)) for s in args.get("servers", [])][:4]
    domain = str(args.get("domain", "")).strip().strip(".")
    if domain and not DOMAIN_RE.match(domain):
        raise HelperError("Invalid DNS domain")
    if not servers:
        raise HelperError("No DNS servers given")
    _run(["resolvectl", "dns", iface] + servers)
    domains = []
    if args.get("route_all"):
        domains.append("~.")
    if domain:
        domains.append("~" + domain if args.get("route_all") else domain)
    if domains:
        _run(["resolvectl", "domain", iface] + domains)
    if args.get("route_all"):
        _run(["resolvectl", "default-route", iface, "yes"], check=False)
    _run(["resolvectl", "flush-caches"], check=False)
    return {}


def act_dns_clear(args):
    iface = _iface(args.get("iface"))
    _run(["resolvectl", "revert", iface], check=False)
    return {}


def act_dns_repair(_args):
    """Restore /etc/resolv.conf if kvpncsvc died without putting it back."""
    if _is_active():
        raise HelperError("Disconnect the VPN before repairing DNS")
    stub = "/run/systemd/resolve/stub-resolv.conf"
    resolved = _run(["systemctl", "is-active", "systemd-resolved"], check=False)
    if resolved.stdout.strip() == "active" and os.path.exists(stub):
        tmp = kvc.RESOLV_CONF + ".kvp-new"
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.symlink("../run/systemd/resolve/stub-resolv.conf", tmp)
        os.replace(tmp, kvc.RESOLV_CONF)
        if os.path.exists(kvc.RESOLV_BACKUP):
            os.replace(kvc.RESOLV_BACKUP, kvc.RESOLV_BACKUP + ".old")
        return {"method": "systemd-resolved"}
    if os.path.exists(kvc.RESOLV_BACKUP):
        with open(kvc.RESOLV_BACKUP) as f:
            data = f.read()
        if os.path.islink(kvc.RESOLV_CONF):
            os.unlink(kvc.RESOLV_CONF)
        _write_atomic(kvc.RESOLV_CONF, data, mode=0o644)
        os.replace(kvc.RESOLV_BACKUP, kvc.RESOLV_BACKUP + ".old")
        return {"method": "backup"}
    if os.path.exists("/run/NetworkManager"):
        _run(["systemctl", "reload-or-restart", "NetworkManager"], check=False)
        return {"method": "NetworkManager"}
    raise HelperError("Nothing to repair: no DNS backup was found")


# ---- split tunneling (policy-free, more specific routes in the main table)

def _networks(items, limit=splitroute.MAX_ENTRIES):
    if not isinstance(items, list) or len(items) > limit:
        raise HelperError("Invalid route list")
    return [str(splitroute.parse_network(str(i))) for i in items]


def _ipv4(value, field) -> str:
    try:
        addr = ipaddress.IPv4Address(str(value))
    except ValueError:
        raise HelperError("Invalid %s" % field)
    return str(addr)


def _flush_routes() -> None:
    _run(["ip", "-4", "route", "flush", "proto", splitroute.ROUTE_PROTO], check=False)


def act_routes_set(args):
    exclude = _networks(args.get("exclude", []))
    include = _networks(args.get("include", []))
    _flush_routes()
    failed = []
    if exclude:
        gw = _ipv4(args.get("uplink_gw"), "uplink gateway")
        dev = _iface(args.get("uplink_dev"))
        for net in exclude:
            p = _run(["ip", "-4", "route", "add", net, "via", gw, "dev", dev,
                      "proto", splitroute.ROUTE_PROTO], check=False)
            if p.returncode != 0 and "File exists" not in p.stderr:
                failed.append("%s: %s" % (net, p.stderr.strip()))
    if include:
        dev = _iface(args.get("iface"))
        via = ["via", _ipv4(args["vpn_gw"], "VPN gateway")] if args.get("vpn_gw") else []
        for net in include:
            p = _run(["ip", "-4", "route", "add", net] + via + ["dev", dev,
                      "proto", splitroute.ROUTE_PROTO], check=False)
            if p.returncode != 0 and "File exists" not in p.stderr:
                failed.append("%s: %s" % (net, p.stderr.strip()))
    return {"failed": failed}


def act_routes_clear(_args):
    _flush_routes()
    return {}


# ---- kill switch (nftables)

def _killswitch_active() -> bool:
    try:
        p = _run(["nft", "list", "table", "inet", NFT_TABLE], check=False, timeout=5)
    except HelperError:
        return False
    return p.returncode == 0


def build_killswitch_ruleset(server_ips, ifaces, allow_lan: bool, bypass=()) -> str:
    v4, v6 = [], []
    for ip in server_ips:
        addr = ipaddress.ip_address(ip)
        (v4 if addr.version == 4 else v6).append(str(addr))
    if not v4 and not v6:
        raise HelperError("Kill switch needs the VPN server IP address")
    names = []
    for name in ifaces:
        if not isinstance(name, str) or not IFACE_RE.match(name):
            raise HelperError("Invalid interface name")
        names.append(name)

    rules = ['oifname "lo" accept']
    rules += ['oifname "%s" accept' % n for n in names]
    if v4:
        rules.append("ip daddr { %s } accept" % ", ".join(v4))
    if v6:
        rules.append("ip6 daddr { %s } accept" % ", ".join(v6))
    rules.append("udp sport 68 udp dport 67 accept")
    rules.append("udp sport 546 udp dport 547 accept")
    rules.append("icmpv6 type { nd-router-solicit, nd-neighbor-solicit, "
                 "nd-neighbor-advert, mld-listener-report } accept")
    bypass = _networks(list(bypass))
    if bypass:
        rules.append("ip daddr { %s } accept" % ", ".join(bypass))
    if allow_lan:
        rules.append("ip daddr { %s } accept" % ", ".join(LAN_V4))
        rules.append("ip6 daddr { %s } accept" % ", ".join(LAN_V6))
    rules.append("counter reject")
    body = "\n".join("    " + r for r in rules)
    return (
        "table inet %(t)s\n"
        "delete table inet %(t)s\n"
        "table inet %(t)s {\n"
        "  chain output {\n"
        "    type filter hook output priority 0; policy accept;\n"
        "%(body)s\n"
        "  }\n"
        "}\n"
    ) % {"t": NFT_TABLE, "body": body}


def act_killswitch_enable(args):
    ruleset = build_killswitch_ruleset(args.get("server_ips", []),
                                       args.get("ifaces", []),
                                       bool(args.get("allow_lan", True)),
                                       args.get("bypass", []))
    _run(["nft", "-f", "-"], stdin=ruleset)
    return {"killswitch": True}


def act_killswitch_disable(_args):
    if _killswitch_active():
        _run(["nft", "delete", "table", "inet", NFT_TABLE])
    return {"killswitch": False}


CONTROL_ACTIONS = {
    "status": act_status,
    "start": act_start,
    "stop": act_stop,
    "restart": act_restart,
    "dns-set": act_dns_set,
    "dns-clear": act_dns_clear,
    "dns-repair": act_dns_repair,
    "routes-set": act_routes_set,
    "routes-clear": act_routes_clear,
    "killswitch-enable": act_killswitch_enable,
    "killswitch-disable": act_killswitch_disable,
}

CONFIGURE_ACTIONS = dict(CONTROL_ACTIONS, **{
    "apply": act_apply,
    "read-config": act_read_config,
    "boot": act_boot,
    "install-client": act_install_client,
})


def _reply(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(level: str, argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    actions = CONFIGURE_ACTIONS if level == "configure" else CONTROL_ACTIONS
    if os.geteuid() != 0:
        _reply({"ok": False, "error": "helper must run as root"})
        return 2
    if len(argv) != 1 or argv[0] not in actions:
        _reply({"ok": False, "error": "unknown action"})
        return 2
    os.umask(0o077)
    raw = sys.stdin.read(MAX_INPUT + 1) if not sys.stdin.isatty() else ""
    if len(raw) > MAX_INPUT:
        _reply({"ok": False, "error": "input too large"})
        return 2
    try:
        args = json.loads(raw) if raw.strip() else {}
        if not isinstance(args, dict):
            raise ValueError("expected an object")
    except ValueError as e:
        _reply({"ok": False, "error": "bad input: %s" % e})
        return 2
    try:
        result = actions[argv[0]](args)
    except (HelperError, ValueError, OSError) as e:
        _reply({"ok": False, "error": str(e)})
        return 1
    result["ok"] = True
    _reply(result)
    return 0
