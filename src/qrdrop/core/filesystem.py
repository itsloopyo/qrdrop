"""Secure filesystem operations with path traversal protection.

All file operations must go through these functions to ensure
proper security boundaries are maintained.
"""

import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import NamedTuple


class PathTraversalError(Exception):
    """Raised when a path attempts to escape the root directory."""

    pass


class SymlinkEscapeError(Exception):
    """Raised when a symlink resolves to a location outside root."""

    pass


# Size units tuple - module-level to avoid recreation on each call
_SIZE_UNITS: tuple[tuple[str, int], ...] = (
    ("GB", 1024 * 1024 * 1024),
    ("MB", 1024 * 1024),
    ("KB", 1024),
    ("B", 1),
)

# Cache for resolved root paths to avoid repeated resolution.
# Stores (Path, str) so str(root) doesn't have to be recomputed on every
# validate_path call.
_root_cache: dict[str, tuple[Path, str]] = {}
_root_cache_lock = Lock()


class _CacheEntry(NamedTuple):
    """Cache entry for directory listings."""

    mtime: float
    entries: tuple  # Immutable tuple of FileEntry


# LRU cache for directory listings
_dir_cache: dict[tuple[str, bool], _CacheEntry] = {}
_dir_cache_lock = Lock()
_DIR_CACHE_MAX_SIZE = 256


def _get_resolved_root_cached(root: Path) -> tuple[Path, str]:
    """Get cached (resolved_path, resolved_str) tuple for `root`."""
    key = str(root)
    cached = _root_cache.get(key)
    if cached is not None:
        return cached
    with _root_cache_lock:
        cached = _root_cache.get(key)
        if cached is not None:
            return cached
        resolved = root.resolve()
        cached = (resolved, str(resolved))
        _root_cache[key] = cached
    return cached


def _is_under_root_str(root_str: str, target_str: str) -> bool:
    """String-only containment check; avoids re-resolving already-resolved paths.

    Uses string-prefix comparison rather than `Path.relative_to` so the result
    is consistent across platforms (Windows uses both "/" and "\\" as separators
    in resolved paths).
    """
    return (
        target_str == root_str
        or target_str.startswith(root_str + "/")
        or target_str.startswith(root_str + "\\")
    )


@dataclass(slots=True)
class FileEntry:
    """Represents a file or directory entry.

    Uses __slots__ for memory efficiency.
    """

    name: str
    size_bytes: int
    size_human: str
    mtime: datetime
    is_dir: bool
    is_hidden: bool


def validate_path(root: Path, requested: str) -> Path:
    """Validate and resolve a requested path relative to root.

    Ensures the requested path:
    1. Resolves to a location under the root directory
    2. Does not escape via ".." traversal
    3. Does not escape via symlink targets

    Args:
        root: The root directory that bounds all access.
        requested: The user-requested path (may be relative).

    Returns:
        Path: The resolved absolute path.

    Raises:
        PathTraversalError: If the path would escape the root directory.
        SymlinkEscapeError: If a symlink target is outside root.
    """
    root_resolved, root_str = _get_resolved_root_cached(root)

    if not requested or requested == "/" or requested == ".":
        return root_resolved

    # On NTFS "file.txt:stream" addresses an alternate data stream of
    # file.txt; its resolved path still sits under root, so the containment
    # check below would let hidden streams be read. No real entry under a
    # relative path contains ":".
    if os.name == "nt" and ":" in requested:
        raise PathTraversalError(f"Path contains invalid character: {requested}")

    target = root / requested.lstrip("/")
    resolved = target.resolve()
    resolved_str = str(resolved)

    if not _is_under_root_str(root_str, resolved_str):
        raise PathTraversalError(f"Path escapes root directory: {requested}")

    # is_symlink() returns False for nonexistent paths, so the prior exists()
    # check is redundant. Only resolve target.parent if we actually have a
    # symlink to inspect, since resolve() is the dominant cost here.
    if target.is_symlink() and not _is_under_root_str(root_str, str(target.parent.resolve())):
        raise SymlinkEscapeError(f"Symlink location escapes root: {requested}")

    return resolved


