"""Tests for directory creation and rename handlers (--modify)."""

from collections.abc import Generator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app


def _build_client(temp_directory: Path, *, allow_modify: bool) -> TestClient:
    """Create an authenticated test client with a given modify permission.

    Args:
        temp_directory: The root directory to serve.
        allow_modify: Whether create/rename operations are permitted.

    Returns:
        TestClient: An authenticated Starlette test client.
    """
    config = AppConfig(
        root_dir=temp_directory,
        password="test-password",
        port=8000,
        bind="127.0.0.1",
        show_hidden=True,
        session_timeout=3600,
        allow_modify=allow_modify,
    )
    client = TestClient(create_app(config), follow_redirects=False)
    client.post("/login", data={"password": config.password, "next": "/"})
    return client


@pytest.fixture
def modify_client(temp_directory: Path) -> Generator[TestClient, None, None]:
    """Authenticated client with modifications enabled."""
    with _build_client(temp_directory, allow_modify=True) as client:
        yield client


@pytest.fixture
def readonly_client(temp_directory: Path) -> Generator[TestClient, None, None]:
    """Authenticated client with modifications disabled."""
    with _build_client(temp_directory, allow_modify=False) as client:
        yield client


class TestMkdirHandler:
    """Tests for the directory creation handler."""

    def test_create_folder_at_root(self, modify_client: TestClient, temp_directory: Path) -> None:
        """A new folder should be created in the root directory."""
        response = modify_client.post("/mkdir", json={"path": "", "name": "newdir"})

        assert response.status_code == 200
        assert response.json() == {"success": True, "path": "newdir"}
        assert (temp_directory / "newdir").is_dir()

    def test_create_folder_in_subdirectory(
        self, modify_client: TestClient, temp_directory: Path
    ) -> None:
        """A new folder should be created inside an existing subdirectory."""
        response = modify_client.post("/mkdir", json={"path": "subdir", "name": "child"})

        assert response.status_code == 200
        assert (temp_directory / "subdir" / "child").is_dir()

    def test_create_folder_forbidden_without_permission(self, readonly_client: TestClient) -> None:
        """Creating a folder should be rejected when --modify is off."""
        response = readonly_client.post("/mkdir", json={"path": "", "name": "newdir"})

        assert response.status_code == 403
        assert response.json()["success"] is False

    def test_create_folder_already_exists(self, modify_client: TestClient) -> None:
        """Creating a folder that already exists should return 409."""
        response = modify_client.post("/mkdir", json={"path": "", "name": "subdir"})

        assert response.status_code == 409
        body = response.json()
        assert body["success"] is False
        assert body["exists"] is True

    def test_create_folder_missing_name(self, modify_client: TestClient) -> None:
        """Creating a folder without a name should return 400."""
        response = modify_client.post("/mkdir", json={"path": ""})

        assert response.status_code == 400
        assert response.json()["success"] is False

    @pytest.mark.parametrize("name", ["..", ".", ""])
    def test_create_folder_rejects_reserved_names(
        self, modify_client: TestClient, name: str
    ) -> None:
        """Reserved or empty directory names must be rejected."""
        response = modify_client.post("/mkdir", json={"path": "", "name": name})

        assert response.status_code == 400
        assert response.json()["success"] is False

    def test_create_folder_strips_path_components(
        self, modify_client: TestClient, temp_directory: Path
    ) -> None:
        """A name containing path separators is reduced to its basename."""
        response = modify_client.post("/mkdir", json={"path": "", "name": "../escape"})

        assert response.status_code == 200
        # Only the basename is used, so the directory stays inside root
        assert (temp_directory / "escape").is_dir()
        assert not (temp_directory.parent / "escape").exists()

    def test_create_folder_invalid_parent(self, modify_client: TestClient) -> None:
        """Creating a folder under a non-existent parent should fail."""
        response = modify_client.post("/mkdir", json={"path": "nope", "name": "child"})

        assert response.status_code in (400, 403)
        assert response.json()["success"] is False

    def test_create_folder_invalid_json(self, modify_client: TestClient) -> None:
        """A malformed JSON body should return 400."""
        response = modify_client.post(
            "/mkdir",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["success"] is False


class TestRenameHandler:
    """Tests for the rename handler."""

    def test_rename_file(self, modify_client: TestClient, temp_directory: Path) -> None:
        """A file should be renamed within its directory."""
        response = modify_client.post(
            "/rename", json={"path": "test.txt", "new_name": "renamed.txt"}
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "path": "renamed.txt"}
        assert not (temp_directory / "test.txt").exists()
        assert (temp_directory / "renamed.txt").read_text() == "Hello, World!"

    def test_rename_directory(self, modify_client: TestClient, temp_directory: Path) -> None:
        """A directory should be renamed, preserving its contents."""
        response = modify_client.post("/rename", json={"path": "subdir", "new_name": "renamed_dir"})

        assert response.status_code == 200
        assert (temp_directory / "renamed_dir" / "nested.txt").exists()

    def test_rename_forbidden_without_permission(self, readonly_client: TestClient) -> None:
        """Renaming should be rejected when --modify is off."""
        response = readonly_client.post(
            "/rename", json={"path": "test.txt", "new_name": "renamed.txt"}
        )

        assert response.status_code == 403
        assert response.json()["success"] is False

    def test_rename_not_found(self, modify_client: TestClient) -> None:
        """Renaming a non-existent entry should return 404."""
        response = modify_client.post("/rename", json={"path": "missing.txt", "new_name": "x.txt"})

        assert response.status_code == 404
        assert response.json()["success"] is False

    def test_rename_target_exists(self, modify_client: TestClient) -> None:
        """Renaming onto an existing entry should return 409."""
        response = modify_client.post("/rename", json={"path": "test.txt", "new_name": "readme.md"})

        assert response.status_code == 409
        body = response.json()
        assert body["success"] is False
        assert body["exists"] is True

    def test_rename_root_forbidden(self, modify_client: TestClient) -> None:
        """Renaming the root directory must be rejected."""
        response = modify_client.post("/rename", json={"path": "", "new_name": "x"})

        assert response.status_code == 403
        assert response.json()["success"] is False

    def test_rename_unchanged_name(self, modify_client: TestClient) -> None:
        """Renaming to the same name should return 400."""
        response = modify_client.post("/rename", json={"path": "test.txt", "new_name": "test.txt"})

        assert response.status_code == 400
        assert response.json()["success"] is False

    @pytest.mark.parametrize("new_name", ["..", ".", ""])
    def test_rename_rejects_invalid_names(self, modify_client: TestClient, new_name: str) -> None:
        """Reserved or empty target names must be rejected."""
        response = modify_client.post("/rename", json={"path": "test.txt", "new_name": new_name})

        assert response.status_code == 400
        assert response.json()["success"] is False

    def test_rename_strips_path_components(
        self, modify_client: TestClient, temp_directory: Path
    ) -> None:
        """A new name containing path separators is reduced to its basename."""
        response = modify_client.post(
            "/rename", json={"path": "test.txt", "new_name": "../escaped.txt"}
        )

        assert response.status_code == 200
        # Only the basename is used, so the file stays inside root
        assert (temp_directory / "escaped.txt").exists()
        assert not (temp_directory.parent / "escaped.txt").exists()
