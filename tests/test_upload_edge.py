"""Edge-case and failure-path tests for the upload handlers.

The happy paths and basic validation live in ``test_upload.py``. This module
exercises the harder-to-reach branches: write failures, the
non-writable-directory guard, and the per-file error reporting in the multi
and check handlers.
"""

import asyncio
import io
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app
from qrdrop.web.handlers import upload as upload_module


def _make_client(temp_directory: Path) -> TestClient:
    config = AppConfig(
        root_dir=temp_directory,
        password="pw",
        port=8000,
        bind="127.0.0.1",
        show_hidden=True,
        session_timeout=3600,
        allow_upload=True,
    )
    client = TestClient(create_app(config), follow_redirects=False)
    client.post("/login", data={"password": "pw", "next": "/"})
    return client


class TestWriteFailure:
    def test_write_oserror_returns_500_and_cleans_up(
        self, temp_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(upload_module.aiofiles, "open", boom)
        client = _make_client(temp_directory)
        r = client.post("/upload", files={"file": ("doomed.txt", b"data")})
        assert r.status_code == 500
        assert r.json()["success"] is False
        assert not (temp_directory / "doomed.txt").exists()


class TestWritableGuard:
    def test_non_writable_directory_returns_403(
        self, temp_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("os.access", lambda _path, _mode: False)
        client = _make_client(temp_directory)
        r = client.post("/upload", files={"file": ("x.txt", b"hi")})
        assert r.status_code == 403
        assert "writable" in r.json()["error"].lower()


class TestMissingFile:
    def test_no_file_field_returns_400(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory)
        # A multipart form with a non-file field and no "file" part.
        r = client.post("/upload", data={"notafile": "value"})
        assert r.status_code == 400
        assert r.json()["success"] is False


class TestMultipleUpload:
    def test_invalid_filename_is_reported_per_file(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory)
        r = client.post(
            "/upload-multiple",
            files=[
                ("files", ("good.txt", b"ok")),
                ("files", ("..", b"evil")),
            ],
        )
        assert r.status_code == 200
        body = r.json()
        assert body["successful"] == 1
        assert body["failed"] == 1
        assert body["success"] is False
        outcomes = {item.get("filename"): item for item in body["results"]}
        assert outcomes["good.txt"]["success"] is True
        # The "filename" key for the bad entry is the raw, unsanitized name.
        assert any(not item["success"] for item in body["results"])

    def test_existing_file_conflict_reported_without_overwrite(self, temp_directory: Path) -> None:
        (temp_directory / "dup.txt").write_text("original")
        client = _make_client(temp_directory)
        r = client.post(
            "/upload-multiple",
            files=[("files", ("dup.txt", b"new"))],
        )
        body = r.json()
        assert body["failed"] == 1
        entry = body["results"][0]
        assert entry["exists"] is True
        # Existing content is preserved when overwrite isn't requested.
        assert (temp_directory / "dup.txt").read_text() == "original"


class TestCheckUpload:
    def test_reports_existence(self, temp_directory: Path) -> None:
        (temp_directory / "here.txt").write_text("x")
        client = _make_client(temp_directory)
        r = client.post(
            "/upload-check",
            json={"path": "", "filenames": ["here.txt", "absent.txt"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["files"]["here.txt"]["exists"] is True
        assert body["files"]["absent.txt"]["exists"] is False

    def test_invalid_filename_marked_invalid(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory)
        r = client.post(
            "/upload-check",
            json={"path": "", "filenames": ["..", "ok.txt"]},
        )
        body = r.json()
        assert body["files"][".."]["valid"] is False
        assert body["files"]["ok.txt"]["valid"] is True

    def test_non_string_filename_is_skipped(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory)
        r = client.post(
            "/upload-check",
            json={"path": "", "filenames": [123, "real.txt"]},
        )
        body = r.json()
        # The integer entry never makes it into the results map.
        assert "123" not in body["files"]
        assert "real.txt" in body["files"]


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation not supported in this environment")


class TestSymlinkTargets:
    def test_upload_through_dangling_symlink_is_rejected(self, tmp_path: Path) -> None:
        """A dangling symlink passes exists()==False; writing through it would
        create a file outside the served root."""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        _symlink_or_skip(root / "trap.txt", outside)

        client = _make_client(root)
        r = client.post("/upload", files={"file": ("trap.txt", b"escaped")})
        assert r.status_code == 403
        assert not outside.exists()

    def test_overwrite_through_symlink_is_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("original")
        _symlink_or_skip(root / "trap.txt", outside)

        client = _make_client(root)
        r = client.post(
            "/upload",
            files={"file": ("trap.txt", b"clobbered")},
            data={"overwrite": "true"},
        )
        assert r.status_code == 403
        assert outside.read_text() == "original"

    def test_multi_upload_symlink_reported_per_file(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        _symlink_or_skip(root / "trap.txt", tmp_path / "elsewhere.txt")

        client = _make_client(root)
        r = client.post(
            "/upload-multiple",
            files=[("files", ("trap.txt", b"x")), ("files", ("fine.txt", b"y"))],
            data={"overwrite": "true"},
        )
        body = r.json()
        outcomes = {item["filename"]: item for item in body["results"]}
        assert outcomes["trap.txt"]["success"] is False
        assert outcomes["fine.txt"]["success"] is True
        assert not (tmp_path / "elsewhere.txt").exists()


class TestCreateRace:
    def test_lost_creation_race_reports_exists(self, tmp_path: Path) -> None:
        """If the file appears between the exists() pre-check and the open,
        the no-overwrite open must fail atomically instead of truncating."""
        target = tmp_path / "raced.txt"
        target.write_text("first writer")
        upload = UploadFile(file=io.BytesIO(b"second writer"), filename="raced.txt")
        result = asyncio.run(
            upload_module._write_upload_file(upload, target, tmp_path, overwrite=False)
        )
        assert result.success is False
        assert result.exists is True
        assert target.read_text() == "first writer"
