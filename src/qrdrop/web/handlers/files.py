"""File viewing and download handlers.

Handles single file viewing (text, images, PDFs) and streaming downloads.
Uses async I/O for efficient file streaming without blocking.
"""

import asyncio
import mimetypes
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import quote

import aiofiles
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from qrdrop.core.filesystem import (
    PathTraversalError,
    SymlinkEscapeError,
    humanize_size,
    validate_path,
)
from qrdrop.core.filetypes import (
    get_syntax_class,
    is_binary_content,
    is_image_file,
    is_inline_document,
    is_text_file,
)
from qrdrop.web.handlers._common import resolve_existing_target

# Chunk size for streaming downloads (128KB for better throughput)
# Larger chunks reduce syscall overhead and improve network utilization
CHUNK_SIZE = 131072

# Size of sample to check for binary detection (8KB is sufficient)
BINARY_CHECK_SIZE = 8192

# Maximum file size for inline viewing (10MB)
MAX_VIEW_SIZE = 10 * 1024 * 1024


def content_disposition(filename: str, disposition: str) -> str:
    """Build a header-injection-safe Content-Disposition value (RFC 6266).

    Filenames on POSIX may legally contain characters that are unsafe in a
    quoted HTTP header value (CR, LF, double-quote, backslash). Strip them
    from the ASCII fallback and additionally provide a UTF-8 percent-encoded
    `filename*` parameter so unicode names survive intact.
    """
    # ASCII-safe fallback: drop control chars, backslashes, and quotes; use
    # a placeholder if nothing useful remains.
    ascii_safe = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '"\\').strip()
    if not ascii_safe:
        ascii_safe = "download"
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"


async def file_stream(path: Path) -> AsyncGenerator[bytes, None]:
    """Async generator for streaming file contents.

    Args:
        path: Path to the file to stream.

    Yields:
        bytes: Chunks of file content.
    """
    async with aiofiles.open(path, "rb") as f:
        while chunk := await f.read(CHUNK_SIZE):
            yield chunk


async def _read_text_content(target: Path) -> str:
    """Read a file as UTF-8 text, replacing undecodable bytes."""
    async with aiofiles.open(target, encoding="utf-8", errors="replace") as f:
        return await f.read()


async def view_handler(request: Request) -> Response:
    """Handle file viewing requests.

    Renders text files with syntax highlighting, images inline,
    and PDFs with native browser rendering.

    Args:
        request: The Starlette request object.

    Returns:
        Response: HTML response with file content or redirect to download.
    """
    path = request.path_params.get("path", "")

    target = resolve_existing_target(request)
    if isinstance(target, Response):
        return target

    if target.is_dir():
        return RedirectResponse(f"/browse/{quote(path)}", status_code=302)

    stat_info = target.stat()
    file_size = stat_info.st_size

    if file_size > MAX_VIEW_SIZE:
        return RedirectResponse(f"/download/{quote(path)}", status_code=302)

    # Get MIME type
    mime_type, _ = mimetypes.guess_type(str(target))

    # Build parent path for breadcrumb navigation
    parent_path = str(Path(path).parent)
    if parent_path == ".":
        parent_path = ""

    templates = request.app.state.templates

    # Determine content type: check extension/MIME, then fall back to content sampling
    is_known_text = is_text_file(mime_type, target.name)
    if not is_known_text and not is_image_file(mime_type) and not is_inline_document(mime_type):
        try:
            async with aiofiles.open(target, "rb") as f:
                sample = await f.read(BINARY_CHECK_SIZE)
            if not is_binary_content(sample):
                is_known_text = True
        except OSError:
            pass

    # Handle text files
    if is_known_text:
        content = await _read_text_content(target)
        return templates.TemplateResponse(
            request,
            "view_text.html",
            {
                "filename": target.name,
                "path": path,
                "parent_path": parent_path,
                "content": content,
                "syntax_class": get_syntax_class(target.name),
                "file_size": humanize_size(file_size),
                "line_count": content.count("\n") + 1,
            },
        )

    # Handle images
    if is_image_file(mime_type):
        return templates.TemplateResponse(
            request,
            "view_image.html",
            {
                "filename": target.name,
                "path": path,
                "parent_path": parent_path,
                "file_size": humanize_size(file_size),
                "mime_type": mime_type,
            },
        )

    # Handle inline documents (PDF)
    if is_inline_document(mime_type):
        return StreamingResponse(
            file_stream(target),
            media_type=mime_type,
            headers={
                "Content-Disposition": content_disposition(target.name, "inline"),
                "Content-Length": str(file_size),
            },
        )

    # For other file types, redirect to download
    return RedirectResponse(f"/download/{quote(path)}", status_code=302)


async def download_handler(request: Request) -> Response:
    """Handle file download requests.

    Streams file content with appropriate MIME type and disposition.

    Args:
        request: The Starlette request object.

    Returns:
        Response: Streaming response with file content.
    """
    path = request.path_params.get("path", "")

    target = resolve_existing_target(request)
    if isinstance(target, Response):
        return target

    if target.is_dir():
        return RedirectResponse(f"/browse/{quote(path)}", status_code=302)

    mime_type, _ = mimetypes.guess_type(str(target))
    if not mime_type:
        mime_type = "application/octet-stream"

    file_size = target.stat().st_size

    return StreamingResponse(
        file_stream(target),
        media_type=mime_type,
        headers={
            "Content-Disposition": content_disposition(target.name, "attachment"),
            "Content-Length": str(file_size),
        },
    )


async def delete_handler(request: Request) -> Response:
    """Handle file/directory deletion requests.

    Deletes files or directories (recursively). Requires allow_delete permission.

    Args:
        request: The Starlette request object.

    Returns:
        Response: JSON response indicating success or failure.
    """
    config = request.app.state.config
    if not config.allow_delete:
        return JSONResponse(
            {"success": False, "error": "Deletion not allowed"},
            status_code=403,
        )

    path = request.path_params.get("path", "")
    root = config.root_dir

    try:
        target = validate_path(root, path)
    except (PathTraversalError, SymlinkEscapeError):
        return JSONResponse(
            {"success": False, "error": "Access denied"},
            status_code=403,
        )

    if not target.exists():
        return JSONResponse(
            {"success": False, "error": "Not found"},
            status_code=404,
        )

    if target.resolve() == root.resolve():
        return JSONResponse(
            {"success": False, "error": "Cannot delete root directory"},
            status_code=403,
        )

    try:
        if target.is_dir():
            # A large tree takes seconds to remove; keep the event loop free.
            await asyncio.to_thread(shutil.rmtree, target)
        else:
            target.unlink()

        return JSONResponse({"success": True})
    except OSError as e:
        # For OS-level failures str(e) embeds the absolute server-side path;
        # strerror is the path-free reason.
        return JSONResponse(
            {"success": False, "error": f"Failed to delete: {e.strerror or e!s}"},
            status_code=500,
        )
