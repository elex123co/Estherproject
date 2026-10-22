"""FastAPI application entry point.

Run from the backend folder:  uvicorn app.main:app --reload --port 8000
Interactive API docs:          http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

    app.include_router(routes_system.router)
    app.include_router(routes_scans.router)
    app.include_router(routes_records.router)
    app.include_router(routes_realtime.router)
    return app


app = create_app()
