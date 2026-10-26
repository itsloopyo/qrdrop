"""File upload handler with streaming support.

Handles file uploads via multipart form data with:
- Path validation to prevent uploads outside root
- Streaming writes for memory efficiency
- Overwrite prevention unless explicitly requested
"""

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from starlette.datastructures import FormData, UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from qrdrop.web.handlers._common import (
    RequestValidationError,
    json_error,
    os_error_reason,
    read_json_object,
    sanitize_name,
    validate_target_directory,
    validation_error_response,
)

# Chunk size for streaming writes (1MB: the copy runs in one worker thread,
# so a larger buffer just means fewer read/write syscalls)
WRITE_CHUNK_SIZE = 1024 * 1024


@dataclass
class UploadResult:
    """Result of a single file upload attempt."""

    filename: str | None
    success: bool
    error: str | None = None
    size: int | None = None
    path: str | None = None
    exists: bool = False
    status_code: int = 200

    def success_body(self) -> dict[str, Any]:
        return {"success": True, "filename": self.filename, "size": self.size, "path": self.path}


def _copy_upload(source: BinaryIO, target_file: Path, mode: str) -> int:
    """Copy `source` into `target_file` and return the number of bytes written.

    A failure after the open removes the partial file. A failed open leaves
    the path alone: whatever is there (a read-only file being overwritten, a
    directory of the same name) is not ours.
    """
    f = open(target_file, mode)  # noqa: SIM115 - the cleanup below must not cover the open
    try:
        with f:
            shutil.copyfileobj(source, f, WRITE_CHUNK_SIZE)
            return f.tell()
    except BaseException:
        target_file.unlink(missing_ok=True)
        raise


async def _write_upload_file(
    upload_file: UploadFile, target_file: Path, root: Path, overwrite: bool
) -> UploadResult:
    """Write an uploaded file to disk.

    The caller has already refused a symlink at `target_file`.

    Args:
        upload_file: The uploaded file object.
        target_file: The target path to write to.
        root: The server's root directory (for relative path calculation).
        overwrite: Whether replacing an existing file is allowed.

    Returns:
        UploadResult with the outcome.
    """
    filename = target_file.name

    # "x" closes the check-then-write race for the no-overwrite case: open
    # fails atomically if the entry appeared (or is a symlink) in the meantime.
    mode = "wb" if overwrite else "xb"
    try:
        bytes_written = await asyncio.to_thread(_copy_upload, upload_file.file, target_file, mode)
    except FileExistsError:
        # Lost the race against a concurrent creation; the existing file is
        # not ours to remove.
        return UploadResult(
            filename=filename,
            success=False,
            error=f"File '{filename}' already exists",
            exists=True,
            status_code=409,
        )
    except OSError as e:
        return UploadResult(
            filename=filename,
            success=False,
            error=f"Failed to write file: {os_error_reason(e)}",
            status_code=500,
        )

    return UploadResult(
        filename=filename,
        success=True,
        size=bytes_written,
        path=str(target_file.relative_to(root)),
    )


async def _save_upload(
    upload_file: UploadFile, target_dir: Path, root: Path, overwrite: bool
) -> UploadResult:
    """Validate the name and destination of one uploaded file, then write it."""
    try:
        filename = sanitize_name(upload_file.filename)
    except RequestValidationError as e:
        return UploadResult(
            filename=upload_file.filename, success=False, error=e.message, status_code=400
        )

    target_file = target_dir / filename

    # A symlink here (even a dangling one, which exists() reports as absent)
    # would make open() write through to the link target, escaping root.
    if target_file.is_symlink():
        return UploadResult(
            filename=filename, success=False, error="Cannot upload over a symlink", status_code=403
        )

    # Opening a FIFO for writing blocks until a reader appears, pinning the
    # worker thread for good. A directory fails the open on its own.
    if overwrite and target_file.exists() and not (target_file.is_file() or target_file.is_dir()):
        return UploadResult(
            filename=filename,
            success=False,
            error=f"'{filename}' is not a regular file",
            status_code=409,
        )

    if not overwrite and target_file.exists():
        return UploadResult(
            filename=filename,
            success=False,
            error=f"File '{filename}' already exists",
            exists=True,
            status_code=409,
        )

    return await _write_upload_file(upload_file, target_file, root, overwrite)


