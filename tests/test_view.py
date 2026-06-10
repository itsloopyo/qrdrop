"""Tests for the file view and download handlers.

Covers the routing decisions in ``view_handler`` (text vs. image vs. inline
PDF vs. download redirect, plus the not-found / access-denied / directory /
oversize branches) and the equivalent error paths in ``download_handler``.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.handlers import files as files_module

# Smallest bytes that mimetypes + the browser will treat as a real PDF/PNG.
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


class TestViewRouting:
    def test_text_file_renders_inline(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/view/test.txt")
        assert resp.status_code == 200
        assert "Hello, World!" in resp.text

    def test_image_renders_image_template(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "pic.png").write_bytes(MINIMAL_PNG)
        resp = authenticated_client.get("/view/pic.png")
        assert resp.status_code == 200
        # view_image.html embeds the raw download URL for the <img> src.
        assert "pic.png" in resp.text

    def test_pdf_streams_inline(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "doc.pdf").write_bytes(MINIMAL_PDF)
        resp = authenticated_client.get("/view/doc.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert "inline" in resp.headers["content-disposition"]
        assert resp.content == MINIMAL_PDF

    def test_binary_file_redirects_to_download(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "blob.bin").write_bytes(b"\x00\x01\x02\x03binary")
        resp = authenticated_client.get("/view/blob.bin")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/download/blob.bin"

    def test_directory_redirects_to_browse(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/view/subdir")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/browse/subdir"

    def test_oversize_file_redirects_to_download(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(files_module, "MAX_VIEW_SIZE", 4)
        (temp_directory / "big.txt").write_text("way over the tiny limit")
        resp = authenticated_client.get("/view/big.txt")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/download/big.txt"

    def test_nonexistent_returns_404(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/view/does-not-exist.txt")
        assert resp.status_code == 404

    def test_path_traversal_returns_403(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/view/..%2f..%2fetc%2fpasswd")
        assert resp.status_code == 403


class TestDownloadRouting:
    def test_download_streams_with_attachment_disposition(
        self, authenticated_client: TestClient
    ) -> None:
        resp = authenticated_client.get("/download/test.txt")
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.content == b"Hello, World!"
        assert resp.headers["content-length"] == str(len(b"Hello, World!"))

    def test_download_unknown_extension_defaults_octet_stream(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "mystery.xyzzy").write_bytes(b"data")
        resp = authenticated_client.get("/download/mystery.xyzzy")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/octet-stream")

    def test_download_directory_redirects_to_browse(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/download/subdir")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/browse/subdir"

    def test_download_nonexistent_returns_404(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/download/nope.txt")
        assert resp.status_code == 404

    def test_download_path_traversal_returns_403(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/download/..%2f..%2fsecret")
        assert resp.status_code == 403


class TestContentDisposition:
    def test_unicode_filename_gets_utf8_star_parameter(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "naïve-café.txt").write_text("unicode name")
        resp = authenticated_client.get("/download/na%C3%AFve-caf%C3%A9.txt")
        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        # RFC 6266: percent-encoded UTF-8 form is present for unicode survival.
        assert "filename*=UTF-8''" in disposition
