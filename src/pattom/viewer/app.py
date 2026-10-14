"""FastAPI app behind ``pattom view``: the local Pattom workbench."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from pattom.paths import REPO_ROOT
from pattom.viewer import routes_detect, routes_pipeline, routes_runs, routes_status, routes_tools, routes_work
from pattom.viewer.jobs import JobRunner
from pattom.viewer.security import LocalGuard, new_token

STATIC = Path(__file__).parent / "static"


def create_app(repo_root: Path = REPO_ROOT, token: str | None = None) -> FastAPI:
    token = token or new_token()
    app = FastAPI(title="Pattom workbench", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.jobs = JobRunner(repo_root)
    app.add_middleware(LocalGuard, token=token)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        return html.replace("__PATTOM_TOKEN__", token)

    app.include_router(routes_status.router(repo_root))
    app.include_router(routes_runs.router(repo_root))
    app.include_router(routes_pipeline.router(repo_root, app.state.jobs))
    app.include_router(routes_tools.router(repo_root))
    app.include_router(routes_detect.router(repo_root))
    app.include_router(routes_work.router(repo_root))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
