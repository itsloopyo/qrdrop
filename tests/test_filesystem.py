"""Tests for core filesystem operations: validation, listing, sorting, sizing."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qrdrop.core import filesystem
from qrdrop.core.filesystem import (
    FileEntry,
    PathTraversalError,
    humanize_size,
    list_directory,
    sort_entries,
    validate_path,
)


@pytest.fixture(autouse=True)
def _clear_dir_cache() -> None:
    filesystem._dir_cache.clear()


class TestHumanizeSize:
    def test_zero_bytes_renders_dash(self) -> None:
        assert humanize_size(0) == "-"

    def test_bytes_under_kb(self) -> None:
        assert humanize_size(512).endswith("B")

    def test_kilobytes(self) -> None:
        assert "KB" in humanize_size(2048)

    def test_megabytes(self) -> None:
        assert "MB" in humanize_size(5 * 1024 * 1024)

    def test_gigabytes(self) -> None:
        assert "GB" in humanize_size(3 * 1024 * 1024 * 1024)

    def test_format_precision_under_10(self) -> None:
        # 1.50 KB - two decimals when value < 10
        assert humanize_size(1536) == "1.50 KB"

    def test_format_precision_under_100(self) -> None:
        # 50 KB region - one decimal
        out = humanize_size(50 * 1024)
        assert out == "50.0 KB"

    def test_format_precision_above_100(self) -> None:
        # 500 KB - no decimals
        assert humanize_size(500 * 1024) == "500 KB"


class TestValidatePath:
    def test_root_path_returns_root(self, tmp_path: Path) -> None:
        result = validate_path(tmp_path, "")
        assert result == tmp_path.resolve()

    def test_slash_returns_root(self, tmp_path: Path) -> None:
        assert validate_path(tmp_path, "/") == tmp_path.resolve()

    def test_dot_returns_root(self, tmp_path: Path) -> None:
        assert validate_path(tmp_path, ".") == tmp_path.resolve()

    def test_resolves_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        assert validate_path(tmp_path, "sub") == sub.resolve()

    def test_strips_leading_slash(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        assert validate_path(tmp_path, "/sub") == sub.resolve()

    def test_traversal_via_dotdot_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            validate_path(tmp_path, "../../etc/passwd")

    def test_absolute_traversal_raises(self, tmp_path: Path) -> None:
        # An absolute escape attempt resolves outside root
        # Use a path that would clearly resolve outside
        with pytest.raises(PathTraversalError):
            validate_path(tmp_path, "..")

    @pytest.mark.skipif(os.name != "nt", reason="NTFS alternate data streams are Windows-only")
    def test_ads_stream_path_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("visible")
        with pytest.raises(PathTraversalError):
            validate_path(tmp_path, "file.txt:hidden")

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need admin on windows")
    def test_symlink_target_outside_root_raises(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside_target"
        outside.mkdir()
        try:
            link = tmp_path / "escape"
            link.symlink_to(outside)
            with pytest.raises(PathTraversalError):
                validate_path(tmp_path, "escape")
        finally:
            outside.rmdir() if outside.exists() else None


class TestListDirectory:
    def test_lists_files_and_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "sub").mkdir()
        names = {e.name for e in list_directory(tmp_path)}
        assert names == {"a.txt", "sub"}

    def test_excludes_hidden_when_requested(self, tmp_path: Path) -> None:
        (tmp_path / ".secret").write_text("x")
        (tmp_path / "visible.txt").write_text("y")
        names = {e.name for e in list_directory(tmp_path, show_hidden=False)}
        assert names == {"visible.txt"}

    def test_includes_hidden_when_requested(self, tmp_path: Path) -> None:
        (tmp_path / ".secret").write_text("x")
        names = {e.name for e in list_directory(tmp_path, show_hidden=True)}
        assert ".secret" in names

    def test_marks_directories_as_dir(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        entries = {e.name: e for e in list_directory(tmp_path)}
        assert entries["sub"].is_dir is True
        assert entries["sub"].size_bytes == 0

    def test_file_size_reported(self, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("hello")
        entries = {e.name: e for e in list_directory(tmp_path)}
        assert entries["f.txt"].size_bytes == len("hello")

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            list_directory(tmp_path / "nope")

    def test_path_is_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("x")
        with pytest.raises(NotADirectoryError):
            list_directory(f)

    def test_cache_returns_consistent_results(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        a = list_directory(tmp_path)
        b = list_directory(tmp_path)
        assert [e.name for e in a] == [e.name for e in b]

    def test_cache_invalidated_when_dir_mtime_changes(self, tmp_path: Path) -> None:
        list_directory(tmp_path)
        # Wait so mtime advances reliably
        time.sleep(0.05)
        (tmp_path / "new.txt").write_text("new")
        # Force mtime update (Windows sometimes lags)
        os.utime(tmp_path, None)
        entries = list_directory(tmp_path)
        assert any(e.name == "new.txt" for e in entries)


class TestSortEntriesEdgeCases:
    def _make(
        self, name: str, is_dir: bool = False, size: int = 0, mtime_ts: float = 0.0
    ) -> FileEntry:
        return FileEntry(
            name=name,
            size_bytes=size,
            size_human=humanize_size(size),
            mtime=datetime.fromtimestamp(mtime_ts or 1, tz=UTC),
            is_dir=is_dir,
            is_hidden=name.startswith("."),
        )

    def test_directories_always_first(self) -> None:
        entries = [
            self._make("zfile.txt"),
            self._make("adir", is_dir=True),
        ]
        out = sort_entries(entries, "name", "asc")
        assert [e.name for e in out] == ["adir", "zfile.txt"]

    def test_directories_first_even_when_sorted_by_size(self) -> None:
        entries = [
            self._make("big.bin", size=10_000),
            self._make("dir1", is_dir=True),
            self._make("small.bin", size=1),
        ]
        out = sort_entries(entries, "size", "asc")
        assert out[0].is_dir is True
        # Files sorted ascending
        files = [e for e in out if not e.is_dir]
        assert [f.name for f in files] == ["small.bin", "big.bin"]

    def test_sort_by_modified_desc(self) -> None:
        old = self._make("old.txt", mtime_ts=1000)
        new = self._make("new.txt", mtime_ts=2000)
        out = sort_entries([old, new], "modified", "desc")
        assert [e.name for e in out] == ["new.txt", "old.txt"]

    def test_invalid_sort_field_falls_back_to_name(self) -> None:
        entries = [self._make("b.txt"), self._make("a.txt")]
        out = sort_entries(entries, "bogus", "asc")
        assert [e.name for e in out] == ["a.txt", "b.txt"]

    def test_case_insensitive_name_sort(self) -> None:
        entries = [self._make("Banana"), self._make("apple"), self._make("Cherry")]
        out = sort_entries(entries, "name", "asc")
        assert [e.name for e in out] == ["apple", "Banana", "Cherry"]
