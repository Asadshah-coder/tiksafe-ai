"""Download helpers for publicly available media.

Every function returns (file_path, work_dir, meta). The caller is responsible
for deleting work_dir (see routes, which do this via BackgroundTask).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import httpx
import yt_dlp

from ..core.config import get_settings
from ..core.logging import get_logger
from ..core.security import human_filesize, validate_tiktok_url
from . import extractor, ffmpeg_service

log = get_logger("downloader")

SAFE_FORMAT_RE = re.compile(r"^[\w\-\+\/\[\]\(\)\:\.\,\s\<\>\=]+$")
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


class DownloadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _download_dir() -> Path:
    target = get_settings().temp_dir / "downloads" / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=True)
    return target


def _safe_format_selector(format_id: str | None) -> str:
    if format_id and SAFE_FORMAT_RE.match(format_id):
        return format_id
    return "best"


def _enforce_download_size(path: Path) -> None:
    limit = get_settings().max_download_mb * 1024 * 1024
    size = path.stat().st_size
    if size > limit:
        raise DownloadError(
            "file_too_large",
            f"This file is {human_filesize(size)}, which exceeds the "
            f"{get_settings().max_download_mb} MB download limit.",
        )


def download_video(
    raw_url: str, format_id: str | None = "best"
) -> tuple[Path, Path, dict]:
    """Download the best available public video file to a temp working directory."""
    url = validate_tiktok_url(raw_url)
    work_dir = _download_dir()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": get_settings().extraction_timeout_seconds,
        "retries": 2,
        "no_color": True,
        "format": _safe_format_selector(format_id),
        "outtmpl": str(work_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        code, message = extractor._classify_error(str(exc))
        raise DownloadError(code, message) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("download failed")
        raise DownloadError(
            "download_failed", "The download failed. Please try again."
        ) from exc

    candidates = [
        p for p in work_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not candidates:
        raise DownloadError(
            "download_failed",
            "The download finished but no video file was produced.",
        )
    media = max(candidates, key=lambda p: p.stat().st_size)
    _enforce_download_size(media)
    meta = {
        "title": (info or {}).get("title") or "tiktok-video",
        "ext": media.suffix.lstrip(".") or "mp4",
        "size": media.stat().st_size,
    }
    return media, work_dir, meta


def download_audio(
    raw_url: str, bitrate: str = "128k"
) -> tuple[Path, Path, dict]:
    """Download public audio and convert it to MP3 via FFmpeg."""
    if not re.fullmatch(r"\d{2,3}k", bitrate or ""):
        bitrate = "128k"
    media, work_dir, meta = download_video(raw_url, "bestaudio/best")
    out = work_dir / "audio.mp3"
    try:
        ffmpeg_service.extract_audio(media, out, bitrate=bitrate)
    except (ffmpeg_service.FFmpegError, ffmpeg_service.FFmpegNotAvailable) as exc:
        raise DownloadError("audio_failed", str(exc)) from exc
    meta = {**meta, "ext": "mp3", "size": out.stat().st_size}
    return out, work_dir, meta


def download_thumbnail(raw_url: str) -> tuple[Path, Path, dict]:
    """Fetch the video's public thumbnail image."""
    info = extractor.extract_metadata(raw_url)
    if not info.thumbnail:
        raise DownloadError(
            "no_thumbnail", "No thumbnail is available for this video."
        )
    work_dir = _download_dir()
    out = work_dir / "thumbnail.jpg"
    try:
        with httpx.stream(
            "GET",
            info.thumbnail,
            timeout=get_settings().request_timeout_seconds,
            follow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type:
                raise DownloadError(
                    "no_thumbnail", "The thumbnail could not be retrieved."
                )
            size = 0
            with out.open("wb") as fh:
                for chunk in resp.iter_bytes(65536):
                    size += len(chunk)
                    if size > 15 * 1024 * 1024:
                        raise DownloadError(
                            "file_too_large", "The thumbnail is too large."
                        )
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        raise DownloadError(
            "network_timeout",
            "Could not download the thumbnail. Please try again.",
        ) from exc
    meta = {"title": info.title or "tiktok-video", "ext": "jpg",
            "size": out.stat().st_size}
    return out, work_dir, meta
