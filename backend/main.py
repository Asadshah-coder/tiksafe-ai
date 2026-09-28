"""TikSave AI FastAPI application."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .ai.base import AIProviderError
from .api.routes import ai as ai_routes
from .api.routes import analyze as analyze_routes
from .api.routes import download as download_routes
from .api.routes import processing as processing_routes
from .core.config import get_settings
from .core.logging import configure_logging, get_logger
from .core.security import (
    RateLimitMiddleware,
    URLValidationError,
    cleanup_old_temp_files,
)
from .services import ai_service
from .services.ai_service import AINotConfigured
from .services.downloader import DownloadError
from .services.extractor import ExtractionError
from .services.ffmpeg_service import FFmpegError, FFmpegNotAvailable, ffmpeg_available
from .services.transcription import TranscriptionError, whisper_available

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()

    async def cleanup_loop() -> None:
        while not stop.is_set():
            await asyncio.sleep(600)
            try:
                removed = cleanup_old_temp_files(
                    settings.temp_dir, settings.temp_file_ttl_seconds
                )
                if removed:
                    log.info("cleaned up %d stale temp entries", removed)
            except Exception:  # noqa: BLE001
                log.exception("temp cleanup failed")

    task = asyncio.create_task(cleanup_loop())
    log.info("TikSave AI v%s starting (env=%s)", __version__, settings.environment)
    yield
    stop.set()
    task.cancel()


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": message, "code": code},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TikSave AI API",
        description=(
            "TikTok video toolkit: public media analysis, downloads, "
            "video processing, and an optional AI toolkit."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=settings.rate_limit_per_minute,
        window_seconds=60,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(analyze_routes.router, prefix="/api/analyze", tags=["analyze"])
    app.include_router(download_routes.router, prefix="/api", tags=["download"])
    app.include_router(ai_routes.router, prefix="/api", tags=["ai"])
    app.include_router(processing_routes.router, prefix="/api", tags=["processing"])

    @app.exception_handler(URLValidationError)
    async def url_validation_handler(_: Request, exc: URLValidationError):
        return _error(exc.code, exc.message, 400)

    @app.exception_handler(ExtractionError)
    async def extraction_handler(_: Request, exc: ExtractionError):
        status = {
            "private_content": 403,
            "unavailable": 404,
            "network_timeout": 504,
        }.get(exc.code, 400)
        return _error(exc.code, exc.message, status)

    @app.exception_handler(DownloadError)
    async def download_handler(_: Request, exc: DownloadError):
        status = {
            "private_content": 403,
            "unavailable": 404,
            "network_timeout": 504,
            "file_too_large": 413,
        }.get(exc.code, 400)
        return _error(exc.code, exc.message, status)

    @app.exception_handler(TranscriptionError)
    async def transcription_handler(_: Request, exc: TranscriptionError):
        status = 503 if exc.code == "unavailable" else 422
        return _error(exc.code, exc.message, status)

    @app.exception_handler(AINotConfigured)
    async def ai_not_configured_handler(_: Request, exc: AINotConfigured):
        return _error("ai_unavailable", str(exc), 503)

    @app.exception_handler(AIProviderError)
    async def ai_provider_handler(_: Request, exc: AIProviderError):
        return _error(exc.code, exc.message, 502)

    @app.exception_handler(FFmpegNotAvailable)
    async def ffmpeg_missing_handler(_: Request, exc: FFmpegNotAvailable):
        return _error("ffmpeg_unavailable", str(exc), 503)

    @app.exception_handler(FFmpegError)
    async def ffmpeg_handler(_: Request, exc: FFmpegError):
        return _error("processing_failed", str(exc), 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error(f"http_{exc.status_code}", detail, exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return _error(
            "internal_error",
            "Something went wrong on our side. Please try again later.",
            500,
        )

    @app.get("/", summary="Service info")
    def root():
        return {
            "ok": True,
            "service": "tiksafe-ai",
            "version": __version__,
            "docs": "/docs",
        }

    @app.get("/api/health", summary="Health check")
    def health():
        return {
            "ok": True,
            "service": "tiksafe-ai",
            "version": __version__,
            "ffmpeg": ffmpeg_available(),
            "ai": ai_service.ai_available(),
            "transcription": whisper_available(),
        }

    return app


app = create_app()
