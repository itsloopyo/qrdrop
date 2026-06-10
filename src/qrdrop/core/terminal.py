"""Terminal output formatting and styling.

Provides styled terminal output with ANSI color support
for the startup banner and QR code display.
"""

import os
import sys


def supports_color() -> bool:
    """Check if the terminal supports ANSI colors.

    Returns:
        bool: True if colors are likely supported.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True

    # Check if stdout is a TTY
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False

    # Check TERM environment variable
    term = os.environ.get("TERM", "")
    return term != "dumb"


class Style:
    """ANSI escape codes for terminal styling."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


def style(text: str, *styles: str, use_color: bool | None = None) -> str:
    """Apply ANSI styles to text.

    Args:
        text: The text to style.
        *styles: One or more Style.* codes to apply.
        use_color: Override color detection. None uses auto-detection.

    Returns:
        str: The styled text, or plain text if colors not supported.
    """
    if use_color is None:
        use_color = supports_color()

    if not use_color or not styles:
        return text

    return "".join(styles) + text + Style.RESET


def print_startup_banner(
    version: str,
    local_url: str,
    network_url: str,
    password: str,
    qr_code: str,
    root_dir: str,
) -> None:
    """Print the styled startup banner with QR code.

    Args:
        version: The application version string.
        local_url: The localhost URL.
        network_url: The network URL.
        password: The generated password.
        qr_code: The QR code as ASCII art string.
        root_dir: The root directory being served.
    """
    use_color = supports_color()

    # Header
    print()
    print(style("╭" + "─" * 50 + "╮", Style.DIM, use_color=use_color))
    print(
        style("│", Style.DIM, use_color=use_color)
        + style("  📂 QRDrop ", Style.BOLD, Style.CYAN, use_color=use_color)
        + style(f"v{version}", Style.DIM, use_color=use_color)
        + " " * (38 - len(version))
        + style("│", Style.DIM, use_color=use_color)
    )
    print(style("╰" + "─" * 50 + "╯", Style.DIM, use_color=use_color))
    print()

    # Server info
    print(
        style("  Serving: ", Style.DIM, use_color=use_color)
        + style(root_dir, Style.WHITE, use_color=use_color)
    )
    print()

    # URLs with labels
    print(
        style("  Local:    ", Style.DIM, use_color=use_color)
        + style(local_url, Style.BRIGHT_GREEN, use_color=use_color)
    )
    print(
        style("  Network:  ", Style.DIM, use_color=use_color)
        + style(network_url, Style.BRIGHT_GREEN, use_color=use_color)
    )
    print()

    # Password with emphasis
    print(
        style("  Password: ", Style.DIM, use_color=use_color)
        + style(password, Style.BOLD, Style.BRIGHT_YELLOW, use_color=use_color)
    )
    print()

    # QR code section
    print(style("  ┌─ Scan for instant access ─┐", Style.DIM, use_color=use_color))
    print()

    # Print QR code with indentation
    for line in qr_code.split("\n"):
        print("    " + line)

    print()
    print(style("  └" + "─" * 27 + "┘", Style.DIM, use_color=use_color))
    print()

    # Help hint
    print(
        style(
            "  Press Ctrl+C to stop the server",
            Style.DIM,
            use_color=use_color,
        )
    )
    print()
