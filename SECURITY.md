# Security Policy

## Supported versions

Security fixes are released for the latest minor version.

| Version | Supported |
|---|---|
| 1.2.x | ✅ |
| < 1.2 | ❌ |

## Reporting a vulnerability

Please **do not open a public issue**. Use
[GitHub private vulnerability reporting](https://github.com/liimitedinfinity/kerio-vpn/security/advisories/new)
and include:

- the affected version and distribution
- steps to reproduce, or a proof of concept
- the impact you expect

You will get an answer within 7 days. We will coordinate a fix and a disclosure date with you.

## Security model in short

- The GUI runs as the user. Privileged work goes through two small helpers started with
  `pkexec`. *control* (start, stop, DNS, routes, kill switch) is allowed for the active
  local session; *configure* (writing `/etc/kerio-kvc.conf`, installing the client) needs
  an administrator password.
- Parameters, including passwords, are sent to the helper as JSON on stdin, never on the
  command line, and every field is validated before use.
- Passwords are stored in the desktop keyring (Secret Service), never in plain files.
- The server is pinned by its certificate fingerprint, as the official client does.
- The Kerio client package is only downloaded over verified HTTPS from Kerio's servers,
  and the helper checks the package name and architecture before installing it.

Vulnerabilities in the Kerio Control VPN Client itself should be reported to GFI Software.
