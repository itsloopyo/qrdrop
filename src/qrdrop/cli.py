"""Command-line interface for qrdrop."""

import argparse
import copy
import os
import sys
from pathlib import Path
from urllib.parse import quote

from qrdrop import __version__


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="qrdrop",
        description="Instant file sharing from your terminal",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="Port to serve on (default: 8000)",
    )
    parser.add_argument(
        "-b",
        "--bind",
        type=str,
        default="0.0.0.0",
        help="Address to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--public-host",
        type=str,
        default=os.environ.get("QRDROP_PUBLIC_HOST"),
        help="Address (HOST or HOST:PORT) to advertise in the Network URL and QR code. "
        "Required for the QR code to work when running in Docker, where the "
        "auto-detected IP is the container's, e.g. --public-host 192.168.1.50. "
        "(env: QRDROP_PUBLIC_HOST)",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="Use specific password instead of generating one",
    )
    parser.add_argument(
        "--hide-dotfiles",
        action="store_true",
        help="Exclude files starting with '.' from listings",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--upload",
        action="store_true",
        help="Restrict writes to uploads only (no deletions or directory create/rename)",
    )
    mode.add_argument(
        "--readonly",
        action="store_true",
        help="Disable all writes; browse and download only",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Expire sessions after this many seconds (default: sessions last until the server stops)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress startup banner",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"qrdrop {__version__}",
    )
    args = parser.parse_args()
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds")
    if args.public_host is not None:
        host, sep, port_str = args.public_host.partition(":")
        if not host or (sep and not port_str.isdigit()):
            parser.error("--public-host must be HOST or HOST:PORT")
    return args


def _force_utf8_console() -> None:
    """Make the banner's box-drawing characters and emoji render correctly."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    # Align the Windows console output codepage so it decodes those bytes as
    # UTF-8 rather than the legacy OEM codepage (e.g. cp850), which otherwise
    # renders the QR code as mojibake under launchers like pipx.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)


def _print_banner(public_host: str | None, port: int, password: str, root_dir: Path) -> None:
    from qrdrop.core.network import get_local_ip
    from qrdrop.core.qr import generate_qr_terminal
    from qrdrop.core.terminal import print_startup_banner

    if public_host:
        display_host, _, public_port = public_host.partition(":")
        display_port = int(public_port) if public_port else port
    else:
        display_host = get_local_ip()
        display_port = port

    network_url = f"http://{display_host}:{display_port}"
    # Percent-encode so a --password containing URL-reserved characters
    # (&, #, +, spaces, ...) survives the QR auto-login round trip.
    auth_url = f"{network_url}/?auth={quote(password, safe='')}"

    print_startup_banner(
        version=__version__,
        local_url=f"http://localhost:{display_port}",
        network_url=network_url,
        password=password,
        qr_code=generate_qr_terminal(auth_url),
        root_dir=str(root_dir),
    )


def _print_docker_public_host_warning() -> None:
    """Warn that the advertised address is the container's own bridge IP."""
    from qrdrop.core.terminal import Style, style

    print(
        style(
            "  ⚠ Running in Docker without --public-host: the Network URL and\n"
            "    QR code point at the container's internal IP and won't work\n"
            "    from other devices. Pass --public-host <LAN-IP[:port]> with\n"
            "    your machine's address, or set QRDROP_PUBLIC_HOST.",
            Style.BRIGHT_YELLOW,
        )
    )
    print()


def _redacting_log_config() -> dict:
    """uvicorn's logging config with the `?auth=<password>` value redacted."""
    from uvicorn.config import LOGGING_CONFIG

    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config.setdefault("filters", {})["redact_auth"] = {
        "()": "qrdrop.core.log_redaction.RedactAuthFilter",
    }
    for handler in log_config.get("handlers", {}).values():
        handler.setdefault("filters", []).append("redact_auth")
    return log_config


def main() -> None:
    """Main entry point for the CLI."""
    _force_utf8_console()
    args = parse_args()

    # Imported here to keep --help/--version fast.
    import uvicorn

    from qrdrop.core.network import find_available_port
    from qrdrop.core.password import generate_password
    from qrdrop.web.app import AppConfig, create_app

    root_dir = Path.cwd()
    in_docker = bool(os.environ.get("DOCKER_CONTAINER"))

    # In Docker the published port is fixed, so take the requested one as is.
    port = args.port if in_docker else find_available_port(args.port)
    password = args.password if args.password else generate_password()

    # Full modify rights by default; --upload restricts to uploads only,
    # --readonly disables all writes.
    allow_modify = not (args.upload or args.readonly)

    app = create_app(
        AppConfig(
            root_dir=root_dir,
            password=password,
            port=port,
            bind=args.bind,
            show_hidden=not args.hide_dotfiles,
            session_timeout=args.timeout,
            allow_upload=not args.readonly,
            allow_delete=allow_modify,
            allow_modify=allow_modify,
        )
    )

    if not args.quiet:
        _print_banner(args.public_host, port, password, root_dir)
        if in_docker and not args.public_host:
            _print_docker_public_host_warning()

    uvicorn.run(
        app,
        host=args.bind,
        port=port,
        log_level="warning" if args.quiet else "info",
        log_config=_redacting_log_config(),
        ws="none",
    )


if __name__ == "__main__":
    main()
