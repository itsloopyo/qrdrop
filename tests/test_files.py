"""Tests for file viewing, download handlers, and sorting."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.core.filesystem import FileEntry, sort_entries
from qrdrop.core.filetypes import is_binary_content


class TestIsBinaryContent:
    """Unit tests for binary content detection."""

    def test_empty_content_is_not_binary(self) -> None:
        """Empty content should be treated as text."""
        assert is_binary_content(b"") is False

    def test_plain_text_is_not_binary(self) -> None:
        """Plain ASCII text should not be detected as binary."""
        assert is_binary_content(b"Hello, World!") is False

    def test_utf8_text_is_not_binary(self) -> None:
        """UTF-8 encoded text should not be detected as binary."""
        assert is_binary_content("Привет мир! 你好世界!".encode()) is False

    def test_multiline_text_is_not_binary(self) -> None:
        """Multiline text with various whitespace should not be binary."""
        content = b"line 1\nline 2\r\nline 3\ttabbed"
        assert is_binary_content(content) is False

    def test_null_byte_is_binary(self) -> None:
        """Content with null bytes should be detected as binary."""
        assert is_binary_content(b"hello\x00world") is True

    def test_binary_file_header_is_binary(self) -> None:
        """Common binary file headers should be detected as binary."""
        # PNG header
        png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        assert is_binary_content(png_header) is True

        # ELF header (Linux executable)
        elf_header = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        assert is_binary_content(elf_header) is True

        # ZIP header
        zip_header = b"PK\x03\x04\x00\x00\x00\x00"
        assert is_binary_content(zip_header) is True

    def test_single_null_byte_is_binary(self) -> None:
        """Even a single null byte should trigger binary detection."""
        assert is_binary_content(b"\x00") is True


class TestFileViewHandler:
    """Tests for file viewing with binary detection."""

    def test_view_text_file_without_extension(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        """Text file without extension should be displayed inline."""
        # Create a text file without extension
        extensionless = temp_directory / "LICENSE"
        extensionless.write_text("MIT License\n\nCopyright (c) 2024")

        response = authenticated_client.get("/view/LICENSE")

        assert response.status_code == 200
        assert b"MIT License" in response.content

    def test_view_binary_file_without_extension_redirects(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        """Binary file without extension should redirect to download."""
        # Create a binary file without extension (fake PNG)
        binary_file = temp_directory / "binary_data"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        response = authenticated_client.get("/view/binary_data")

        assert response.status_code == 302
        assert "/download/binary_data" in response.headers["location"]

    def test_view_extensionless_script(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        """Script file without extension (like shebang scripts) should display."""
        # Create a shell script without extension
        script = temp_directory / "run"
        script.write_text("#!/bin/bash\necho 'Hello'\nexit 0")

        response = authenticated_client.get("/view/run")

        assert response.status_code == 200
        assert b"#!/bin/bash" in response.content

    def test_view_makefile(self, authenticated_client: TestClient, temp_directory: Path) -> None:
        """Makefile (no extension) should be displayed as text."""
        makefile = temp_directory / "Makefile"
        makefile.write_text("all:\n\t@echo 'Building...'\n\nclean:\n\t@rm -rf build")

        response = authenticated_client.get("/view/Makefile")

        assert response.status_code == 200
        assert b"Building" in response.content

    def test_view_dockerfile(self, authenticated_client: TestClient, temp_directory: Path) -> None:
        """Dockerfile (no extension) should be displayed as text."""
        dockerfile = temp_directory / "Dockerfile"
        dockerfile.write_text("FROM python:3.11\nWORKDIR /app\nCOPY . .")

        response = authenticated_client.get("/view/Dockerfile")

        assert response.status_code == 200
        assert b"FROM python" in response.content

    def test_view_gitignore(self, authenticated_client: TestClient, temp_directory: Path) -> None:
        """Dotfiles like .gitignore should be displayed as text."""
        gitignore = temp_directory / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n.env")

        response = authenticated_client.get("/view/.gitignore")

        assert response.status_code == 200
        assert b"*.pyc" in response.content

    def test_view_empty_file_without_extension(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        """Empty file without extension should be displayed (not binary)."""
        empty_file = temp_directory / "empty"
        empty_file.write_text("")

        response = authenticated_client.get("/view/empty")

        assert response.status_code == 200


class TestFileDownloadHandler:
    """Tests for file download handler."""

    def test_download_binary_file(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        """Binary file download should have correct content-disposition."""
        binary_file = temp_directory / "data.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\x04")

        response = authenticated_client.get("/download/data.bin")

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert response.content == b"\x00\x01\x02\x03\x04"

    def test_download_text_file(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Text file download should work correctly."""
        response = authenticated_client.get("/download/test.txt")

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert b"Hello, World!" in response.content


