# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

## [1.2.1] - 2026-10-24

### Added
- Release downloads: a stable `kerio-vpn_latest_all.deb` link that always points to the
  newest version, and `SHA256SUMS` for verification.
- One-command install instructions in the README.

## [1.2.0] - 2026-10-24

### Added
- Detects a missing Kerio Control VPN Client on startup and installs it: downloads the
  latest official package over verified HTTPS, or installs a `.deb` you downloaded.
- `kerio-vpn install-client [--file PACKAGE.deb]` command.
- AppStream metadata, so software centers show the app properly.
- Screenshot tool (`tools/screenshots.py`) that renders only demo data.

### Changed
- The project is now called **Kerio VPN**. One command, `kerio-vpn`, opens the GUI, and
  `kerio-vpn <command>` runs the CLI.
- Settings, saved passwords and autostart from earlier releases are migrated automatically.

## [1.1.0] - 2026-10-24

### Added
- Sidebar navigation with Dashboard, Connections, Split tunneling, Logs, Settings and About.
- Split tunneling: per-connection lists of IPs, networks and domains that bypass the VPN
  or are always routed through it.
- Statistic tiles and a traffic chart with a labelled axis.
- Latency falls back to the VPN server when the VPN DNS server does not answer ping.

### Fixed
- Window had no title bar, so it could not be moved, minimized or maximized.

## [1.0.0] - 2026-10-24

### Added
- First release: connection profiles, keyring passwords, certificate pinning, live
  status and logs, stop after failed logins, kill switch, systemd-resolved DNS, tray
  icon, notifications and CLI.

[1.2.1]: https://github.com/liimitedinfinity/kerio-vpn/releases/tag/v1.2.1
[1.2.0]: https://github.com/liimitedinfinity/kerio-vpn/releases/tag/v1.2.0
[1.1.0]: https://github.com/liimitedinfinity/kerio-vpn/releases/tag/v1.1.0
[1.0.0]: https://github.com/liimitedinfinity/kerio-vpn/releases/tag/v1.0.0
