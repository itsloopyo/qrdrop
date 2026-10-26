"""Directory creation and rename handlers.

Implements the create/rename operations that full-modify mode enables:
- Creating a new directory inside an existing, writable directory.
- Renaming an existing file or directory in place (within its parent).

Both operations require the ``allow_modify`` permission and validate all
paths through the shared filesystem security boundary.
"""

import os

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from qrdrop.web.handlers._common import (
    RequestValidationError,
    json_error,
    named_entry,
    os_error_reason,
    read_json_object,
    resolve_existing_path,
    sanitize_name,
    validate_target_directory,
    validation_error_response,
)


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
        return json_error("Modifications not allowed", 403)

    root = config.root_dir

    try:
        body = await read_json_object(request)
        target_dir = validate_target_directory(root, body.get("path", ""))
        name = sanitize_name(body.get("name"))
    except RequestValidationError as e:
        return validation_error_response(e)

    new_dir = target_dir / name

    if new_dir.exists():
        return json_error(f"'{name}' already exists", 409, exists=True)

    try:
        new_dir.mkdir()
    except OSError as e:
        return json_error(f"Failed to create directory: {os_error_reason(e)}", 500)

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
        return json_error("Modifications not allowed", 403)

    root = config.root_dir

    try:
        body = await read_json_object(request)
        path = body.get("path", "")
        resolved = resolve_existing_path(root, path)
    except RequestValidationError as e:
        return validation_error_response(e)

    if resolved == root.resolve():
        return json_error("Cannot rename root directory", 403)

    source = named_entry(root, path, resolved)

    try:
        new_name = sanitize_name(body.get("new_name"))
    except RequestValidationError as e:
        return validation_error_response(e)

    parent = source.parent
    if not os.access(parent, os.W_OK):
        return json_error("Directory is not writable", 403)

    if new_name == source.name:
        return json_error("New name is unchanged", 400)

    target = parent / new_name

    # On case-insensitive filesystems a case-only rename finds the source
    # itself at `target`; comparing lstat()s tells that apart from a real
    # collision, without following a symlink onto the entry it points at.
    if os.path.lexists(target) and not os.path.samestat(target.lstat(), source.lstat()):
        return json_error(f"'{new_name}' already exists", 409, exists=True)

    try:
        source.rename(target)
    except OSError as e:
        return json_error(f"Failed to rename: {os_error_reason(e)}", 500)

    return JSONResponse({"success": True, "path": str(target.relative_to(root))})
