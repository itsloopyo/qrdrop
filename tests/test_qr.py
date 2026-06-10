"""Tests for QR code generation."""

from qrdrop.core.qr import generate_qr_terminal


class TestGenerateQrTerminal:
    """Tests for generate_qr_terminal function."""

    def test_returns_non_empty_string(self) -> None:
        """QR code generation should return a non-empty string."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_qr_block_characters(self) -> None:
        """QR code should contain Unicode block characters."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)

        block_chars = {"█", "▀", "▄", " "}
        result_chars = set(result.replace("\n", ""))

        assert result_chars.issubset(block_chars), (
            f"QR contains unexpected characters: {result_chars - block_chars}"
        )

    def test_multiple_lines(self) -> None:
        """QR code should have multiple lines."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)
        lines = result.split("\n")
        assert len(lines) > 5, "QR code should have multiple lines"

    def test_consistent_line_width(self) -> None:
        """All lines should have the same width."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)
        lines = result.split("\n")

        widths = [len(line) for line in lines if line]
        assert len(set(widths)) == 1, "All lines should have the same width"

    def test_encodes_short_url(self) -> None:
        """Should encode a short URL successfully."""
        url = "http://a.co"
        result = generate_qr_terminal(url)
        assert len(result) > 0
        lines = result.split("\n")
        assert len(lines) >= 5

    def test_encodes_long_url(self) -> None:
        """Should encode a long URL with query parameters."""
        url = "http://192.168.1.100:8000/?auth=apple-banana-cherry"
        result = generate_qr_terminal(url)
        assert len(result) > 0
        lines = result.split("\n")
        assert len(lines) >= 10

    def test_different_urls_produce_different_codes(self) -> None:
        """Different URLs should produce different QR codes."""
        url1 = "http://localhost:8000"
        url2 = "http://localhost:9000"

        result1 = generate_qr_terminal(url1)
        result2 = generate_qr_terminal(url2)

        assert result1 != result2

    def test_finder_patterns_present(self) -> None:
        """QR code should contain the characteristic finder patterns."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)

        assert "█" in result, "QR code should contain full blocks"
        assert "▀" in result or "▄" in result, "QR code should contain half blocks"


class TestQrCodeScannability:
    """Tests to ensure QR codes are likely scannable."""

    def test_minimum_size_for_scannability(self) -> None:
        """QR code should be large enough to be scannable."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)
        lines = result.split("\n")

        min_size = 11
        assert len(lines) >= min_size, f"QR code should have at least {min_size} lines"
        assert len(lines[0]) >= min_size, f"QR code should be at least {min_size} characters wide"

    def test_has_quiet_zone(self) -> None:
        """QR code should have a quiet zone (border of spaces)."""
        url = "http://localhost:8000"
        result = generate_qr_terminal(url)
        lines = result.split("\n")

        first_line = lines[0]
        last_line = lines[-1]

        assert first_line.strip(" ▀") == "" or " " in first_line, "Should have quiet zone at top"
        assert last_line.strip(" ▄") == "" or " " in last_line, "Should have quiet zone at bottom"

    def test_encodes_complex_auth_url(self) -> None:
        """Should properly encode a typical auth URL with password."""
        url = "http://192.168.1.100:8000/?auth=apple-tiger-cloud"
        result = generate_qr_terminal(url)

        assert len(result) > 0
        lines = result.split("\n")
        assert len(lines) >= 10

        widths = [len(line) for line in lines if line]
        assert len(set(widths)) == 1
