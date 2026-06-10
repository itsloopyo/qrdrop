"""Tests for the batch archive download handler."""

import io
import json
import tarfile
import time
import zipfile
from pathlib import Path

from starlette.testclient import TestClient


def _post_archive(client: TestClient, paths: list[str], format_type: str = "zip"):
    return client.post(
        "/download-archive",
        data={"paths": json.dumps(paths), "format": format_type},
    )


class TestArchiveHandler:
    def test_zip_single_file(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["test.txt"], "zip")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert "test.txt" in zf.namelist()
            assert zf.read("test.txt") == b"Hello, World!"

    def test_zip_directory_recursive(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["subdir"], "zip")
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
            assert any("nested.txt" in n for n in names)

    def test_tar_gz_format(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["test.txt"], "tar.gz")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/gzip"
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
            assert "test.txt" in tf.getnames()

    def test_tar_bz2_format(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["test.txt"], "tar.bz2")
        assert r.status_code == 200
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:bz2") as tf:
            assert "test.txt" in tf.getnames()

    def test_unsupported_format_returns_400(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["test.txt"], "rar")
        assert r.status_code == 400

    def test_invalid_paths_json_returns_400(self, authenticated_client: TestClient) -> None:
        r = authenticated_client.post(
            "/download-archive",
            data={"paths": "not json", "format": "zip"},
        )
        assert r.status_code == 400

    def test_empty_paths_returns_400(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, [], "zip")
        assert r.status_code == 400

    def test_path_traversal_returns_403(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["../../etc/passwd"], "zip")
        assert r.status_code == 403

    def test_nonexistent_path_returns_404(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["does-not-exist"], "zip")
        assert r.status_code == 404

    def test_empty_directory_returns_400(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "empty").mkdir()
        r = _post_archive(authenticated_client, ["empty"], "zip")
        assert r.status_code == 400

    def test_archive_filename_for_single_item(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["test.txt"], "zip")
        assert "test.txt.zip" in r.headers.get("content-disposition", "")

    def test_archive_filename_for_multiple_items(self, authenticated_client: TestClient) -> None:
        r = _post_archive(authenticated_client, ["test.txt", "readme.md"], "zip")
        assert "archive_" in r.headers.get("content-disposition", "")


class TestStreaming:
    def test_no_content_length_and_large_round_trip(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        """Archives stream chunk-by-chunk instead of buffering in memory."""
        payload = bytes(range(256)) * 8192  # 2MB, mildly compressible
        (temp_directory / "big.bin").write_bytes(payload)
        r = _post_archive(authenticated_client, ["big.bin"], "zip")
        assert r.status_code == 200
        assert "content-length" not in r.headers
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert zf.read("big.bin") == payload

    def test_tar_stream_round_trip(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "data.txt").write_text("streamed")
        r = _post_archive(authenticated_client, ["data.txt", "test.txt"], "tar.gz")
        assert r.status_code == 200
        assert "content-length" not in r.headers
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
            member = tf.extractfile("data.txt")
            assert member is not None
            assert member.read() == b"streamed"

    def test_producer_thread_stops_when_consumer_closes_early(self, temp_directory: Path) -> None:
        """An abandoned download must not leave the writer thread running."""
        import asyncio
        import threading

        from qrdrop.web.handlers import archive as archive_module

        big = temp_directory / "huge.bin"
        big.write_bytes(bytes(1024) * (8 * 1024))
        files = [(big, "huge.bin")]

        async def consume_one_chunk_then_close() -> None:
            stream = archive_module._stream_archive(files, "zip")
            await stream.__anext__()
            await stream.aclose()

        before = {t for t in threading.enumerate() if t.name == "archive-writer"}
        asyncio.run(consume_one_chunk_then_close())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            leftovers = [
                t
                for t in threading.enumerate()
                if t.name == "archive-writer" and t not in before and t.is_alive()
            ]
            if not leftovers:
                break
            time.sleep(0.05)
        assert not leftovers
