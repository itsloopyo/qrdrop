"""Tests for upload, multi-upload, and check-upload handlers."""

from pathlib import Path

from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app


def _make_client(
    temp_directory: Path, *, allow_upload: bool, allow_delete: bool = False
) -> TestClient:
    config = AppConfig(
        root_dir=temp_directory,
        password="pw",
        port=8000,
        bind="127.0.0.1",
        show_hidden=True,
        session_timeout=3600,
        allow_upload=allow_upload,
        allow_delete=allow_delete,
    )
    app = create_app(config)
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"password": "pw", "next": "/"})
    return client


class TestUploadDisabled:
    def test_upload_returns_403_when_disabled(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=False)
        r = client.post("/upload", files={"file": ("a.txt", b"hello")})
        assert r.status_code == 403
        assert r.json()["success"] is False

    def test_upload_multiple_returns_403_when_disabled(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=False)
        r = client.post(
            "/upload-multiple",
            files=[("files", ("a.txt", b"hello"))],
        )
        assert r.status_code == 403

    def test_upload_check_returns_403_when_disabled(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=False)
        r = client.post("/upload-check", json={"path": "", "filenames": ["a.txt"]})
        assert r.status_code == 403


class TestUpload:
    def test_writes_file_to_root(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post("/upload", files={"file": ("new.txt", b"payload")})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["filename"] == "new.txt"
        assert body["size"] == len(b"payload")
        assert (temp_directory / "new.txt").read_bytes() == b"payload"

    def test_upload_to_subdirectory(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload?path=subdir",
            files={"file": ("uploaded.txt", b"data")},
        )
        assert r.status_code == 200
        assert (temp_directory / "subdir" / "uploaded.txt").read_bytes() == b"data"

    def test_existing_file_without_overwrite_returns_409(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post("/upload", files={"file": ("test.txt", b"new content")})
        assert r.status_code == 409
        body = r.json()
        assert body["exists"] is True
        # Original preserved
        assert (temp_directory / "test.txt").read_text() == "Hello, World!"

    def test_overwrite_replaces_existing(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload",
            files={"file": ("test.txt", b"replaced")},
            data={"overwrite": "true"},
        )
        assert r.status_code == 200
        assert (temp_directory / "test.txt").read_bytes() == b"replaced"

    def test_filename_path_injection_stripped(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        # Filename with path components should be reduced to basename
        r = client.post("/upload", files={"file": ("../../evil.txt", b"x")})
        # Either rejected or saved as 'evil.txt' (basename only) under root
        if r.status_code == 200:
            assert (temp_directory / "evil.txt").exists()
            assert not (temp_directory.parent / "evil.txt").exists()
        else:
            assert r.status_code == 400

    def test_upload_invalid_path_returns_403(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post("/upload?path=../escape", files={"file": ("a.txt", b"x")})
        assert r.status_code == 403

    def test_upload_to_file_path_returns_400(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload?path=test.txt",
            files={"file": ("a.txt", b"x")},
        )
        assert r.status_code == 400


class TestUploadMultiple:
    def test_uploads_multiple_files(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload-multiple",
            files=[
                ("files", ("a.txt", b"AAA")),
                ("files", ("b.txt", b"BBB")),
            ],
        )
        assert r.status_code == 200
        body = r.json()
        assert body["successful"] == 2
        assert body["failed"] == 0
        assert (temp_directory / "a.txt").read_bytes() == b"AAA"
        assert (temp_directory / "b.txt").read_bytes() == b"BBB"

    def test_partial_success_records_existing_conflict(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload-multiple",
            files=[
                ("files", ("test.txt", b"will conflict")),
                ("files", ("brand-new.txt", b"ok")),
            ],
        )
        assert r.status_code == 200
        body = r.json()
        assert body["successful"] == 1
        assert body["failed"] == 1
        assert body["success"] is False
        # Conflicted file unchanged
        assert (temp_directory / "test.txt").read_text() == "Hello, World!"

    def test_no_files_returns_400(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post("/upload-multiple", data={"overwrite": "false"})
        assert r.status_code == 400


class TestUploadCheck:
    def test_reports_existing_and_missing(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload-check",
            json={"path": "", "filenames": ["test.txt", "new.txt"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["files"]["test.txt"]["exists"] is True
        assert body["files"]["new.txt"]["exists"] is False

    def test_invalid_json_returns_400(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload-check",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400

    def test_filenames_must_be_array(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload-check",
            json={"path": "", "filenames": "test.txt"},
        )
        assert r.status_code == 400

    def test_invalid_path_returns_403(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_upload=True)
        r = client.post(
            "/upload-check",
            json={"path": "../escape", "filenames": ["a.txt"]},
        )
        assert r.status_code == 403
