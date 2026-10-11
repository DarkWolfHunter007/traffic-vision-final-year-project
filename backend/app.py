"""Minimal Phase 01 application wiring."""

from fastapi import FastAPI

from backend import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="Traffic Vision", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "phase": "01", "version": __version__}

    @app.get("/status")
    def status() -> dict[str, str]:
        return {"implementation_scope": "phase_01_foundation", "next_cv_phase": "phase_02_detection"}

    return app


app = create_app()
