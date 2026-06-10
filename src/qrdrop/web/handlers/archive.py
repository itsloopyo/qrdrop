"""Batch archive download handler.

Creates ZIP, TAR.GZ, or TAR.BZ2 archives from selected files and directories.
Archives are streamed to the client with bounded memory: a writer thread
produces compressed chunks into a small bounded queue as it walks the files,
so the archive never accumulates in RAM and a slow client applies
backpressure to the writer. No temporary files are created.
"""

import asyncio
import io
import json
import os
import queue
import tarfile
import threading
import zipfile
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from qrdrop.core.filesystem import (
    PathTraversalError,
    SymlinkEscapeError,
    validate_path,
)
from qrdrop.web.handlers.files import content_disposition

# Supported archive formats
SUPPORTED_FORMATS = {"zip", "tar.gz", "tar.bz2"}

_MEDIA_TYPES = {
    "zip": "application/zip",
    "tar.gz": "application/gzip",
    "tar.bz2": "application/x-bzip2",
}

# Writers emit chunks of at most ~16KB (zipfile/tarfile internal buffer
# sizes), so the queue bounds in-flight archive data to roughly 1MB.
_QUEUE_MAX_CHUNKS = 64

# Both sides poll at this interval so a vanished peer can never strand a
# thread: the producer notices cancellation on its next full-queue wait, and
# an orphaned consumer get() simply times out and exits.
_POLL_INTERVAL_SECONDS = 0.5


class _ClientDisconnected(Exception):
    """Raised inside the writer thread when the response stream is gone."""


class _QueueWriter(io.RawIOBase):
    """Write-only file object that hands written chunks to a bounded queue.

    Deliberately leaves tell()/seek() unsupported: zipfile detects that and
    switches to its unseekable streaming mode (data-descriptor entries),
    which is what makes single-pass ZIP output possible.
    """

    def __init__(self, chunk_queue: queue.Queue, cancelled: threading.Event) -> None:
        self._queue = chunk_queue
        self._cancelled = cancelled

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        data = bytes(b)
        while True:
            try:
                self._queue.put(data, timeout=_POLL_INTERVAL_SECONDS)
                return len(data)
            except queue.Full:
                if self._cancelled.is_set():
                    raise _ClientDisconnected() from None


def _write_archive(writer: _QueueWriter, files: list[tuple[Path, str]], format_type: str) -> None:
    """Write the archive for `files` to `writer` in a single streaming pass."""
    if format_type == "zip":
        with zipfile.ZipFile(writer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path, archive_path in files:
                zf.write(file_path, archive_path)
    else:  # tar.gz / tar.bz2 - validated against SUPPORTED_FORMATS upstream
        compression = "gz" if format_type == "tar.gz" else "bz2"
        with tarfile.open(fileobj=writer, mode=f"w|{compression}") as tf:
            for file_path, archive_path in files:
                tf.add(file_path, arcname=archive_path, recursive=False)


def _archive_producer(
    files: list[tuple[Path, str]],
    format_type: str,
    chunk_queue: queue.Queue,
    cancelled: threading.Event,
) -> None:
    """Thread target: write the archive, then signal completion.

    Terminal items: None for success, an Exception to re-raise in the
    response stream. If the consumer is gone (cancelled) the terminal put is
    skipped; the orphaned reader exits via its own timeout.
    """
    writer = _QueueWriter(chunk_queue, cancelled)
    try:
        _write_archive(writer, files, format_type)
        terminal: Exception | None = None
    except _ClientDisconnected:
        return
    except Exception as e:
        terminal = e

    while not cancelled.is_set():
        try:
            chunk_queue.put(terminal, timeout=_POLL_INTERVAL_SECONDS)
            return
        except queue.Full:
            continue


async def _stream_archive(
    files: list[tuple[Path, str]], format_type: str
) -> AsyncGenerator[bytes, None]:
    """Yield archive chunks as the writer thread produces them."""
    chunk_queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)
    cancelled = threading.Event()
    producer = threading.Thread(
        target=_archive_producer,
        args=(files, format_type, chunk_queue, cancelled),
        name="archive-writer",
        daemon=True,
    )
    producer.start()
    try:
        while True:
            try:
                item = await asyncio.to_thread(chunk_queue.get, True, _POLL_INTERVAL_SECONDS)
            except queue.Empty:
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        cancelled.set()


