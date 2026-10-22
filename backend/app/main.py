"""FastAPI application entry point.

Run from the backend folder:  uvicorn app.main:app --reload --port 8000
Interactive API docs:          http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import base64
import secrets
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, Response

from .api import routes_realtime, routes_records, routes_scans, routes_system
from .core.config import Settings, get_settings
from .core.container import build_container

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nid")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = build_container(settings)
        yield
        app.state.container.realtime.shutdown()
        app.state.container.analysis.executor.shutdown(wait=False, cancel_futures=True)
        app.state.container.db.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Decision-support prototype: machine-learning intrusion detection plus a separate, rule-based "
            "risk assessment. Predictions are model outputs, not confirmed incidents."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error. See server logs."})

    if settings.access_password:
        expected = settings.access_password

        @app.middleware("http")
        async def gate(request: Request, call_next):
            if request.url.path != "/api/health":  # health stays open for host probes
                supplied = ""
                header = request.headers.get("authorization", "")
                if header.lower().startswith("basic "):
                    try:
                        supplied = base64.b64decode(header[6:]).decode().partition(":")[2]
                    except Exception:  # noqa: BLE001
                        supplied = ""
                if not secrets.compare_digest(supplied.encode(), expected.encode()):
                    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Viona"'})
            return await call_next(request)

    app.include_router(routes_system.router)
    app.include_router(routes_scans.router)
    app.include_router(routes_records.router)
    app.include_router(routes_realtime.router)

    # Single-URL deployment: serve the built dashboard from the same process when it exists.
    dist = Path(settings.frontend_dir)
    if (dist / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
