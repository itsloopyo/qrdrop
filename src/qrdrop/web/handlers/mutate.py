"""Directory creation and rename handlers.

Implements the create/rename operations enabled by the ``--modify`` flag:
- Creating a new directory inside an existing, writable directory.
- Renaming an existing file or directory in place (within its parent).

Both operations require the ``allow_modify`` permission and validate all
paths through the shared filesystem security boundary.
"""

import json
import os

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from qrdrop.core.filesystem import (
    PathTraversalError,
    SymlinkEscapeError,
    validate_path,
)
from qrdrop.web.handlers._common import (
    RequestValidationError,
    sanitize_name,
    validate_target_directory,
    validation_error_response,
)


def _parse_json_object(body: object) -> dict:
    """Validate that a decoded JSON body is an object.

    Raises:
        RequestValidationError: If the body is not a JSON object.
    """
    if not isinstance(body, dict):
        raise RequestValidationError("Request body must be a JSON object", 400)
    return body


async def _read_json_body(request: Request) -> dict:
    """Parse the request body as a JSON object.

    Raises:
        RequestValidationError: If the body is not valid JSON or not an object.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        raise RequestValidationError("Invalid JSON body", 400) from e

    return _parse_json_object(body)


async def mkdir_handler(request: Request) -> Response:
    """Handle directory creation requests.

    Accepts a JSON body with:
    - path: Parent directory path relative to root (defaults to root)
    - name: Name of the directory to create (required)

    Args:
        request: The Starlette request object.

    Returns:
        Response: JSON response indicating success or failure.
    """
    config = request.app.state.config
    if not config.allow_modify:
        return JSONResponse(
            {"success": False, "error": "Modifications not allowed"},
            status_code=403,
        )

    root = config.root_dir

    try:
        body = await _read_json_body(request)
        target_dir = validate_target_directory(root, body.get("path", ""))
        name = sanitize_name(body.get("name"))
    except RequestValidationError as e:
        return validation_error_response(e)

    new_dir = target_dir / name

    if new_dir.exists():
        return JSONResponse(
            {"success": False, "error": f"'{name}' already exists", "exists": True},
            status_code=409,
        )

    try:
        new_dir.mkdir()
    except OSError as e:
        # For OS-level failures str(e) embeds the absolute server-side path;
        # strerror is the path-free reason.
        return JSONResponse(
            {
                "success": False,
                "error": f"Failed to create directory: {e.strerror or e!s}",
            },
            status_code=500,
        )

    return JSONResponse({"success": True, "path": str(new_dir.relative_to(root))})


async def rename_handler(request: Request) -> Response:
    """Handle file/directory rename requests.

    Renames an entry in place within its parent directory. Accepts a JSON
    body with:
    - path: Path of the entry to rename, relative to root (required)
    - new_name: New name for the entry (required)

    Args:
        request: The Starlette request object.

    Returns:
        Response: JSON response indicating success or failure.
    """
    config = request.app.state.config
    if not config.allow_modify:
        return JSONResponse(
            {"success": False, "error": "Modifications not allowed"},
            status_code=403,
        )

    root = config.root_dir

    try:
        body = await _read_json_body(request)
    except RequestValidationError as e:
        return validation_error_response(e)

    try:
        source = validate_path(root, body.get("path", ""))
    except (PathTraversalError, SymlinkEscapeError):
        return JSONResponse(
            {"success": False, "error": "Access denied"},
            status_code=403,
        )

    if not source.exists():
        return JSONResponse(
            {"success": False, "error": "Not found"},
            status_code=404,
        )

    if source.resolve() == root.resolve():
        return JSONResponse(
            {"success": False, "error": "Cannot rename root directory"},
            status_code=403,
        )

    try:
        new_name = sanitize_name(body.get("new_name"))
    except RequestValidationError as e:
        return validation_error_response(e)

    parent = source.parent
    if not os.access(parent, os.W_OK):
        return JSONResponse(
            {"success": False, "error": "Directory is not writable"},
            status_code=403,
        )

    if new_name == source.name:
        return JSONResponse(
            {"success": False, "error": "New name is unchanged"},
            status_code=400,
        )

    target = parent / new_name

    # On case-insensitive filesystems a case-only rename makes target.exists()
    # report the source itself; samefile() distinguishes that from a real
    # collision with another entry.
    if target.exists() and not target.samefile(source):
        return JSONResponse(
            {"success": False, "error": f"'{new_name}' already exists", "exists": True},
            status_code=409,
        )

    try:
        source.rename(target)
    except OSError as e:
        # For OS-level failures str(e) embeds the absolute server-side path;
        # strerror is the path-free reason.
        return JSONResponse(
            {"success": False, "error": f"Failed to rename: {e.strerror or e!s}"},
            status_code=500,
        )

    return JSONResponse({"success": True, "path": str(target.relative_to(root))})