class TestSortEntries:
    """Tests for file entry sorting functionality."""

    @pytest.fixture
    def sample_entries(self) -> list[FileEntry]:
        """Create sample file entries for testing."""
        now = datetime.now(tz=UTC)
        return [
            FileEntry("zebra.txt", 100, "100 B", now, False, False),
            FileEntry("alpha.txt", 500, "500 B", now, False, False),
            FileEntry("docs", 0, "-", now, True, False),
            FileEntry("beta.txt", 200, "200 B", now, False, False),
            FileEntry("archive", 0, "-", now, True, False),
        ]

    def test_sort_by_name_ascending(self, sample_entries: list[FileEntry]) -> None:
        """Sort by name ascending should put dirs first, then alphabetical."""
        result = sort_entries(sample_entries, sort_by="name", sort_order="asc")

        names = [e.name for e in result]
        assert names == ["archive", "docs", "alpha.txt", "beta.txt", "zebra.txt"]

    def test_sort_by_name_descending(self, sample_entries: list[FileEntry]) -> None:
        """Sort by name descending should put dirs first (reversed), then files reversed."""
        result = sort_entries(sample_entries, sort_by="name", sort_order="desc")

        names = [e.name for e in result]
        assert names == ["docs", "archive", "zebra.txt", "beta.txt", "alpha.txt"]

    def test_sort_by_size_ascending(self, sample_entries: list[FileEntry]) -> None:
        """Sort by size ascending should put dirs first, then smallest files first."""
        result = sort_entries(sample_entries, sort_by="size", sort_order="asc")

        names = [e.name for e in result]
        # Dirs first (size 0), then files by size: 100, 200, 500
        assert names[:2] == ["archive", "docs"]  # dirs (both size 0)
        assert names[2:] == ["zebra.txt", "beta.txt", "alpha.txt"]

    def test_sort_by_size_descending(self, sample_entries: list[FileEntry]) -> None:
        """Sort by size descending should put dirs first, then largest files first."""
        result = sort_entries(sample_entries, sort_by="size", sort_order="desc")

        names = [e.name for e in result]
        # Dirs always alphabetical (we don't know their size), files by size desc: 500, 200, 100
        assert names[:2] == ["archive", "docs"]  # dirs always alphabetical
        assert names[2:] == ["alpha.txt", "beta.txt", "zebra.txt"]

    def test_sort_by_modified_ascending(self) -> None:
        """Sort by modified ascending should put oldest files first."""
        old = datetime(2020, 1, 1, tzinfo=UTC)
        mid = datetime(2022, 6, 15, tzinfo=UTC)
        new = datetime(2024, 12, 1, tzinfo=UTC)

        entries = [
            FileEntry("new.txt", 100, "100 B", new, False, False),
            FileEntry("old.txt", 100, "100 B", old, False, False),
            FileEntry("folder", 0, "-", mid, True, False),
            FileEntry("mid.txt", 100, "100 B", mid, False, False),
        ]

        result = sort_entries(entries, sort_by="modified", sort_order="asc")
        names = [e.name for e in result]

        assert names[0] == "folder"  # dir first
        assert names[1:] == ["old.txt", "mid.txt", "new.txt"]

    def test_sort_by_modified_descending(self) -> None:
        """Sort by modified descending should put newest files first."""
        old = datetime(2020, 1, 1, tzinfo=UTC)
        mid = datetime(2022, 6, 15, tzinfo=UTC)
        new = datetime(2024, 12, 1, tzinfo=UTC)

        entries = [
            FileEntry("new.txt", 100, "100 B", new, False, False),
            FileEntry("old.txt", 100, "100 B", old, False, False),
            FileEntry("folder", 0, "-", mid, True, False),
            FileEntry("mid.txt", 100, "100 B", mid, False, False),
        ]

        result = sort_entries(entries, sort_by="modified", sort_order="desc")
        names = [e.name for e in result]

        assert names[0] == "folder"  # dir first
        assert names[1:] == ["new.txt", "mid.txt", "old.txt"]

    def test_default_sort_is_name_ascending(self, sample_entries: list[FileEntry]) -> None:
        """Default sort should be name ascending."""
        result = sort_entries(sample_entries)
        names = [e.name for e in result]

        assert names == ["archive", "docs", "alpha.txt", "beta.txt", "zebra.txt"]


class TestBrowseSorting:
    """Tests for browse handler sorting via query params."""

    def test_sort_query_param_name_asc(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Sort by name ascending via query parameter."""
        response = authenticated_client.get("/?sort=name&order=asc", follow_redirects=True)
        assert response.status_code == 200

    def test_sort_query_param_size_desc(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Sort by size descending via query parameter."""
        response = authenticated_client.get("/?sort=size&order=desc", follow_redirects=True)
        assert response.status_code == 200

    def test_sort_query_param_modified(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Sort by modified date via query parameter."""
        response = authenticated_client.get("/?sort=modified&order=asc", follow_redirects=True)
        assert response.status_code == 200

    def test_invalid_sort_param_defaults_to_name(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Invalid sort parameter should default to name."""
        response = authenticated_client.get("/?sort=invalid&order=asc", follow_redirects=True)
        assert response.status_code == 200

    def test_invalid_order_param_defaults_to_asc(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Invalid order parameter should default to asc."""
        response = authenticated_client.get("/?sort=name&order=invalid", follow_redirects=True)
        assert response.status_code == 200

    def test_sort_header_links_present(
        self,
        authenticated_client: TestClient,
        temp_directory: Path,  # noqa: ARG002
    ) -> None:
        """Sort header links should be present in response."""
        response = authenticated_client.get("/", follow_redirects=True)

        assert response.status_code == 200
        assert b"sort=name" in response.content
        assert b"sort=size" in response.content
        assert b"sort=modified" in response.content
