"""File type detection and classification.

Centralizes all file type knowledge: MIME classification, extension-to-syntax
mappings, icon assignments, and binary/text detection. Used by both the browse
handler (icons) and the file view handler (syntax highlighting, type routing).
"""

from qrdrop.core.filesystem import FileEntry

# --- MIME type classification sets ---

VIEWABLE_TEXT_TYPES: set[str] = {
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "text/markdown",
    "text/x-python",
    "text/x-java-source",
    "text/x-c",
    "text/x-c++",
    "text/x-go",
    "text/x-rust",
    "text/x-ruby",
    "text/x-shellscript",
    "text/xml",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-yaml",
    "application/toml",
}

VIEWABLE_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/x-icon",
}

INLINE_DOCUMENT_TYPES: set[str] = {
    "application/pdf",
}

# --- Extension and filename lookup tables ---

# Special filenames without extensions - module-level for O(1) lookup
_SPECIAL_FILENAME_MAP: dict[str, str] = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "makefile": "makefile",
    "gnumakefile": "makefile",
    "cmakelists.txt": "cmake",
    "vagrantfile": "ruby",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "brewfile": "ruby",
    "procfile": "yaml",
    "jenkinsfile": "groovy",
    ".gitignore": "ini",
    ".gitattributes": "ini",
    ".gitmodules": "ini",
    ".dockerignore": "ini",
    ".editorconfig": "ini",
    ".npmrc": "ini",
    ".prettierrc": "json",
    ".eslintrc": "json",
    ".babelrc": "json",
    "tsconfig.json": "json",
    "package.json": "json",
    "composer.json": "json",
    "cargo.toml": "toml",
    "pyproject.toml": "toml",
    "go.mod": "go",
    "go.sum": "plaintext",
    "requirements.txt": "plaintext",
    "constraints.txt": "plaintext",
}

# Canonical per-extension descriptor: each entry says (a) the syntax-highlighter
# class to use when rendering inline (None = no highlighter / not text) and
# (b) whether the extension qualifies the file as inline-viewable text by name
# alone. Some entries have a syntax class but `text=False` because they map
# to languages we don't currently surface in the inline viewer; new extensions
# must make both choices explicitly so the two questions can't drift.
_EXTENSION_INFO: dict[str, tuple[str | None, bool]] = {
    # Python
    ".py": ("python", True),
    ".pyw": ("python", False),
    ".pyi": ("python", False),
    # JavaScript/TypeScript
    ".js": ("javascript", True),
    ".mjs": ("javascript", True),
    ".jsx": ("javascript", True),
    ".ts": ("typescript", True),
    ".tsx": ("typescript", True),
    # Web
    ".html": ("html", True),
    ".htm": ("html", True),
    ".css": ("css", True),
    ".scss": ("scss", True),
    ".sass": ("sass", True),
    ".less": ("less", True),
    # Data formats
    ".json": ("json", True),
    ".xml": ("xml", True),
    ".yaml": ("yaml", True),
    ".yml": ("yaml", True),
    ".toml": ("toml", True),
    ".lock": ("toml", True),
    # Systems
    ".c": ("c", True),
    ".h": ("c", True),
    ".cpp": ("cpp", True),
    ".hpp": ("cpp", True),
    ".cc": ("cpp", True),
    ".cxx": ("cpp", False),
    ".go": ("go", True),
    ".rs": ("rust", True),
    ".rb": ("ruby", True),
    ".java": ("java", True),
    ".kt": ("kotlin", True),
    ".swift": ("swift", True),
    ".php": ("php", True),
    ".cs": ("csharp", True),
    ".fs": ("fsharp", False),
    # Shell
    ".sh": ("bash", True),
    ".bash": ("bash", True),
    ".zsh": ("bash", True),
    ".fish": ("fish", True),
    ".ps1": ("powershell", True),
    ".bat": ("batch", True),
    ".cmd": ("batch", False),
    # Markup
    ".md": ("markdown", True),
    ".markdown": ("markdown", True),
    ".rst": ("rst", True),
    ".tex": ("latex", False),
    # Config
    ".ini": ("ini", True),
    ".conf": ("ini", True),
    ".cfg": ("ini", True),
    ".env": ("ini", True),
    ".properties": ("properties", False),
    # Other
    ".sql": ("sql", True),
    ".dockerfile": ("dockerfile", True),
    ".makefile": ("makefile", True),
    ".cmake": ("cmake", True),
    ".gradle": ("groovy", False),
    ".lua": ("lua", False),
    ".perl": ("perl", False),
    ".pl": ("perl", False),
    ".r": ("r", False),
    ".scala": ("scala", False),
    ".vim": ("vim", False),
    # Plain-text extensions with no syntax highlighter
    ".txt": (None, True),
    ".log": (None, True),
    ".gitignore": (None, True),
    ".gitattributes": (None, True),
    ".editorconfig": (None, True),
}

_SYNTAX_CLASS_MAP: dict[str, str] = {
    ext: syntax for ext, (syntax, _) in _EXTENSION_INFO.items() if syntax is not None
}
_TEXT_FILE_EXTENSIONS: frozenset[str] = frozenset(
    ext for ext, (_, is_text) in _EXTENSION_INFO.items() if is_text
)

