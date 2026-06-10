"""Tests for network helpers: local IP detection and port discovery."""

import socket

import pytest

from qrdrop.core import network
from qrdrop.core.network import find_available_port, get_local_ip


class TestGetLocalIp:
    def test_returns_string(self) -> None:
        ip = get_local_ip()
        assert isinstance(ip, str)
        # Either a real IP or fallback
        parts = ip.split(".")
        assert len(parts) == 4

    def test_falls_back_to_loopback_on_socket_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_args, **_kwargs):
            raise OSError("no network")

        monkeypatch.setattr(network.socket, "socket", boom)
        assert get_local_ip() == "127.0.0.1"


class TestFindAvailablePort:
    def test_returns_starting_port_if_free(self) -> None:
        # Bind a temp socket to get an OS-assigned free port, then close it
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("0.0.0.0", 0))
        port = s.getsockname()[1]
        s.close()

        assert find_available_port(port, max_attempts=5) == port

    def test_skips_busy_port(self) -> None:
        # Bind a socket so the port appears busy
        busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        busy.bind(("0.0.0.0", 0))
        busy_port = busy.getsockname()[1]
        try:
            found = find_available_port(busy_port, max_attempts=20)
            assert found != busy_port
            assert found > busy_port
        finally:
            busy.close()

    def test_raises_when_no_port_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(network, "_is_port_available", lambda _p: False)
        with pytest.raises(RuntimeError):
            find_available_port(8000, max_attempts=3)
