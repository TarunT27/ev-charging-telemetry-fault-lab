"""FastAPI delivery layer for the interactive lab dashboard."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import BoundedSemaphore, Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from telemetry_lab.presets import PRESETS, config_from_preset, preset_catalog
from telemetry_lab.service import run_scenario

STATIC_DIR = Path(__file__).with_name("static")
MAX_BODY_BYTES = 32_768
RATE_LIMIT_REQUESTS = 100
SCENARIO_RATE_LIMIT_REQUESTS = 12
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_API_RECORDS = 500
LOGGER = logging.getLogger(__name__)


class RequestBodyLimitMiddleware:
    """Bound request bodies even when transfer encoding omits Content-Length."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        body_parts: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_body_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={"success": False, "data": None, "error": "request body too large"},
                )
                await response(scope, receive, send)
                return
            body_parts.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(body_parts)
        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(default="Dashboard run", min_length=1, max_length=80)
    seed: int = Field(default=27, ge=0, le=2_147_483_647)
    charger_count: int = Field(default=3, ge=1, le=20)
    samples_per_charger: int = Field(default=60, ge=5, le=1_000)
    preset: str = Field(default="mixed-faults")


def create_app() -> FastAPI:
    app = FastAPI(
        title="EV Charging Telemetry Fault Lab",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=MAX_BODY_BYTES)
    request_windows: dict[str, tuple[float, ...]] = {}
    rate_lock = Lock()
    scenario_slots = BoundedSemaphore(2)

    def add_safety_headers(response: Response, request_id: str, started: float) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"success": False, "data": None, "error": "validation failed"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"success": False, "data": None, "error": str(error.detail)},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={"success": False, "data": None, "error": "internal server error"},
        )

    @app.middleware("http")
    async def safety_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        nonlocal request_windows
        provided_request_id = request.headers.get("x-request-id", "")
        request_id = "".join(
            character for character in provided_request_id if character.isalnum() or character in "-_."
        )[:128] or str(uuid.uuid4())
        started = time.perf_counter()
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
            error_response = JSONResponse(
                status_code=413,
                content={"success": False, "data": None, "error": "request body too large"},
            )
            return add_safety_headers(error_response, request_id, started)

        client_id = request.client.host if request.client else "unknown"
        is_scenario_request = request.method == "POST" and request.url.path == "/api/v1/scenarios"
        window_key = f"{client_id}:scenario" if is_scenario_request else client_id
        request_limit = SCENARIO_RATE_LIMIT_REQUESTS if is_scenario_request else RATE_LIMIT_REQUESTS
        now = time.monotonic()
        with rate_lock:
            active_windows = {
                key: tuple(timestamp for timestamp in timestamps if now - timestamp < RATE_LIMIT_WINDOW_SECONDS)
                for key, timestamps in request_windows.items()
            }
            active_windows = {key: timestamps for key, timestamps in active_windows.items() if timestamps}
            recent = active_windows.get(window_key, ())
            if len(recent) >= request_limit:
                error_response = JSONResponse(
                    status_code=429,
                    content={"success": False, "data": None, "error": "rate limit exceeded"},
                    headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
                )
                return add_safety_headers(error_response, request_id, started)
            request_windows = {**active_windows, window_key: (*recent, now)}

        try:
            response = await call_next(request)
        except Exception as error:  # middleware must also header unexpected failures
            LOGGER.exception("Unhandled API error", exc_info=error)
            response = JSONResponse(
                status_code=500,
                content={"success": False, "data": None, "error": "internal server error"},
            )
        return add_safety_headers(response, request_id, started)

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/docs", include_in_schema=False)
    def api_reference() -> FileResponse:
        return FileResponse(STATIC_DIR / "api-docs.html")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, object]:
        return {
            "success": True,
            "data": {"status": "ok", "mode": "synthetic-only"},
            "error": None,
        }

    @app.get("/api/v1/presets", tags=["scenarios"])
    def presets() -> dict[str, object]:
        return {"success": True, "data": preset_catalog(), "error": None}

    @app.post("/api/v1/scenarios", status_code=201, tags=["scenarios"])
    def create_scenario(payload: ScenarioRequest) -> dict[str, object]:
        if payload.preset not in PRESETS:
            raise HTTPException(status_code=422, detail="unknown scenario preset")
        config = config_from_preset(
            payload.preset,
            name=payload.name,
            seed=payload.seed,
            charger_count=payload.charger_count,
            samples_per_charger=payload.samples_per_charger,
        )
        if not scenario_slots.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="scenario capacity reached; retry shortly")
        try:
            result = run_scenario(config)
        finally:
            scenario_slots.release()
        return {"success": True, "data": result.to_dict(max_records=MAX_API_RECORDS), "error": None}

    return app
