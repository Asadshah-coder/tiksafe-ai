"""Media metadata extraction built on yt-dlp.

Only publicly available media is read. No authentication, no cookies, no DRM
or access-control bypass of any kind.
"""

from __future__ import annotations

import yt_dlp

from ..core.config import get_settings
from ..core.logging import get_logger
from ..core.security import human_filesize, validate_tiktok_url
from ..schemas.media import FormatOption, MediaInfo

log = get_logger("extractor")


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _ydl_opts() -> dict:
    settings = get_settings()
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": settings.extraction_timeout_seconds,
        "retries": 1,
        "no_color": True,
    }


def _classify_error(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if any(
        k in lowered
        for k in ("private video", "private", "login required", "log in", "sign in")
    ):
        return (
            "private_content",
            "This video is private or needs a login. "
            "TikSave AI only works with publicly available videos.",
        )
    if any(
        k in lowered
        for k in (
            "removed",
            "deleted",
            "not available",
            "unavailable",
            "does not exist",
            "404",
        )
    ):
        return (
            "unavailable",
            "This video is unavailable. It may have been removed or deleted.",
        )
    if "unsupported url" in lowered:
        return ("unsupported_url", "This TikTok URL format is not supported.")
    if any(
        k in lowered
        for k in ("timed out", "timeout", "network is unreachable", "connection")
    ):
        return (
            "network_timeout",
            "Network error while contacting TikTok. "
            "Please check your connection and try again.",
        )
    return (
        "extraction_failed",
        "Could not read this video. It may be restricted, region-locked, "
        "or temporarily unavailable.",
    )


def _pick_formats(info: dict) -> list[FormatOption]:
    options: list[FormatOption] = []
    for fmt in info.get("formats") or []:
        if not fmt.get("url"):
            continue
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        resolution = fmt.get("resolution")
        if not resolution:
            width, height = fmt.get("width"), fmt.get("height")
            resolution = f"{width}x{height}" if width and height else None
        options.append(
            FormatOption(
                format_id=str(fmt.get("format_id", "unknown")),
                ext=str(fmt.get("ext", "mp4")),
                resolution=resolution,
                filesize=size,
                filesize_human=human_filesize(size),
                note=fmt.get("format_note"),
                has_video=vcodec not in (None, "none"),
                has_audio=acodec not in (None, "none"),
            )
        )

    def sort_key(f: FormatOption):
        combined_mp4 = f.has_video and f.has_audio and f.ext == "mp4"
        combined = f.has_video and f.has_audio
        return (not combined_mp4, not combined)

    return sorted(options, key=sort_key)[:12]


def extract_metadata(raw_url: str) -> MediaInfo:
    """Extract structured metadata for a public TikTok video URL."""
    url = validate_tiktok_url(raw_url)
    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        code, message = _classify_error(str(exc))
        raise ExtractionError(code, message) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced as a friendly error
        log.exception("Unexpected extraction failure")
        raise ExtractionError(
            "extraction_failed",
            "Could not read this video right now. Please try again later.",
        ) from exc

    if not info:
        raise ExtractionError("unavailable", "This video is unavailable.")

    return MediaInfo(
        status="success",
        title=info.get("title") or "TikTok video",
        author=info.get("uploader") or info.get("channel"),
        author_id=info.get("uploader_id") or info.get("channel_id"),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or url,
        upload_date=info.get("upload_date"),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        description=info.get("description"),
        available_formats=_pick_formats(info),
    )