def _list_directory_uncached(path: Path, show_hidden: bool) -> list[FileEntry]:
    """Internal uncached directory listing.

    Args:
        path: The directory path to list.
        show_hidden: Whether to include files starting with '.'.

    Returns:
        list[FileEntry]: List of file entries in the directory.
    """
    entries: list[FileEntry] = []
    fromtimestamp = datetime.fromtimestamp
    is_dir_check = stat.S_ISDIR

    with os.scandir(path) as it:
        for entry_de in it:
            name = entry_de.name
            is_hidden = name.startswith(".")

            # Skip hidden files if not showing them
            if is_hidden and not show_hidden:
                continue

            try:
                # DirEntry.stat() follows symlinks by default, matching prior behavior.
                # On Windows, stat info is populated from the directory enumeration
                # for non-symlinks, avoiding a per-file syscall.
                stat_info = entry_de.stat()
                is_dir = is_dir_check(stat_info.st_mode)
                size = 0 if is_dir else stat_info.st_size

                entries.append(
                    FileEntry(
                        name=name,
                        size_bytes=size,
                        size_human=humanize_size(size),
                        mtime=fromtimestamp(stat_info.st_mtime, tz=UTC),
                        is_dir=is_dir,
                        is_hidden=is_hidden,
                    )
                )
            except OSError:
                # Skip files we can't stat (permission errors, etc.)
                continue

    return entries


def list_directory(path: Path, show_hidden: bool = True) -> list[FileEntry]:
    """List contents of a directory with caching.

    Uses an LRU cache with mtime-based invalidation for performance.
    Cache entries are invalidated when directory mtime changes.

    Args:
        path: The directory path to list.
        show_hidden: Whether to include files starting with '.'.

    Returns:
        list[FileEntry]: List of file entries in the directory.

    Raises:
        NotADirectoryError: If path is not a directory.
        FileNotFoundError: If path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")

    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    # Get directory mtime for cache validation
    try:
        dir_mtime = path.stat().st_mtime
    except OSError:
        # Can't stat - skip cache
        return _list_directory_uncached(path, show_hidden)

    cache_key = (str(path), show_hidden)

    cached = _dir_cache.get(cache_key)
    if cached is not None and cached.mtime == dir_mtime:
        return list(cached.entries)

    entries = _list_directory_uncached(path, show_hidden)

    # Update cache with lock
    with _dir_cache_lock:
        # Evict oldest entries if cache is full
        if len(_dir_cache) >= _DIR_CACHE_MAX_SIZE:
            # Remove 25% of entries (simple LRU approximation)
            keys_to_remove = list(_dir_cache.keys())[: _DIR_CACHE_MAX_SIZE // 4]
            for key in keys_to_remove:
                del _dir_cache[key]

        # Store as tuple for immutability
        _dir_cache[cache_key] = _CacheEntry(mtime=dir_mtime, entries=tuple(entries))

    return entries


def humanize_size(size_bytes: int) -> str:
    """Convert byte size to human-readable format.

    Args:
        size_bytes: Size in bytes.

    Returns:
        str: Human-readable size string (e.g., "1.5 MB").
    """
    if size_bytes == 0:
        return "-"

    for unit_name, unit_size in _SIZE_UNITS:
        if size_bytes >= unit_size:
            value = size_bytes / unit_size
            if value >= 100:
                return f"{value:.0f} {unit_name}"
            elif value >= 10:
                return f"{value:.1f} {unit_name}"
            else:
                return f"{value:.2f} {unit_name}"

    return f"{size_bytes} B"


def _key_name(e: FileEntry) -> str:
    """Sort key for name (case-insensitive)."""
    return e.name.lower()


def _key_size(e: FileEntry) -> int:
    """Sort key for size."""
    return e.size_bytes


def _key_mtime(e: FileEntry) -> datetime:
    """Sort key for modification time."""
    return e.mtime


# Pre-defined sort key functions to avoid lambda recreation
_SORT_KEYS = {
    "name": _key_name,
    "size": _key_size,
    "modified": _key_mtime,
}


def sort_entries(
    entries: list[FileEntry],
    sort_by: str = "name",
    sort_order: str = "asc",
) -> list[FileEntry]:
    """Sort file entries with directories first, then by specified field.

    Uses single-pass separation and pre-defined key functions for performance.

    Args:
        entries: List of file entries to sort.
        sort_by: Field to sort by - "name", "size", or "modified".
        sort_order: Sort direction - "asc" or "desc".

    Returns:
        list[FileEntry]: Sorted list (directories always first, then files sorted).
    """
    # Single pass to separate directories and files
    dirs: list[FileEntry] = []
    files: list[FileEntry] = []
    for e in entries:
        (dirs if e.is_dir else files).append(e)

    reverse = sort_order == "desc"
    key_func = _SORT_KEYS.get(sort_by, _key_name)

    if sort_by == "size":
        # Directories have no meaningful size - always sort alphabetically
        dirs.sort(key=_key_name)
        files.sort(key=key_func, reverse=reverse)
    else:
        dirs.sort(key=key_func, reverse=reverse)
        files.sort(key=key_func, reverse=reverse)

    return dirs + files
