"""POST /api/download, /api/audio, /api/thumbnail — file downloads.

Each endpoint streams a file produced in a temp working directory and deletes
that directory afterwards via a BackgroundTask, so no media lingers on disk.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ...core.logging import get_logger
from ...core.security import remove_path, sanitize_filename
from ...schemas.media import AudioRequest, DownloadRequest, ThumbnailRequest
from ...services import downloader

log = get_logger("routes.download")

router = APIRouter()

_MIME_BY_EXT = {
    "mp4": "video/mp4",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "mp3": "audio/mpeg",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


def _file_response(path: Path, work_dir: Path, filename: str, ext: str) -> FileResponse:
    background = BackgroundTask(remove_path, work_dir)
    return FileResponse(
        path,
        media_type=_MIME_BY_EXT.get(ext.lower(), "application/octet-stream"),
        filename=filename,
        background=background,
    )


@router.post("/download", summary="Download the video file")
def download_video(payload: DownloadRequest) -> FileResponse:
    work_dir: Path | None = None
    try:
        path, work_dir, meta = downloader.download_video(
            payload.url, payload.format_id
        )
    except Exception:
        if work_dir is not None:
            remove_path(work_dir)
        raise
    filename = sanitize_filename(
        f"{meta.get('title', 'tiktok-video')}.{meta.get('ext', 'mp4')}",
        default="tiktok-video.mp4",
    )
    return _file_response(path, work_dir, filename, meta.get("ext", "mp4"))


@router.post("/audio", summary="Extract audio as MP3")
def download_audio(payload: AudioRequest) -> FileResponse:
    work_dir: Path | None = None
    try:
        path, work_dir, meta = downloader.download_audio(
            payload.url, payload.bitrate
        )
    except Exception:
        if work_dir is not None:
            remove_path(work_dir)
        raise
    filename = sanitize_filename(
        f"{meta.get('title', 'tiktok-audio')}.mp3", default="tiktok-audio.mp3"
    )
    return _file_response(path, work_dir, filename, "mp3")


@router.post("/thumbnail", summary="Download the video thumbnail")
def download_thumbnail(payload: ThumbnailRequest) -> FileResponse:
    work_dir: Path | None = None
    try:
        path, work_dir, meta = downloader.download_thumbnail(payload.url)
    except Exception:
        if work_dir is not None:
            remove_path(work_dir)
        raise
    filename = sanitize_filename(
        f"{meta.get('title', 'tiktok-thumbnail')}.jpg",
        default="tiktok-thumbnail.jpg",
    )
    return _file_response(path, work_dir, filename, "jpg")