def _generate_archive_name(paths: list[str], format_type: str) -> str:
    """Generate a name for the archive file.

    Args:
        paths: List of paths being archived.
        format_type: The archive format.

    Returns:
        str: A suitable filename for the archive.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    if len(paths) == 1:
        # Single item - use its name
        name = Path(paths[0]).name
        return f"{name}.{format_type}"

    # Multiple items - use generic name with timestamp
    return f"archive_{timestamp}.{format_type}"


def _walk_real_files(target: Path) -> Iterator[tuple[Path, str]]:
    """Yield (absolute_path, relative_str) for non-symlink files under target.

    Uses os.scandir directly (cached DirEntry attrs) and never follows symlinks,
    so by induction every yielded path is physically inside `target`. The
    caller relies on this invariant to skip per-file containment checks.
    """
    base_len = len(str(target)) + 1  # +1 for trailing separator
    stack: list[str] = [str(target)]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        yield Path(entry.path), entry.path[base_len:]
                except OSError:
                    continue


def _collect_files(root: Path, paths: list[str]) -> list[tuple[Path, str]]:
    """Collect all files to include in the archive.

    Args:
        root: The server's root directory.
        paths: List of requested paths (relative to root).

    Returns:
        List of tuples: (absolute_path, archive_path).

    Raises:
        PathTraversalError: If any path escapes the root.
        FileNotFoundError: If any path doesn't exist.
    """
    files: list[tuple[Path, str]] = []

    for requested_path in paths:
        # validate_path returns a path resolved under root; the recursion below
        # never follows symlinks, so per-file containment checks are unnecessary.
        target = validate_path(root, requested_path)

        if not target.exists():
            raise FileNotFoundError(f"Path not found: {requested_path}")

        if target.is_file():
            files.append((target, target.name))
        elif target.is_dir():
            dir_name = target.name
            for abs_path, relative in _walk_real_files(target):
                # Normalize Windows separators for portable archive paths
                rel = relative.replace("\\", "/")
                files.append((abs_path, f"{dir_name}/{rel}"))

    return files


async def archive_handler(request: Request) -> Response:
    """Handle batch archive download requests.

    Accepts POST request with form data:
    - paths: JSON array of file/directory paths to include
    - format: Archive format (zip, tar.gz, tar.bz2)

    Args:
        request: The Starlette request object.

    Returns:
        Response: Streaming response with archive content, or error response.
    """
    root = request.app.state.config.root_dir

    # Parse form data
    form = await request.form()
    paths_json = form.get("paths", "[]")
    format_type = form.get("format", "zip")

    # Validate format
    if format_type not in SUPPORTED_FORMATS:
        return Response(
            f"Unsupported format: {format_type}. Supported: {', '.join(SUPPORTED_FORMATS)}",
            status_code=400,
        )

    # Parse paths JSON
    try:
        paths = json.loads(str(paths_json))
    except json.JSONDecodeError:
        return Response("Invalid paths JSON", status_code=400)

    if not isinstance(paths, list) or len(paths) == 0:
        return Response("No paths provided", status_code=400)

    # Validate all paths before streaming the archive
    # Run in thread pool to avoid blocking the event loop during directory scanning
    try:
        files = await asyncio.to_thread(_collect_files, root, paths)
    except PathTraversalError:
        return Response("Access denied: path traversal attempt", status_code=403)
    except SymlinkEscapeError:
        return Response("Access denied: symlink escape attempt", status_code=403)
    except FileNotFoundError as e:
        return Response(str(e), status_code=404)

    if len(files) == 0:
        return Response("No files to archive (directories may be empty)", status_code=400)

    archive_name = _generate_archive_name(paths, format_type)

    # No Content-Length: the size isn't known until the stream finishes.
    return StreamingResponse(
        _stream_archive(files, str(format_type)),
        media_type=_MEDIA_TYPES[str(format_type)],
        headers={"Content-Disposition": content_disposition(archive_name, "attachment")},
    )
