"""Single entry point: `kerio-vpn` opens the GUI, `kerio-vpn <command>` is the CLI."""

import os
import sys

CLI_COMMANDS = {"status", "connect", "disconnect", "restart", "profiles", "add", "logs",
                "fingerprint", "install-client", "-h", "--help", "--version"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    has_display = (sys.platform == "darwin" or
                   bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")))
    if sys.platform == "darwin" and not argv:
        from .macos import open_client
        open_client()
        return 0
    if (argv and argv[0] in CLI_COMMANDS) or (not argv and not has_display):
        from .cli import main as cli_main
        return cli_main(argv)
    from .ui.app import main as gui_main
    return gui_main([sys.argv[0]] + argv)


if __name__ == "__main__":
    sys.exit(main())
