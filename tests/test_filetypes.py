"""Tests for the filetype detection module."""

from datetime import UTC, datetime

from qrdrop.core.filesystem import FileEntry
from qrdrop.core.filetypes import (
    get_file_icon,
    get_syntax_class,
    is_image_file,
    is_inline_document,
    is_text_file,
)


def _entry(name: str, is_dir: bool = False) -> FileEntry:
    return FileEntry(
        name=name,
        size_bytes=0,
        size_human="-",
        mtime=datetime.now(UTC),
        is_dir=is_dir,
        is_hidden=name.startswith("."),
    )


class TestGetSyntaxClass:
    def test_python_extension(self) -> None:
        assert get_syntax_class("foo.py") == "python"

    def test_typescript_extension(self) -> None:
        assert get_syntax_class("foo.ts") == "typescript"
        assert get_syntax_class("foo.tsx") == "typescript"

    def test_unknown_extension_falls_back_to_plaintext(self) -> None:
        assert get_syntax_class("foo.xyz") == "plaintext"

    def test_no_extension_falls_back_to_plaintext(self) -> None:
        assert get_syntax_class("noext") == "plaintext"

    def test_dockerfile(self) -> None:
        assert get_syntax_class("Dockerfile") == "dockerfile"

    def test_makefile(self) -> None:
        assert get_syntax_class("Makefile") == "makefile"

    def test_pyproject_toml(self) -> None:
        assert get_syntax_class("pyproject.toml") == "toml"

    def test_case_insensitive_extension(self) -> None:
        assert get_syntax_class("FOO.PY") == "python"


class TestIsTextFile:
    def test_python_is_text(self) -> None:
        assert is_text_file("text/x-python", "foo.py") is True

    def test_text_mime_prefix(self) -> None:
        assert is_text_file("text/csv", "data.csv") is True

    def test_image_is_not_text(self) -> None:
        assert is_text_file("image/png", "x.png") is False

    def test_no_mime_uses_extension(self) -> None:
        assert is_text_file(None, "script.sh") is True

    def test_no_mime_unknown_extension(self) -> None:
        assert is_text_file(None, "binary.xyz") is False

    def test_special_filename_text(self) -> None:
        assert is_text_file(None, "Dockerfile") is True

    def test_no_extension_no_mime(self) -> None:
        assert is_text_file(None, "noextension") is False


class TestIsImageFile:
    def test_png_is_image(self) -> None:
        assert is_image_file("image/png") is True

    def test_jpeg_is_image(self) -> None:
        assert is_image_file("image/jpeg") is True

    def test_text_is_not_image(self) -> None:
        assert is_image_file("text/plain") is False

    def test_none_mime(self) -> None:
        assert is_image_file(None) is False

    def test_unknown_image_type_not_viewable(self) -> None:
        assert is_image_file("image/heic") is False


class TestIsInlineDocument:
    def test_pdf_is_inline(self) -> None:
        assert is_inline_document("application/pdf") is True

    def test_zip_is_not_inline(self) -> None:
        assert is_inline_document("application/zip") is False

    def test_none(self) -> None:
        assert is_inline_document(None) is False


class TestGetFileIcon:
    def test_directory_icon(self) -> None:
        icon = get_file_icon(_entry("any", is_dir=True))
        # folder emoji
        assert icon == "\U0001f4c1"

    def test_python_file_icon(self) -> None:
        # code icon
        assert get_file_icon(_entry("foo.py")) == "\U0001f4bb"

    def test_unknown_extension_uses_default(self) -> None:
        assert get_file_icon(_entry("file.xyzz")) == "\U0001f4c4"

    def test_no_extension_uses_default(self) -> None:
        assert get_file_icon(_entry("noext")) == "\U0001f4c4"
