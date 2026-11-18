"""FastAPI application — REST API plus the built frontend, on one port.

Serving the compiled React bundle from the same origin as the API is what keeps
AutoClip a single process with no CORS configuration, no second port, and no
Node.js at runtime.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, errors, paths
from .api import api_router
from .jobs.events import broker
from .jobs.queue import queue
from .youtube.queue import upload_queue

log = logging.getLogger(__name__)

#: Set to "1" to serve the API without starting the background job worker.
ENV_NO_WORKER = "AUTOCLIP_NO_WORKER"

#: Where the built frontend is looked for, in priority order. The first is the
#: packaged location (inside the wheel); the second is the dev build output.
_STATIC_CANDIDATES = (
    Path(__file__).resolve().parent / "static",
    Path(__file__).resolve().parents[2] / "frontend" / "dist",
)


def static_dir() -> Path | None:
    for candidate in _STATIC_CANDIDATES:
        if (candidate / "index.html").exists():
            return candidate
    return None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio

    paths.ensure_layout()
    db.init()

    # Phase 4: import the pre-multi-era YouTube connection as the default
    # account/channel row (no-op when already migrated or nothing connected).
    from .youtube import accounts as yt_accounts

    try:
        yt_accounts.ensure_legacy_migrated()
    except Exception:  # noqa: BLE001 - never block startup on the import
        log.warning("Legacy YouTube account import failed.", exc_info=True)

    broker.bind_loop(asyncio.get_running_loop())

    # Phase 6: batch runner advances persistent batch queues item by item.
    from .jobs.batch_runner import batch_runner

    batch_runner.start()

    # Serving the API without a worker is useful for debugging a stuck queue and
    # makes API tests deterministic — jobs stay queued instead of racing off.
    worker_enabled = os.environ.get(ENV_NO_WORKER) != "1"
    if worker_enabled:
        await queue.start()
        await upload_queue.start()
    else:
        log.info("Job worker disabled by %s=1.", ENV_NO_WORKER)

    log.info("AutoClip %s ready. Artifacts in %s", __version__, paths.root())

    try:
        yield
    finally:
        await batch_runner.stop()
        if worker_enabled:
            await upload_queue.stop()
            await queue.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoClip",
        version=__version__,
        description="Local-first AI video clipper.",
        lifespan=lifespan,
    )

    _install_error_handlers(app)

    app.include_router(api_router)

    @app.get("/api/health")
    async def health() -> dict:
        status = queue.status()
        return {
            "status": "ok",
            "version": __version__,
            "running_job": status.running_job_id,
            "queued": status.queued,
        }

    _mount_frontend(app)
    return app


def _install_error_handlers(app: FastAPI) -> None:
    """Make every API failure look the same to the client.

    One JSON shape — ``{detail, code, hint, retryable}`` — with a stable code
    the UI can branch on. Without this, the client had to guess from prose
    whether a failure was worth retrying.
    """

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        # Some endpoints raise with a structured detail ({message, hint}) so
        # the UI can show the fix alongside the failure. Those are flattened
        # into the same shape as every other failure, so the client has one
        # contract to parse rather than two.
        message = ""
        hint = ""
        code = ""
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("detail") or "Request failed.")
            hint = str(detail.get("hint") or "")
            code = str(detail.get("code") or "")
        else:
            message = str(detail)

        if not code:
            code = _code_for_status(exc.status_code)
        if not hint:
            hint = errors.classify_text(message, code=code).hint

        info = errors.ErrorInfo(
            code=code,
            message=message,
            hint=hint,
            retryable=code in errors.RETRYABLE_CODES,
            status=exc.status_code,
        )
        return JSONResponse(status_code=exc.status_code, content=info.to_response())

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "request"
        message = f"{field}: {first.get('msg', 'is invalid')}."
        info = errors.ErrorInfo(
            code=errors.VALIDATION,
            message=message,
            hint="Check the values sent to this endpoint.",
            retryable=False,
            status=422,
        )
        return JSONResponse(status_code=422, content=info.to_response())

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s.", request.method, request.url.path)
        info = errors.classify(exc)
        return JSONResponse(status_code=info.status, content=info.to_response())


def _code_for_status(status: int) -> str:
    """The stable code for a bare HTTP status."""
    if status == 404:
        return errors.NOT_FOUND
    if status == 409:
        return errors.CONFLICT
    if status in (401, 403):
        return errors.AUTH
    if status == 429:
        return errors.RATE_LIMIT
    if status in (400, 415, 422):
        return errors.VALIDATION
    if status >= 500:
        return errors.INTERNAL
    return errors.CONFIG


def _mount_frontend(app: FastAPI) -> None:
    directory = static_dir()

    if directory is None:

        @app.get("/", include_in_schema=False)
        async def missing_frontend() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "The frontend has not been built.",
                    "hint": (
                        "Run `npm install && npm run build` in the frontend/ "
                        "directory, then restart. The API itself is available "
                        "at /docs."
                    ),
                },
            )

        log.warning("No built frontend found; serving the API only.")
        return

    app.mount(
        "/assets",
        StaticFiles(directory=directory / "assets"),
        name="assets",
    )

    # response_model=None because the return type is a union of Response
    # subclasses, which FastAPI would otherwise try to turn into a Pydantic
    # response model and reject.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(request: Request, full_path: str) -> FileResponse | JSONResponse:
        """Serve the SPA, letting the client router own unknown paths.

        API routes are registered first and win; anything else that isn't a real
        file falls through to index.html so a deep link like /jobs/abc123 works
        on a hard refresh.
        """
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found."})

        candidate = directory / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(directory / "index.html")

    log.info("Serving the frontend from %s", directory)


app = create_app()
