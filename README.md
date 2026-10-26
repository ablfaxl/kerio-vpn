<div align="center">

<img src="data/macos/app-icon-1024.png" width="128" alt="Kerio VPN app icon">

# Kerio VPN — Kerio Control VPN Client GUI for Linux and macOS

**A modern companion for the official Kerio Control VPN Client on Linux and macOS.**
Connect in one click, manage several VPN profiles, split-tunnel traffic, and watch live status and logs.
No more `dpkg-reconfigure` and editing `/etc/kerio-kvc.conf` by hand.

[![CI](https://github.com/liimitedinfinity/kerio-vpn/actions/workflows/ci.yml/badge.svg)](https://github.com/liimitedinfinity/kerio-vpn/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/liimitedinfinity/kerio-vpn?sort=semver)](https://github.com/liimitedinfinity/kerio-vpn/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/liimitedinfinity/kerio-vpn/total)](https://github.com/liimitedinfinity/kerio-vpn/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Ubuntu%20%7C%20Debian%20%7C%20Mint-blue)

[**Download**](https://github.com/liimitedinfinity/kerio-vpn/releases/latest) ·
[Features](#features) ·
[Installation](#installation) ·
[Usage](#usage) ·
[CLI](#command-line-interface) ·
[FAQ](#faq--troubleshooting)

<img src="docs/screenshots/demo.gif" alt="Kerio VPN demo: connecting to a Kerio Control VPN server on Linux, live traffic, split tunneling and connection profiles" width="860">

</div>

---

## Why Kerio VPN?

Kerio Control (by GFI Software) ships a VPN client for Linux, `kerio-control-vpnclient`,
but it has **no graphical interface**. You configure it with a text wizard, check its state
with `systemctl`, and read cryptic codes in `/var/log/kerio-kvc/`. It also keeps retrying
a wrong password forever, which can lock your account.

**Kerio VPN** is a free, open-source desktop app and CLI built on top of the official client:

- ✅ Uses the **official Kerio daemon** (`kvpncsvc`). It controls the client and does not replace it.
- ✅ Includes a **native SwiftUI macOS app** with its own isolated multi-profile workspace.
- ✅ Looks and works like a modern VPN app: **one-click connect**, tray icon, notifications.
- ✅ **Installs the Kerio client for you** if it is missing.
- ✅ Adds features the official client lacks: **split tunneling**, a **kill switch**,
  **DNS leak protection**, multiple profiles and readable logs.

> Kerio VPN is an independent community project. It is not affiliated with, endorsed by or
> sponsored by Kerio Technologies or GFI Software. "Kerio" and "Kerio Control" are
> trademarks of their respective owners.

## Features

| | |
|---|---|
| 🔌 **One-click connection** | Connect, disconnect or switch between servers from the window, the tray or the CLI |
| 👥 **Multiple profiles** | Any number of servers and accounts. Import the existing system configuration; import or export profiles as JSON (passwords are never exported) |
| 🔐 **Secure by design** | Passwords in the desktop keyring (GNOME Keyring / KWallet). Server identity is pinned by its certificate fingerprint, with a loud warning if it changes. Privileged actions go through polkit |
| 📊 **Live dashboard** | Connection state, VPN IP, DNS, routes, full or split tunnel, uptime, latency, live download and upload speed, traffic chart |
| 🔀 **Split tunneling** | Per-connection lists of IPs, networks and domains that **bypass the VPN** or are **always sent through it** |
| 🛡️ **Kill switch** | Blocks traffic outside the tunnel if the VPN drops unexpectedly (nftables), with optional LAN access |
| 🌐 **DNS integration** | Registers VPN DNS with systemd-resolved, can send all DNS through the VPN to prevent leaks, and repairs DNS in one click after a crash |
| 🚫 **Account lockout protection** | Stops the daemon after repeated failed logins and asks for the password |
| 📜 **Readable logs** | Live `debug.log` with packet noise filtered out, `error.log` and the service journal; search, pause, copy, save |
| 🩺 **Diagnostics** | One-click report (without passwords) for your network administrator |
| 💤 **Desktop integration** | Tray icon, notifications, autostart at login, reconnect after suspend, start at boot |
| ⌨️ **Scriptable CLI** | `kerio-vpn status / connect / disconnect / logs -f / install-client …` |
| 📦 **Client installer** | Detects a missing `kerio-control-vpnclient` and installs the official package |

## Screenshots

![Kerio VPN dark theme dashboard](docs/screenshots/dashboard-dark.png)

| Dashboard | Connections |
|---|---|
| ![Kerio VPN Linux dashboard](docs/screenshots/dashboard.png) | ![Managing Kerio VPN connection profiles](docs/screenshots/connections.png) |
| **Split tunneling** | **Settings** |
| ![Kerio VPN split tunneling: bypass or force destinations](docs/screenshots/split-tunneling.png) | ![Kerio VPN settings: kill switch and DNS](docs/screenshots/settings.png) |
| **Automatic client installation** | **Connection editor** |
| ![Install the Kerio Control VPN Client automatically](docs/screenshots/install.png) | ![Adding a Kerio VPN connection with certificate fingerprint detection](docs/screenshots/connection-editor.png) |

## Installation

### macOS

The macOS edition is a native SwiftUI app. It shows the launchd/tunnel state, readable recent
logs, and maintains any number of connections independently from Kerio's existing preference
pane. Its profile store lives in `~/Library/Application Support/KerioVPNMac`; the existing
`~/.kerio/vpnclient` directory is never modified.

When you open a connection, the signed Kerio status client is launched with an isolated home
directory containing only this app's profiles. Password fields are deliberately left empty so
Kerio asks for them directly; this project never reads or exports saved passwords. Use
**Import existing** to copy only connection name, server, username, and persistence metadata
from the existing Kerio configuration.

macOS features:

- Native SwiftUI split-view interface and Dock icon
- Add and remove multiple independent Kerio connections
- One-click import of non-secret metadata from the existing Kerio client
- Isolated Kerio runtime under `Application Support/KerioVPNMac/KerioHome`
- Live daemon status and recent activity log
- No changes to the user's original Kerio profiles
- Single-instance Kerio helper management, preventing duplicate menu-bar icons
- **Hide Kerio helper** closes the isolated menu-bar item without stopping the VPN daemon

Requirements: macOS 13 or newer and the official Kerio Control VPN Client. Build the app with:

```sh
make macos
open "dist/Kerio VPN.app"
```

The build targets the current Mac architecture and produces an ad-hoc signed local app bundle.
The official client itself must be installed from the
[Kerio/GFI VPN download page](https://www.gfi.com/products-and-solutions/network-security-solutions/keriocontrol/resources/vpn).

The CLI also understands the native macOS layout:

```sh
python3 -m kerio_vpn status
python3 -m kerio_vpn profiles
python3 -m kerio_vpn logs -n 50
```

### Requirements

- **Ubuntu 20.04+, Debian 11+, Linux Mint 20+**, Pop!_OS, Zorin OS, elementary OS or another
  Debian-based distribution, 64-bit (amd64). Kerio only publishes the client as an amd64 `.deb`.
- A desktop with GTK 3 (GNOME, KDE Plasma, Xfce, Cinnamon, MATE, Budgie…), on X11 or Wayland.
- The **Kerio Control VPN Client**. Kerio VPN installs it for you if it is missing.

### Option 1: install the .deb package (recommended)

**One command** downloads and installs the latest release:

```sh
wget -O /tmp/kerio-vpn.deb https://github.com/liimitedinfinity/kerio-vpn/releases/latest/download/kerio-vpn_latest_all.deb \
  && sudo apt install /tmp/kerio-vpn.deb
```

Or download the file in your browser:

| Package | Link |
|---|---|
| Latest release, Debian / Ubuntu / Mint (`all`) | [**kerio-vpn_latest_all.deb**](https://github.com/liimitedinfinity/kerio-vpn/releases/latest/download/kerio-vpn_latest_all.deb) |
| Version 1.3.0 | [kerio-vpn_1.3.0_all.deb](https://github.com/liimitedinfinity/kerio-vpn/releases/download/v1.3.0/kerio-vpn_1.3.0_all.deb) |
| AppImage (portable, no install) | [kerio-vpn-latest-x86_64.AppImage](https://github.com/liimitedinfinity/kerio-vpn/releases/latest/download/kerio-vpn-latest-x86_64.AppImage) |
| Checksums | [SHA256SUMS](https://github.com/liimitedinfinity/kerio-vpn/releases/latest/download/SHA256SUMS) |
| All versions | [Releases](https://github.com/liimitedinfinity/kerio-vpn/releases) |

Then install it with `sudo apt install ./kerio-vpn_*_all.deb` and open **Kerio VPN** from
your applications menu, or run `kerio-vpn`.

The AppImage runs without installing (`chmod +x kerio-vpn-latest-x86_64.AppImage` and
start it). It uses your system's Python and GTK 3 (`sudo apt install python3-gi
python3-gi-cairo gir1.2-gtk-3.0`). Because an AppImage cannot install a polkit policy,
every privileged action asks for the administrator password, so the `.deb` is the
recommended way to install.

To verify the download before installing:

```sh
wget https://github.com/liimitedinfinity/kerio-vpn/releases/latest/download/SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
```

`apt` pulls in all dependencies. Upgrading works the same way, and your profiles and saved
passwords are kept.

### Option 2: install from source

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-notify-0.7 \
    gir1.2-secret-1 gir1.2-ayatanaappindicator3-0.1 pkexec iproute2 nftables
git clone https://github.com/liimitedinfinity/kerio-vpn.git
cd kerio-vpn
sudo make install          # sudo make uninstall removes it again
```

Or build your own package with `make deb` (the result is in `dist/`).

### Installing the Kerio Control VPN Client

On first start Kerio VPN checks for the official client. If it is missing, click
**Install automatically**. Kerio VPN then:

1. finds the latest release in Kerio's official software archive,
2. downloads the package over **verified HTTPS** only,
3. checks that the file really is `kerio-control-vpnclient` for your architecture,
4. installs it with `apt` after asking for the administrator password.

If the automatic download is not possible (for example, Kerio's download server presents
an invalid certificate, or the computer is offline), get the package from the
[official download page](https://gfi.ai/products-and-solutions/network-security-solutions/keriocontrol/resources/vpn)
and choose **Install from file…**, or run:

```sh
kerio-vpn install-client --file ~/Downloads/kerio-control-vpnclient-*-linux-amd64.deb
```

> **Tip:** use a client version that matches your Kerio Control server. Your administrator
> can also download it from the Kerio Control web interface.

### Tray icon on GNOME

GNOME needs the *AppIndicator and KStatusNotifierItem Support* extension for tray icons.
Ubuntu enables it by default. On other distributions:

```sh
sudo apt install gnome-shell-extension-appindicator
```

## Usage

1. **Add a connection.** Go to *Connections → Add connection…* and enter the server
   (`vpn.example.com` or `vpn.example.com:4090`), your username and your password.
2. **Verify the server.** Click **Detect** to fetch the certificate fingerprint and compare
   it with the one your administrator gives you (Kerio Control → *Interfaces → VPN Server →
   Properties*).
3. **Connect.** Press **Connect** on the dashboard or in the tray menu.

Already configured the client with `dpkg-reconfigure`? Use
**Import current system configuration** to turn it into a profile.

### Split tunneling

Open **Split tunneling**, pick a connection and add entries. You can paste several at once,
separated by spaces, commas or new lines:

| List | Effect | Example entries |
|---|---|---|
| **Bypass the VPN** | Goes directly through your normal internet connection, even if the VPN routes all traffic | an IP address, a network in CIDR notation, `updates.example.org` |
| **Always through the VPN** | Is sent through the tunnel even if the server only pushes company networks | an IP address, a network in CIDR notation, `intranet.example.com` |

Rules are applied every time the connection comes up. Domain names are resolved when the
rules are applied and refreshed every 10 minutes. The routes are tagged
(`ip route show proto 233`) and removed when you disconnect.

### Kill switch

*Settings → Security → Kill switch* blocks all outgoing traffic except the VPN tunnel, the
VPN server, DHCP and (optionally) your local network, so nothing leaks if the tunnel drops.
It is lifted automatically when you disconnect manually, and it never survives a reboot.

## Command-line interface

`kerio-vpn` with no arguments opens the GUI. With a command it works in a terminal or over SSH:

```text
$ kerio-vpn status
● CONNECTED
  Service    active (disabled at boot)
  Server     vpn.example.com
  User       jane.doe
  VPN IP     <address assigned by the server>
  DNS        <VPN DNS server> corp.example
  Routing    full tunnel
  Uptime     02:17:42
```

| Command | Description |
|---|---|
| `kerio-vpn status [--json]` | Show the tunnel state (exit code 0 when connected, so it works in scripts) |
| `kerio-vpn connect [PROFILE] [-p] [-w SEC]` | Connect the default or a named profile, then wait until it is up |
| `kerio-vpn disconnect` | Disconnect |
| `kerio-vpn restart` | Restart the tunnel |
| `kerio-vpn profiles` | List profiles (`*` marks the default) |
| `kerio-vpn add HOST[:PORT] USER [--name N]` | Add a profile; detects and asks you to confirm the fingerprint |
| `kerio-vpn logs [-f] [-n N] [-e] [-a]` | Show or follow logs (`-e` error.log, `-a` include packet noise) |
| `kerio-vpn fingerprint HOST[:PORT]` | Show a server's certificate fingerprints |
| `kerio-vpn install-client [--file DEB]` | Install the official Kerio Control VPN Client |

GUI options: `--minimized`, `--connect NAME`, `--connect-default`, `--disconnect`.

## How it works

```text
 Kerio VPN (GUI / tray / CLI, runs as you)
        │  pkexec + polkit
        ├──► kerio-vpn-control     start · stop · DNS · split routes · kill switch
        └──► kerio-vpn-configure   write /etc/kerio-kvc.conf · install client · boot
                     │
                     ▼
        systemd: kerio-kvc.service ──► kvpncsvc (official Kerio Control VPN Client)
                     │
 state ◄── /var/log/kerio-kvc/debug.log · error.log · /sys/class/net/kvnet/statistics
```

- **Configuration** is written in exactly the format of Kerio's own Debian wizard, including
  its password obfuscation. A test checks this against the wizard's shell code byte for byte.
- **State** comes from the daemon's state-machine messages (`libVpn(connected)`,
  `libVpn(error 161)` …), so the app knows *why* a connection fails, not only *that* it does.
- **Privileges**: connecting and disconnecting a configured profile needs no password, like
  NetworkManager. Changing the system configuration or installing software needs an
  administrator password, which polkit remembers for a few minutes.

See [SECURITY.md](SECURITY.md) for the full security model.

## FAQ / Troubleshooting

<details>
<summary><b>Authentication failed (error 161)</b></summary>

The username or password is wrong, or the account is not allowed to use VPN in Kerio
Control. Kerio VPN stops retrying after two failures (configurable) to avoid an account
lockout, and asks for the password again.
</details>

<details>
<summary><b>SSL error (error 120)</b></summary>

The TLS handshake failed. Usually the server certificate was renewed, so the saved
fingerprint no longer matches. Use *Check certificate*, and only accept the new
fingerprint after your administrator confirms it. It can also mean the port is wrong
(the default is 4090).
</details>

<details>
<summary><b>Operation timeout (145) / network error (146) / closed by peer (142)</b></summary>

The server cannot be reached or dropped the connection. Check the address and port, your
internet connection, and whether a firewall blocks TCP/UDP 4090. The daemon keeps retrying
automatically.
</details>

<details>
<summary><b>Unable to resolve server name (191)</b></summary>

The server's DNS name does not resolve. Check for typos, or use the server's IP address.
</details>

<details>
<summary><b>Internet does not work after the VPN disconnected</b></summary>

The kill switch may still be active after an unexpected drop (the dashboard shows a
banner with a *Disable kill switch* button). Otherwise DNS may still point at the VPN
server: use *Settings → DNS → Repair*. As a last resort:

```sh
sudo nft delete table inet kerio_vpn
sudo ip -4 route flush proto 233
```
</details>

<details>
<summary><b>Internal names (intranet) do not resolve</b></summary>

On systems with systemd-resolved, enable *Settings → DNS → Register VPN DNS with
systemd-resolved*. To send all DNS queries through the VPN, also enable
*Send all DNS queries through the VPN*.
</details>

<details>
<summary><b>No tray icon</b></summary>

Install and enable the AppIndicator GNOME extension (see [Tray icon on GNOME](#tray-icon-on-gnome)).
Without a tray, closing the window quits the app instead of hiding it.
</details>

<details>
<summary><b>Does this work with Fedora, Arch or openSUSE?</b></summary>

Kerio only publishes the client as a Debian package for amd64. Kerio VPN itself is plain
Python and GTK, so it runs anywhere the official client runs. Packaging contributions are
welcome.
</details>

<details>
<summary><b>Where is my data stored?</b></summary>

| What | Where |
|---|---|
| Profiles (no passwords) | `~/.config/kerio-vpn/profiles.json` |
| Settings | `~/.config/kerio-vpn/settings.json` |
| Passwords | Desktop keyring, item "Kerio VPN: <profile>" |
| Active system config | `/etc/kerio-kvc.conf` (root only, written by the official format) |
| Kill switch | nftables table `inet kerio_vpn` (never persistent) |
| Split tunneling routes | Kernel routes with `proto 233` |
</details>

## Uninstall

```sh
sudo apt remove kerio-vpn             # keeps the Kerio client
sudo apt purge kerio-vpn              # also removes /var/lib/kerio-vpn
rm -rf ~/.config/kerio-vpn            # your profiles and settings
```

Removing the package always lifts the kill switch and the split tunneling routes.

## Roadmap

- [ ] Flatpak and AppImage packages
- [ ] Translations
- [ ] Per-application split tunneling
- [ ] Connection statistics history

Have an idea? [Open a feature request](https://github.com/liimitedinfinity/kerio-vpn/issues/new/choose).

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first. If Kerio
VPN saves you time, **give it a ⭐ on GitHub**; it helps other Linux users find it.

## License

Kerio VPN is free software under the [GNU General Public License v3.0](LICENSE) or later.

<sub>Keywords: Kerio Control VPN client Linux GUI, Kerio VPN Ubuntu, Kerio VPN Debian, Kerio VPN Linux Mint,
kerio-control-vpnclient, kvpncsvc, kerio-kvc, Kerio VPN graphical interface, Kerio VPN tray, Kerio VPN split tunneling,
GFI Kerio Control VPN Linux.</sub>