# File extension to icon mappings - pre-computed for O(1) lookup
_EXTENSION_ICONS: dict[str, str] = {
    # Documents
    ".pdf": "\U0001f4c4",
    ".doc": "\U0001f4dd",
    ".docx": "\U0001f4dd",
    ".odt": "\U0001f4dd",
    ".rtf": "\U0001f4dd",
    ".xls": "\U0001f4ca",
    ".xlsx": "\U0001f4ca",
    ".ods": "\U0001f4ca",
    ".csv": "\U0001f4ca",
    ".ppt": "\U0001f4fd\ufe0f",
    ".pptx": "\U0001f4fd\ufe0f",
    ".odp": "\U0001f4fd\ufe0f",
    # Images
    ".jpg": "\U0001f5bc\ufe0f",
    ".jpeg": "\U0001f5bc\ufe0f",
    ".png": "\U0001f5bc\ufe0f",
    ".gif": "\U0001f5bc\ufe0f",
    ".bmp": "\U0001f5bc\ufe0f",
    ".webp": "\U0001f5bc\ufe0f",
    ".svg": "\U0001f5bc\ufe0f",
    ".ico": "\U0001f5bc\ufe0f",
    # Audio
    ".mp3": "\U0001f3b5",
    ".wav": "\U0001f3b5",
    ".flac": "\U0001f3b5",
    ".ogg": "\U0001f3b5",
    ".m4a": "\U0001f3b5",
    ".aac": "\U0001f3b5",
    # Video
    ".mp4": "\U0001f3ac",
    ".avi": "\U0001f3ac",
    ".mkv": "\U0001f3ac",
    ".mov": "\U0001f3ac",
    ".webm": "\U0001f3ac",
    ".wmv": "\U0001f3ac",
    # Archives
    ".zip": "\U0001f4e6",
    ".tar": "\U0001f4e6",
    ".gz": "\U0001f4e6",
    ".bz2": "\U0001f4e6",
    ".xz": "\U0001f4e6",
    ".7z": "\U0001f4e6",
    ".rar": "\U0001f4e6",
    # Code
    ".py": "\U0001f4bb",
    ".js": "\U0001f4bb",
    ".ts": "\U0001f4bb",
    ".java": "\U0001f4bb",
    ".c": "\U0001f4bb",
    ".cpp": "\U0001f4bb",
    ".h": "\U0001f4bb",
    ".go": "\U0001f4bb",
    ".rs": "\U0001f4bb",
    ".rb": "\U0001f4bb",
    # Web
    ".html": "\U0001f310",
    ".css": "\U0001f310",
    ".scss": "\U0001f310",
    ".sass": "\U0001f310",
    ".less": "\U0001f310",
    # Config
    ".json": "\u2699\ufe0f",
    ".xml": "\u2699\ufe0f",
    ".yaml": "\u2699\ufe0f",
    ".yml": "\u2699\ufe0f",
    ".toml": "\u2699\ufe0f",
    # Shell
    ".sh": "\u2328\ufe0f",
    ".bash": "\u2328\ufe0f",
    ".zsh": "\u2328\ufe0f",
    ".fish": "\u2328\ufe0f",
    ".ps1": "\u2328\ufe0f",
    ".bat": "\u2328\ufe0f",
    # Text
    ".txt": "\U0001f4dd",
    ".md": "\U0001f4dd",
    ".rst": "\U0001f4dd",
    ".log": "\U0001f4dd",
}

# --- Detection functions ---


def is_binary_content(data: bytes) -> bool:
    """Check if data appears to be binary content.

    Uses null byte detection - binary files almost always contain null bytes,
    while text files (even with various encodings) typically don't.
    This is the same heuristic used by git and the 'file' command.

    Args:
        data: Raw bytes to check.

    Returns:
        bool: True if the data appears to be binary.
    """
    return b"\x00" in data


def _extension(name: str) -> str:
    """Return the lowercased extension (including the leading dot), or "" if none."""
    lowered = name.lower()
    dot_idx = lowered.rfind(".")
    return lowered[dot_idx:] if dot_idx != -1 else ""


def get_syntax_class(filename: str) -> str:
    """Get the syntax highlighting class for a file based on extension or name.

    Args:
        filename: The filename to get syntax class for.

    Returns:
        str: CSS class name for syntax highlighting.
    """
    # Check special filenames first (Dockerfile, Makefile, etc.)
    special = _SPECIAL_FILENAME_MAP.get(filename.lower())
    if special is not None:
        return special

    return _SYNTAX_CLASS_MAP.get(_extension(filename), "plaintext")


def is_text_file(mime_type: str | None, filename: str) -> bool:
    """Determine if a file should be treated as text.

    Args:
        mime_type: The MIME type of the file.
        filename: The filename.

    Returns:
        bool: True if the file is viewable as text.
    """
    if mime_type:
        if mime_type in VIEWABLE_TEXT_TYPES:
            return True
        if mime_type.startswith("text/"):
            return True

    # Check special filenames (Dockerfile, Makefile, etc.)
    if filename.lower() in _SPECIAL_FILENAME_MAP:
        return True

    return _extension(filename) in _TEXT_FILE_EXTENSIONS


def is_image_file(mime_type: str | None) -> bool:
    """Determine if a file is a viewable image.

    Args:
        mime_type: The MIME type of the file.

    Returns:
        bool: True if the file is a viewable image.
    """
    if not mime_type:
        return False
    return mime_type in VIEWABLE_IMAGE_TYPES


def is_inline_document(mime_type: str | None) -> bool:
    """Determine if a file can be displayed inline (e.g., PDF).

    Args:
        mime_type: The MIME type of the file.

    Returns:
        bool: True if the file can be displayed inline.
    """
    if not mime_type:
        return False
    return mime_type in INLINE_DOCUMENT_TYPES


def get_file_icon(entry: FileEntry) -> str:
    """Get the appropriate icon for a file or directory.

    Uses O(1) dictionary lookup instead of sequential string matching.

    Args:
        entry: The file entry.

    Returns:
        str: Unicode character representing the file type.
    """
    if entry.is_dir:
        return "\U0001f4c1"

    return _EXTENSION_ICONS.get(_extension(entry.name), "\U0001f4c4")
