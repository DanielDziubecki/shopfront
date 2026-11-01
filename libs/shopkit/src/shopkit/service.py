"""App factory and runner shared by the HTTP services."""

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shopkit import telemetry

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@asynccontextmanager
async def _no_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def create_app(name: str, lifespan: Lifespan | None = None) -> FastAPI:
    telemetry.setup(name)
    app = FastAPI(title=name, lifespan=lifespan or _no_lifespan)
    log = logging.getLogger(name)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "internal error"}, status_code=500)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    return app


def http_client(base_url: str, timeout_s: float = 5.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=timeout_s)


def run(app: FastAPI) -> None:
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        log_config=None,
        access_log=False,
    )
