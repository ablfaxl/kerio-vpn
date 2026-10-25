# Contributing to Kerio VPN

Thanks for helping! Bug reports, fixes, translations of documentation, packaging for more
distributions and UI ideas are all welcome.

## Development setup

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-notify-0.7 \
    gir1.2-secret-1 gir1.2-ayatanaappindicator3-0.1 pyflakes3
git clone https://github.com/liimitedinfinity/kerio-vpn.git
cd kerio-vpn
./bin/kerio-vpn            # run the GUI from the source tree
./bin/kerio-vpn status     # run the CLI
```

Without the installed polkit policy, every privileged action asks for the administrator
password. Run `sudo make install` to test the real permission model.

## Before you open a pull request

```sh
make lint
make test
```

- Keep the code style of the surrounding code (PEP 8, 100 columns).
- **Never commit personal data**: no real server names, usernames, IP addresses,
  certificate fingerprints, log excerpts or time zones. Use `example.com` names; tests may
  only use the reserved documentation address ranges (RFC 5737).
- Commit with a UTC timestamp so no time zone is recorded: `TZ=UTC git commit`.
- If the UI changes, regenerate the screenshots. The tool renders demo data and never
  touches your system:

  ```sh
  xvfb-run -a -s "-screen 0 1280x900x24" python3 tools/screenshots.py docs/screenshots
  GTK_THEME=Adwaita:dark xvfb-run -a -s "-screen 0 1280x900x24" \
      python3 tools/screenshots.py docs/screenshots --dark
  GTK_THEME=Adwaita:dark xvfb-run -a -s "-screen 0 1280x900x24" \
      python3 tools/screenshots.py docs/screenshots --gif     # README demo (needs Pillow)
  python3 tools/social_preview.py                              # docs/social-preview.png
  ```

- Add an entry to `CHANGELOG.md`.

## Project layout

| Path | Purpose |
|---|---|
| `kerio_vpn/kvc.py` | Config format of `kvpncsvc`, validation (shared with the root helper) |
| `kerio_vpn/logparse.py` | Turns `debug.log` into tunnel state |
| `kerio_vpn/monitor.py` | Background polling of service, logs and interface counters |
| `kerio_vpn/controller.py` | Connection logic used by GUI, tray and CLI |
| `kerio_vpn/helper.py` | Privileged helper (runs as root through pkexec) |
| `kerio_vpn/splitroute.py` | Split tunneling rules |
| `kerio_vpn/installer.py` | Finds and downloads the official Kerio client |
| `kerio_vpn/ui/` | GTK 3 interface |
| `libexec/` | pkexec entry points, one per polkit action |
| `data/` | Desktop entry, polkit policy, AppStream metadata, icons |

## Security-sensitive code

`kerio_vpn/helper.py` runs as root. Every value it receives must be validated, and new
actions must be added to the right polkit level (`control` or `configure`). Please add
tests in `tests/test_helper.py` for any change there.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
