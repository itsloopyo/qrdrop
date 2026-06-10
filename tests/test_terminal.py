"""Tests for terminal output formatting."""

import os
from io import StringIO
from unittest.mock import patch

import pytest

from qrdrop.core.terminal import (
    Style,
    print_startup_banner,
    style,
    supports_color,
)


class TestSupportsColor:
    """Tests for color support detection."""

    def test_no_color_env_disables_color(self) -> None:
        """NO_COLOR environment variable should disable colors."""
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            assert supports_color() is False

    def test_force_color_env_enables_color(self) -> None:
        """FORCE_COLOR environment variable should enable colors."""
        with (
            patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True),
            patch("sys.stdout.isatty", return_value=True),
        ):
            assert supports_color() is True

    def test_dumb_terminal_disables_color(self) -> None:
        """TERM=dumb should disable colors."""
        with (
            patch.dict(os.environ, {"TERM": "dumb"}, clear=True),
            patch("sys.stdout.isatty", return_value=True),
        ):
            assert supports_color() is False


class TestStyle:
    """Tests for ANSI style constants."""

    def test_reset_code(self) -> None:
        """RESET should be the standard ANSI reset code."""
        assert Style.RESET == "\033[0m"

    def test_bold_code(self) -> None:
        """BOLD should be the standard ANSI bold code."""
        assert Style.BOLD == "\033[1m"

    def test_color_codes_start_with_escape(self) -> None:
        """All color codes should start with escape sequence."""
        colors = [
            Style.RED,
            Style.GREEN,
            Style.BLUE,
            Style.YELLOW,
            Style.CYAN,
            Style.MAGENTA,
            Style.WHITE,
            Style.BLACK,
        ]
        for color in colors:
            assert color.startswith("\033["), f"{color} should start with escape"


class TestStyleFunction:
    """Tests for the style() function."""

    def test_applies_single_style(self) -> None:
        """Should apply a single style code."""
        result = style("hello", Style.BOLD, use_color=True)
        assert result == "\033[1mhello\033[0m"

    def test_applies_multiple_styles(self) -> None:
        """Should apply multiple style codes."""
        result = style("hello", Style.BOLD, Style.RED, use_color=True)
        assert result == "\033[1m\033[31mhello\033[0m"

    def test_no_style_returns_plain_text(self) -> None:
        """Should return plain text when no styles provided."""
        result = style("hello", use_color=True)
        assert result == "hello"

    def test_color_disabled_returns_plain_text(self) -> None:
        """Should return plain text when color is disabled."""
        result = style("hello", Style.BOLD, Style.RED, use_color=False)
        assert result == "hello"

    def test_empty_string(self) -> None:
        """Should handle empty strings."""
        result = style("", Style.BOLD, use_color=True)
        assert result == "\033[1m\033[0m"

    def test_unicode_text(self) -> None:
        """Should handle Unicode text."""
        result = style("héllo 世界", Style.BOLD, use_color=True)
        assert "héllo 世界" in result


class TestPrintStartupBanner:
    """Tests for the startup banner printing."""

    @pytest.fixture
    def sample_qr_code(self) -> str:
        """Sample QR code for testing."""
        return " ▄▄▄▄▄▄▄ \n █ ▄▄▄ █ \n █ ███ █ \n █▄▄▄▄▄█ \n"

    def test_prints_version(self, sample_qr_code: str) -> None:
        """Banner should include the version."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="1.2.3",
                local_url="http://localhost:8000",
                network_url="http://192.168.1.1:8000",
                password="test-password",
                qr_code=sample_qr_code,
                root_dir="/home/user",
            )

        result = output.getvalue()
        assert "1.2.3" in result

    def test_prints_local_url(self, sample_qr_code: str) -> None:
        """Banner should include the local URL."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="0.1.0",
                local_url="http://localhost:9000",
                network_url="http://192.168.1.1:9000",
                password="test",
                qr_code=sample_qr_code,
                root_dir="/home/user",
            )

        result = output.getvalue()
        assert "http://localhost:9000" in result

    def test_prints_network_url(self, sample_qr_code: str) -> None:
        """Banner should include the network URL."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="0.1.0",
                local_url="http://localhost:8000",
                network_url="http://10.0.0.5:8000",
                password="test",
                qr_code=sample_qr_code,
                root_dir="/home/user",
            )

        result = output.getvalue()
        assert "http://10.0.0.5:8000" in result

    def test_prints_password(self, sample_qr_code: str) -> None:
        """Banner should include the password."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="0.1.0",
                local_url="http://localhost:8000",
                network_url="http://192.168.1.1:8000",
                password="apple-tiger-cloud",
                qr_code=sample_qr_code,
                root_dir="/home/user",
            )

        result = output.getvalue()
        assert "apple-tiger-cloud" in result

    def test_prints_qr_code(self, sample_qr_code: str) -> None:
        """Banner should include the QR code."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="0.1.0",
                local_url="http://localhost:8000",
                network_url="http://192.168.1.1:8000",
                password="test",
                qr_code=sample_qr_code,
                root_dir="/home/user",
            )

        result = output.getvalue()
        assert "▄▄▄▄▄▄▄" in result

    def test_prints_root_dir(self, sample_qr_code: str) -> None:
        """Banner should include the root directory."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="0.1.0",
                local_url="http://localhost:8000",
                network_url="http://192.168.1.1:8000",
                password="test",
                qr_code=sample_qr_code,
                root_dir="/path/to/files",
            )

        result = output.getvalue()
        assert "/path/to/files" in result

    def test_prints_box_characters(self, sample_qr_code: str) -> None:
        """Banner should use box-drawing characters."""
        output = StringIO()
        with patch("sys.stdout", output):
            print_startup_banner(
                version="0.1.0",
                local_url="http://localhost:8000",
                network_url="http://192.168.1.1:8000",
                password="test",
                qr_code=sample_qr_code,
                root_dir="/home/user",
            )

        result = output.getvalue()
        assert "╭" in result or "─" in result
