"""Network utility functions for IP detection and port management."""

import socket


def get_local_ip() -> str:
    """Detect the local network IP address.

    Uses a UDP socket trick to determine which interface would be used
    to reach external hosts. This works without actually sending any data.

    Returns:
        str: The local IP address, or "127.0.0.1" if detection fails.
    """
    try:
        # Create a UDP socket (doesn't actually connect)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Connect to a public IP (doesn't send anything)
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
        finally:
            sock.close()
        return local_ip
    except OSError:
        return "127.0.0.1"


def find_available_port(start_port: int, max_attempts: int = 100) -> int:
    """Find an available port starting from the given port.

    If the requested port is in use, increments until an available port is found.

    Args:
        start_port: The port to try first.
        max_attempts: Maximum number of ports to try (default 100).

    Returns:
        int: An available port number.

    Raises:
        RuntimeError: If no available port is found within max_attempts.
    """
    for offset in range(max_attempts):
        port = start_port + offset
        if _is_port_available(port):
            return port

    raise RuntimeError(
        f"Could not find available port after {max_attempts} attempts "
        f"starting from port {start_port}"
    )


def _is_port_available(port: int) -> bool:
    """Check if a port is available for binding.

    Args:
        port: The port number to check.

    Returns:
        bool: True if the port is available, False otherwise.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", port))
            return True
        finally:
            sock.close()
    except OSError:
        return False