def _wants_overwrite(form: FormData) -> bool:
    return str(form.get("overwrite", "false")).lower() == "true"


async def upload_handler(request: Request) -> Response:
    """Handle single file upload requests.

    Accepts multipart form data with:
    - file: The file to upload (required)
    - path: Target directory path relative to root (query param)
    - overwrite: Whether to overwrite existing files (optional, defaults to false)

    Args:
        request: The Starlette request object.

    Returns:
        Response: JSON response with upload result.
    """
    config = request.app.state.config
    if not config.allow_upload:
        return json_error("Uploads not allowed", 403)

    root = config.root_dir

    try:
        target_dir = validate_target_directory(root, request.query_params.get("path", ""))
    except RequestValidationError as e:
        return validation_error_response(e)

    try:
        form = await request.form()
    except (ValueError, RuntimeError) as e:
        return json_error(f"Failed to parse form data: {e!s}", 400)

    upload_file = form.get("file")
    if not upload_file or not hasattr(upload_file, "filename"):
        return json_error("No file provided", 400)

    result = await _save_upload(upload_file, target_dir, root, _wants_overwrite(form))

    if result.success:
        return JSONResponse(result.success_body())

    return json_error(result.error, result.status_code, exists=result.exists)


def _multi_entry(result: UploadResult) -> dict[str, Any]:
    """Describe one file's outcome in a multi-file response."""
    if result.success:
        return result.success_body()

    failure: dict[str, Any] = {
        "filename": result.filename,
        "success": False,
        "error": result.error,
    }
    if result.exists:
        failure["exists"] = True
    return failure


async def upload_multiple_handler(request: Request) -> Response:
    """Handle multiple file uploads in a single request.

    Accepts multipart form data with:
    - files: Multiple files to upload (required)
    - path: Target directory path relative to root (query param)
    - overwrite: Whether to overwrite existing files (optional)

    Args:
        request: The Starlette request object.

    Returns:
        Response: JSON response with results for each file.
    """
    config = request.app.state.config
    if not config.allow_upload:
        return json_error("Uploads not allowed", 403, results=[])

    root = config.root_dir

    try:
        target_dir = validate_target_directory(root, request.query_params.get("path", ""))
    except RequestValidationError as e:
        return validation_error_response(e, with_results=True)

    try:
        form = await request.form()
    except (ValueError, RuntimeError) as e:
        return json_error(f"Failed to parse form data: {e!s}", 400, results=[])

    overwrite = _wants_overwrite(form)
    files = form.getlist("files") or form.getlist("file")

    if not files:
        return json_error("No files provided", 400, results=[])

    # Plain string fields under the file keys are not uploads; skip them.
    results = [
        _multi_entry(await _save_upload(upload_file, target_dir, root, overwrite))
        for upload_file in files
        if hasattr(upload_file, "filename")
    ]
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    return JSONResponse(
        {
            "success": failed == 0,
            "total": len(results),
            "successful": successful,
            "failed": failed,
            "results": results,
        }
    )


async def check_upload_handler(request: Request) -> Response:
    """Check if files can be uploaded (pre-flight check).

    Used to check if files exist before starting upload,
    allowing the UI to prompt for overwrite confirmation.

    Args:
        request: The Starlette request object with JSON body containing:
            - path: Target directory path
            - filenames: List of filenames to check

    Returns:
        Response: JSON with existence status for each filename.
    """
    config = request.app.state.config
    if not config.allow_upload:
        return json_error("Uploads not allowed", 403)

    root = config.root_dir

    try:
        body = await read_json_object(request)
    except RequestValidationError as e:
        return validation_error_response(e)

    filenames = body.get("filenames", [])

    if not isinstance(filenames, list):
        return json_error("filenames must be an array", 400)

    try:
        target_dir = validate_target_directory(root, body.get("path", ""))
    except RequestValidationError as e:
        return validation_error_response(e)

    results: dict[str, dict[str, Any]] = {}
    for filename in filenames:
        if not isinstance(filename, str):
            continue

        try:
            safe_filename = sanitize_name(filename)
        except RequestValidationError as e:
            results[filename] = {"valid": False, "error": e.message}
            continue

        results[filename] = {"valid": True, "exists": (target_dir / safe_filename).exists()}

    return JSONResponse({"success": True, "files": results})
