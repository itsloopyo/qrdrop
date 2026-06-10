"""Command-line interface for qrdrop."""

import argparse
import os
from pathlib import Path

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
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Allow file uploads",
    )
    parser.add_argument(
        "--modify",
        action="store_true",
        help="Allow uploads, deletions, and directory create/rename (implies --upload)",
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


def main() -> None:
    """Main entry point for the CLI."""
    args = parse_args()

    # Import here to avoid circular imports and speed up --help/--version
    from qrdrop.core.network import find_available_port, get_local_ip
    from qrdrop.core.password import generate_password
    from qrdrop.core.qr import generate_qr_terminal
    from qrdrop.core.terminal import Style, print_startup_banner, style
    from qrdrop.web.app import AppConfig, create_app

    # Get root directory
    root_dir = Path.cwd()

    # In Docker, use the exact port specified (don't auto-increment)
    # Outside Docker, find an available port
    port = args.port if os.environ.get("DOCKER_CONTAINER") else find_available_port(args.port)

    # Generate or use provided password
    password = args.password if args.password else generate_password()

    # Determine permissions (--modify implies --upload)
    allow_upload = args.upload or args.modify
    allow_delete = args.modify
    allow_modify = args.modify

    # Create configuration
    config = AppConfig(
        root_dir=root_dir,
        password=password,
        port=port,
        bind=args.bind,
        show_hidden=not args.hide_dotfiles,
        session_timeout=args.timeout,
        allow_upload=allow_upload,
        allow_delete=allow_delete,
        allow_modify=allow_modify,
    )

    # Create app
    app = create_app(config)

    # Print startup banner
    if not args.quiet:
        from urllib.parse import quote

        if args.public_host:
            display_host, _, public_port = args.public_host.partition(":")
            display_port = int(public_port) if public_port else port
        else:
            display_host = get_local_ip()
            display_port = port

        local_url = f"http://localhost:{display_port}"
        network_url = f"http://{display_host}:{display_port}"
        # Percent-encode so a --password containing URL-reserved characters
        # (&, #, +, spaces, ...) survives the QR auto-login round trip.
        auth_url = f"http://{display_host}:{display_port}/?auth={quote(password, safe='')}"

        qr_code = generate_qr_terminal(auth_url)

        print_startup_banner(
            version=__version__,
            local_url=local_url,
            network_url=network_url,
            password=password,
            qr_code=qr_code,
            root_dir=str(root_dir),
        )

        # A container only sees its own bridge IP, so without an explicit
        # public host the QR code points somewhere no other device can reach.
        if os.environ.get("DOCKER_CONTAINER") and not args.public_host:
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

    # Start server
    import copy

    import uvicorn
    from uvicorn.config import LOGGING_CONFIG

    # Wire a redaction filter into uvicorn's logging config so the
    # `?auth=<password>` query parameter never leaks into access logs.
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config.setdefault("filters", {})["redact_auth"] = {
        "()": "qrdrop.core.log_redaction.RedactAuthFilter",
    }
    for handler in log_config.get("handlers", {}).values():
        handler.setdefault("filters", []).append("redact_auth")

    uvicorn.run(
        app,
        host=args.bind,
        port=port,
        log_level="warning" if args.quiet else "info",
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
