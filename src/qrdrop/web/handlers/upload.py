"""File upload handler with streaming support.

Handles file uploads via multipart form data with:
- Path validation to prevent uploads outside root
- Streaming writes for memory efficiency
- Overwrite prevention unless explicitly requested
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles
from starlette.datastructures import FormData, UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from qrdrop.web.handlers._common import (
    RequestValidationError,
    json_error,
    os_error_reason,
    sanitize_name,
    validate_target_directory,
    validation_error_response,
)

# Chunk size for streaming writes (128KB for better throughput)
WRITE_CHUNK_SIZE = 131072


@dataclass
class UploadResult:
    """Result of a single file upload attempt."""

    filename: str | None
    success: bool
    error: str | None = None
    size: int | None = None
    path: str | None = None
    exists: bool = False

    def success_body(self) -> dict[str, Any]:
        return {"success": True, "filename": self.filename, "size": self.size, "path": self.path}


async def _write_upload_file(
    upload_file: UploadFile, target_file: Path, root: Path, overwrite: bool
) -> UploadResult:
    """Stream an uploaded file to disk.

    Args:
        upload_file: The uploaded file object.
        target_file: The target path to write to.
        root: The server's root directory (for relative path calculation).
        overwrite: Whether replacing an existing file is allowed.

    Returns:
        UploadResult with the outcome.
    """
    filename = target_file.name
    bytes_written = 0

    # A symlink here (even a dangling one, which exists() reports as absent)
    # would make open() write through to the link target, escaping root.
    if target_file.is_symlink():
        return UploadResult(filename=filename, success=False, error="Target is a symlink")

    # "x" closes the check-then-write race for the no-overwrite case: open
    # fails atomically if the entry appeared (or is a symlink) in the meantime.
    mode = "wb" if overwrite else "xb"
    try:
        async with aiofiles.open(target_file, mode) as f:
            while chunk := await upload_file.read(WRITE_CHUNK_SIZE):
                bytes_written += len(chunk)
                await f.write(chunk)
    except FileExistsError:
        # Lost the race against a concurrent creation; the existing file is
        # not ours to remove.
        return UploadResult(
            filename=filename,
            success=False,
            error=f"File '{filename}' already exists",
            exists=True,
        )
    except OSError as e:
        target_file.unlink(missing_ok=True)
        return UploadResult(
            filename=filename,
            success=False,
            error=f"Failed to write file: {os_error_reason(e)}",
        )

    return UploadResult(
        filename=filename,
        success=True,
        size=bytes_written,
        path=str(target_file.relative_to(root)),
    )


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

    try:
        filename = sanitize_name(upload_file.filename)
    except RequestValidationError as e:
        return validation_error_response(e)

    overwrite = _wants_overwrite(form)
    target_file = target_dir / filename

    if target_file.is_symlink():
        return json_error("Cannot upload over a symlink", 403)

    if target_file.exists() and not overwrite:
        return json_error(f"File '{filename}' already exists", 409, exists=True)

    result = await _write_upload_file(upload_file, target_file, root, overwrite)

    if result.success:
        return JSONResponse(result.success_body())

    return json_error(result.error, 409 if result.exists else 500, exists=result.exists)


async def _upload_one(
    upload_file: UploadFile, target_dir: Path, root: Path, overwrite: bool
) -> dict[str, Any]:
    """Upload one file of a multi-file request and describe the outcome."""
    try:
        filename = sanitize_name(upload_file.filename)
    except RequestValidationError as e:
        return {"filename": upload_file.filename, "success": False, "error": e.message}

    target_file = target_dir / filename

    if target_file.is_symlink():
        return {"filename": filename, "success": False, "error": "Cannot upload over a symlink"}

    if target_file.exists() and not overwrite:
        return {
            "filename": filename,
            "success": False,
            "error": "File already exists",
            "exists": True,
        }

    result = await _write_upload_file(upload_file, target_file, root, overwrite)

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
        await _upload_one(upload_file, target_dir, root, overwrite)
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
        body = await request.json()
    except json.JSONDecodeError:
        return json_error("Invalid JSON body", 400)

    target_dir_path = body.get("path", "")
    filenames = body.get("filenames", [])

    if not isinstance(filenames, list):
        return json_error("filenames must be an array", 400)

    try:
        target_dir = validate_target_directory(root, target_dir_path)
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
