"""QR code generation for terminal display.

Generates ASCII/Unicode QR codes that can be displayed in the terminal
for easy mobile device access.
"""

import qrcode
from qrcode.constants import ERROR_CORRECT_L


def generate_qr_terminal(url: str) -> str:
    """Generate a QR code as ASCII art for terminal display.

    Uses Unicode block characters to create a scannable QR code
    that displays in the terminal.

    Args:
        url: The URL to encode in the QR code.

    Returns:
        str: A multi-line string containing the QR code in ASCII art.
    """
    # Create QR code with low error correction (smaller, faster to scan)
    qr = qrcode.QRCode(
        version=None,  # Auto-determine size
        error_correction=ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Get the QR code matrix
    modules = qr.get_matrix()

    # Build ASCII representation using Unicode blocks
    # We use half-height blocks to make it more compact
    # █ (full block) = black on black
    # ▀ (upper half) = black on white
    # ▄ (lower half) = white on black
    # " " (space) = white on white

    lines: list[str] = []

    # Process two rows at a time for half-height blocks
    for row_idx in range(0, len(modules), 2):
        line_parts: list[str] = []

        for col_idx in range(len(modules[row_idx])):
            top = modules[row_idx][col_idx]
            # Handle odd number of rows
            bottom = modules[row_idx + 1][col_idx] if row_idx + 1 < len(modules) else False

            if top and bottom:
                line_parts.append("█")  # Full block - both black
            elif top and not bottom:
                line_parts.append("▀")  # Upper half - top black, bottom white
            elif not top and bottom:
                line_parts.append("▄")  # Lower half - top white, bottom black
            else:
                line_parts.append(" ")  # Space - both white

        lines.append("".join(line_parts))

    return "\n".join(lines)
