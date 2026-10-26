"""File viewing, download, and delete handlers.

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

from qrdrop.core.filesystem import humanize_size
from qrdrop.core.filetypes import (
    get_syntax_class,
    is_binary_content,
    is_image_file,
    is_inline_document,
    is_text_file,
)
from qrdrop.web.handlers._common import (
    RequestValidationError,
    content_disposition,
    json_error,
    os_error_reason,
    resolve_existing_path,
    resolve_existing_target,
)

# Chunk size for streaming downloads (128KB for better throughput)
# Larger chunks reduce syscall overhead and improve network utilization
CHUNK_SIZE = 131072

# Size of sample to check for binary detection (8KB is sufficient)
BINARY_CHECK_SIZE = 8192

# Maximum file size for inline viewing (10MB)
MAX_VIEW_SIZE = 10 * 1024 * 1024


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


def _stream_file(target: Path, media_type: str, disposition: str, size: int) -> StreamingResponse:
    return StreamingResponse(
        file_stream(target),
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(target.name, disposition),
            "Content-Length": str(size),
        },
    )


async def _read_text_content(target: Path) -> str:
    """Read a file as UTF-8 text, replacing undecodable bytes."""
    async with aiofiles.open(target, encoding="utf-8", errors="replace") as f:
        return await f.read()


async def _sample_is_text(target: Path) -> bool:
    """Sniff the head of a file of unknown type for binary content.

    An unreadable file is treated as not text, so the viewer falls through to
    the download redirect.
    """
    try:
        async with aiofiles.open(target, "rb") as f:
            sample = await f.read(BINARY_CHECK_SIZE)
    except OSError:
        return False
    return not is_binary_content(sample)


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

    file_size = target.stat().st_size

    if file_size > MAX_VIEW_SIZE:
        return RedirectResponse(f"/download/{quote(path)}", status_code=302)

    mime_type, _ = mimetypes.guess_type(str(target))
    is_image = is_image_file(mime_type)
    is_document = is_inline_document(mime_type)

    # Extension/MIME first; content sampling only for otherwise unknown types.
    is_text = is_text_file(mime_type, target.name) or (
        not is_image and not is_document and await _sample_is_text(target)
    )

    parent_path = str(Path(path).parent)
    if parent_path == ".":
        parent_path = ""

    templates = request.app.state.templates

    if is_text:
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

    if is_image:
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

    if is_document:
        return _stream_file(target, mime_type, "inline", file_size)

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
    return _stream_file(
        target, mime_type or "application/octet-stream", "attachment", target.stat().st_size
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
        return json_error("Deletion not allowed", 403)

    root = config.root_dir

    try:
        target = resolve_existing_path(root, request.path_params.get("path", ""))
    except RequestValidationError as e:
        return json_error(e.message, e.status_code)

    if target.resolve() == root.resolve():
        return json_error("Cannot delete root directory", 403)

    try:
        if target.is_dir():
            # A large tree takes seconds to remove; keep the event loop free.
            await asyncio.to_thread(shutil.rmtree, target)
        else:
            target.unlink()
    except OSError as e:
        return json_error(f"Failed to delete: {os_error_reason(e)}", 500)

    return JSONResponse({"success": True})
