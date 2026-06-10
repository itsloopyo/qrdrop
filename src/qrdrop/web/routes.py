"""Route definitions for the QRDrop application."""

from pathlib import Path

from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from qrdrop.web.handlers.archive import archive_handler
from qrdrop.web.handlers.auth import (
    login_page_handler,
    login_submit_handler,
    logout_handler,
)
from qrdrop.web.handlers.browse import browse_handler
from qrdrop.web.handlers.files import delete_handler, download_handler, view_handler
from qrdrop.web.handlers.health import health_handler
from qrdrop.web.handlers.mutate import mkdir_handler, rename_handler
from qrdrop.web.handlers.upload import (
    check_upload_handler,
    upload_handler,
    upload_multiple_handler,
)


def get_routes(static_dir: Path) -> list[Route | Mount]:
    """Get all application routes.

    Args:
        static_dir: Path to the static files directory.

    Returns:
        list: List of Route and Mount objects.
    """
    return [
        Route("/health", health_handler, name="health"),
        Route("/", browse_handler, name="browse_root"),
        Route("/browse/{path:path}", browse_handler, name="browse"),
        Route("/view/{path:path}", view_handler, name="view"),
        Route("/download/{path:path}", download_handler, name="download"),
        Route("/delete/{path:path}", delete_handler, methods=["DELETE"], name="delete"),
        Route("/mkdir", mkdir_handler, methods=["POST"], name="mkdir"),
        Route("/rename", rename_handler, methods=["POST"], name="rename"),
        Route("/download-archive", archive_handler, methods=["POST"], name="archive"),
        Route("/upload", upload_handler, methods=["POST"], name="upload"),
        Route(
            "/upload-multiple", upload_multiple_handler, methods=["POST"], name="upload_multiple"
        ),
        Route("/upload-check", check_upload_handler, methods=["POST"], name="upload_check"),
        Route("/login", login_page_handler, name="login_page", methods=["GET"]),
        Route("/login", login_submit_handler, name="login_submit", methods=["POST"]),
        Route("/logout", logout_handler, name="logout"),
        Mount("/static", StaticFiles(directory=str(static_dir)), name="static"),
    ]
