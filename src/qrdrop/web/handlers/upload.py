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
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from qrdrop.web.handlers._common import (
    RequestValidationError,
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
        return UploadResult(
            filename=filename,
            success=False,
            error="Target is a symlink",
        )

    # "x" closes the check-then-write race for the no-overwrite case: open
    # fails atomically if the entry appeared (or is a symlink) in the meantime.
    mode = "wb" if overwrite else "xb"
    try:
        async with aiofiles.open(target_file, mode) as f:
            while True:
                chunk = await upload_file.read(WRITE_CHUNK_SIZE)
                if not chunk:
                    break

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
        # Clean up partial file on error. Report only the OS-level reason:
        # str(e) embeds the absolute server-side path.
        target_file.unlink(missing_ok=True)
        return UploadResult(
            filename=filename,
            success=False,
            error=f"Failed to write file: {e.strerror or e!s}",
        )

    return UploadResult(
        filename=filename,
        success=True,
        size=bytes_written,
        path=str(target_file.relative_to(root)),
    )


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

    # Check permission
    if not config.allow_upload:
        return JSONResponse(
            {"error": "Uploads not allowed", "success": False},
            status_code=403,
        )

    root = config.root_dir
    target_dir_path = request.query_params.get("path", "")

    try:
        target_dir = validate_target_directory(root, target_dir_path)
    except RequestValidationError as e:
        return validation_error_response(e)

    try:
        form = await request.form()
    except (ValueError, RuntimeError) as e:
        return JSONResponse(
            {"error": f"Failed to parse form data: {e!s}", "success": False},
            status_code=400,
        )

    upload_file = form.get("file")
    if not upload_file or not hasattr(upload_file, "filename"):
        return JSONResponse(
            {"error": "No file provided", "success": False},
            status_code=400,
        )

    try:
        filename = sanitize_name(upload_file.filename)
    except RequestValidationError as e:
        return validation_error_response(e)

    overwrite = str(form.get("overwrite", "false")).lower() == "true"
    target_file = target_dir / filename

    if target_file.is_symlink():
        return JSONResponse(
            {"error": "Cannot upload over a symlink", "success": False},
            status_code=403,
        )

    # Check if file already exists
    if target_file.exists() and not overwrite:
        return JSONResponse(
            {
                "error": f"File '{filename}' already exists",
                "exists": True,
                "success": False,
            },
            status_code=409,
        )

    # Write the file
    result = await _write_upload_file(upload_file, target_file, root, overwrite)

    if result.success:
        return JSONResponse(
            {
                "success": True,
                "filename": result.filename,
                "size": result.size,
                "path": result.path,
            }
        )

    status_code = 409 if result.exists else 500
    return JSONResponse(
        {"error": result.error, "success": False, "exists": result.exists},
        status_code=status_code,
    )


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

    # Check permission
    if not config.allow_upload:
        return JSONResponse(
            {"error": "Uploads not allowed", "success": False, "results": []},
            status_code=403,
        )

    root = config.root_dir
    target_dir_path = request.query_params.get("path", "")

    try:
        target_dir = validate_target_directory(root, target_dir_path)
    except RequestValidationError as e:
        return validation_error_response(e, with_results=True)

    try:
        form = await request.form()
    except (ValueError, RuntimeError) as e:
        return JSONResponse(
            {"error": f"Failed to parse form data: {e!s}", "success": False, "results": []},
            status_code=400,
        )

    overwrite = str(form.get("overwrite", "false")).lower() == "true"
    files = form.getlist("files") or form.getlist("file") or []

    if not files:
        return JSONResponse(
            {"error": "No files provided", "success": False, "results": []},
            status_code=400,
        )

    results: list[dict[str, Any]] = []
    success_count = 0
    error_count = 0

    for upload_file in files:
        if not hasattr(upload_file, "filename"):
            continue

        try:
            filename = sanitize_name(upload_file.filename)
        except RequestValidationError as e:
            results.append(
                {
                    "filename": upload_file.filename,
                    "success": False,
                    "error": e.message,
                }
            )
            error_count += 1
            continue

        target_file = target_dir / filename

        if target_file.is_symlink():
            results.append(
                {
                    "filename": filename,
                    "success": False,
                    "error": "Cannot upload over a symlink",
                }
            )
            error_count += 1
            continue

        # Check if file exists
        if target_file.exists() and not overwrite:
            results.append(
                {
                    "filename": filename,
                    "success": False,
                    "error": "File already exists",
                    "exists": True,
                }
            )
            error_count += 1
            continue

        # Write the file
        result = await _write_upload_file(upload_file, target_file, root, overwrite)

        if result.success:
            results.append(
                {
                    "filename": result.filename,
                    "success": True,
                    "size": result.size,
                    "path": result.path,
                }
            )
            success_count += 1
        else:
            failure = {
                "filename": result.filename,
                "success": False,
                "error": result.error,
            }
            if result.exists:
                failure["exists"] = True
            results.append(failure)
            error_count += 1

    return JSONResponse(
        {
            "success": error_count == 0,
            "total": len(results),
            "successful": success_count,
            "failed": error_count,
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

    # Check permission
    if not config.allow_upload:
        return JSONResponse(
            {"error": "Uploads not allowed", "success": False},
            status_code=403,
        )

    root = config.root_dir

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON body", "success": False},
            status_code=400,
        )

    target_dir_path = body.get("path", "")
    filenames = body.get("filenames", [])

    if not isinstance(filenames, list):
        return JSONResponse(
            {"error": "filenames must be an array", "success": False},
            status_code=400,
        )

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

        target_file = target_dir / safe_filename
        results[filename] = {
            "valid": True,
            "exists": target_file.exists(),
        }

    return JSONResponse(
        {
            "success": True,
            "files": results,
        }
    )
