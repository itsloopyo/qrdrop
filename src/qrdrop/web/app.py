"""Starlette application factory for the QRDrop file-sharing server."""

from dataclasses import dataclass
from pathlib import Path

from starlette.applications import Starlette
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp

from qrdrop.web.middleware import AuthMiddleware
from qrdrop.web.routes import get_routes


@dataclass
class AppConfig:
    """Application configuration."""

    root_dir: Path
    password: str
    port: int
    bind: str
    show_hidden: bool
    session_timeout: int | None
    allow_upload: bool = False
    allow_delete: bool = False
    allow_modify: bool = False


# Get package directory for templates and static files
PACKAGE_DIR = Path(__file__).parent.parent  # src/qrdrop/
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Initialize Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(config: AppConfig) -> ASGIApp:
    """Create the Starlette application with all routes and middleware.

    Args:
        config: Application configuration.

    Returns:
        ASGIApp: The configured ASGI application wrapped with authentication.
    """
    app = Starlette(routes=get_routes(STATIC_DIR))
    app.state.config = config
    app.state.templates = templates
    return AuthMiddleware(app)
