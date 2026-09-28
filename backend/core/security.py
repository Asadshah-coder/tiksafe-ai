"""Security helpers: URL validation, filename sanitization, rate limiting, temp hygiene."""

from __future__ import annotations

import re
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

ALLOWED_TIKTOK_DOMAINS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}

MAX_URL_LENGTH = 2048
ALLOWED_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
MAX_FILENAME_LENGTH = 120


class URLValidationError(ValueError):
    """Raised when a user-supplied URL fails validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def validate_tiktok_url(raw_url: str | None) -> str:
    """Validate a TikTok URL and return a normalized form. Never trust raw input."""
    if raw_url is None:
        raise URLValidationError("empty_url", "Please paste a TikTok video URL.")
    url = raw_url.strip()
    if not url:
        raise URLValidationError("empty_url", "Please paste a TikTok video URL.")
    if len(url) > MAX_URL_LENGTH:
        raise URLValidationError("url_too_long", "That URL is too long to be valid.")

    try:
        parsed = urlsplit(url)
    except ValueError:
        raise URLValidationError(
            "malformed_url", "That URL is malformed. Please check it and try again."
        ) from None

    if parsed.scheme not in ("http", "https"):
        raise URLValidationError(
            "invalid_scheme", "URLs must start with http:// or https://."
        )
    host = (parsed.hostname or "").lower().strip(".")
    if host not in ALLOWED_TIKTOK_DOMAINS:
        raise URLValidationError(
            "unsupported_domain",
            "Only TikTok links are supported (tiktok.com, vm.tiktok.com, vt.tiktok.com).",
        )
    if not parsed.path or parsed.path.strip("/") == "":
        raise URLValidationError(
            "invalid_url", "That doesn't look like a TikTok video link."
        )

    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def sanitize_filename(name: str | None, default: str = "file") -> str:
    """Strip path components and unsafe characters from a user-influenced filename."""
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    if not base:
        base = default
    return base[:MAX_FILENAME_LENGTH]


def validate_upload_filename(filename: str | None) -> str:
    """Ensure an uploaded file has an allowed video extension."""
    safe = sanitize_filename(filename, default="upload")
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext or 'unknown'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}."
        )
    return safe


def human_filesize(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "unknown"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def is_within_directory(base: Path, target: Path) -> bool:
    """Guard against path traversal: target must live inside base."""
    try:
        base = base.resolve()
        target = target.resolve()
    except OSError:
        return False
    return base == target or base in target.parents


def new_temp_path(temp_dir: Path, suffix: str) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{uuid.uuid4().hex}{suffix}"


def remove_path(path: Path) -> None:
    """Best-effort removal of a temp file or directory."""
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_old_temp_files(temp_dir: Path, max_age_seconds: int) -> int:
    """Delete temp files/dirs older than the TTL. Returns the number removed."""
    removed = 0
    if not temp_dir.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    for path in temp_dir.iterdir():
        if path.name == ".gitkeep":
            continue
        try:
            if path.stat().st_mtime < cutoff:
                remove_path(path)
                removed += 1
        except OSError:
            continue
    return removed


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding-window rate limiter (per client IP)."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/", "/api/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = self._hits.setdefault(ip, deque())
        while bucket and bucket[0] <= now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "error": "Too many requests. Please slow down and try again shortly.",
                    "code": "rate_limited",
                },
                headers={"Retry-After": str(self.window_seconds)},
            )
        bucket.append(now)
        return await call_next(request)
