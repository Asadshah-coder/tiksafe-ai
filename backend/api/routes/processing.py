"""POST /api/process-video — edit user-uploaded videos with FFmpeg.

This is the "Clean Export" path: it only ever touches videos the user uploads
themselves (their own originals or media they have permission to edit).
"""

import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ...core.config import get_settings
from ...core.logging import get_logger
from ...core.security import (
    human_filesize,
    remove_path,
    validate_upload_filename,
)
from ...services import ffmpeg_service, transcription
from ...services.ffmpeg_service import FFmpegError, FFmpegNotAvailable
from ...services.transcription import TranscriptionError

log = get_logger("routes.processing")

router = APIRouter()

OPERATIONS = {
    "trim", "crop", "resize", "compress", "convert", "audio", "thumbnail",
    "subtitles", "gif", "mute",
}
EXT_BY_OPERATION = {
    "trim": ".mp4", "crop": ".mp4", "resize": ".mp4", "compress": ".mp4",
    "convert": ".mp4", "audio": ".mp3", "thumbnail": ".jpg",
    "subtitles": ".srt", "gif": ".gif", "mute": ".mp4",
}
MIME_BY_EXT = {
    ".mp4": "video/mp4", ".mp3": "audio/mpeg",
    ".jpg": "image/jpeg", ".srt": "text/plain", ".gif": "image/gif",
}


@router.post("/video-info", summary="Inspect an uploaded video's metadata")
async def video_info(file: UploadFile = File(...)) -> dict:
    """Return ffprobe metadata (duration, resolution, codecs...) for an upload."""
    settings = get_settings()
    if not ffmpeg_service.ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="Media inspection is unavailable: FFmpeg is not installed on this server.",
        )
    try:
        safe_name = validate_upload_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    work_dir = settings.temp_dir / "probe" / uuid.uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)
    src = work_dir / safe_name
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with src.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than the {settings.max_upload_mb} MB upload limit.",
                    )
                fh.write(chunk)
    except HTTPException:
        remove_path(work_dir)
        raise
    if size == 0:
        remove_path(work_dir)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        info = await run_in_threadpool(ffmpeg_service.probe, src)
    except (FFmpegError, FFmpegNotAvailable) as exc:
        remove_path(work_dir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    remove_path(work_dir)
    return {"ok": True, "info": info}


@router.post("/process-video", summary="Process an uploaded video")
async def process_video(
    file: UploadFile = File(...),
    operation: str = Form(...),
    start: Optional[float] = Form(None),
    end: Optional[float] = Form(None),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    x: int = Form(0),
    y: int = Form(0),
    crf: int = Form(28),
    timestamp: str = Form("00:00:01"),
) -> FileResponse:
    settings = get_settings()
    op = (operation or "").strip().lower()
    if op not in OPERATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown operation '{operation}'. Choose one of: {', '.join(sorted(OPERATIONS))}.",
        )
    if not ffmpeg_service.ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="Video processing is unavailable: FFmpeg is not installed on this server.",
        )
    try:
        safe_name = validate_upload_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    work_dir = settings.temp_dir / "processing" / uuid.uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)
    src = work_dir / safe_name

    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with src.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than the {settings.max_upload_mb} MB upload limit.",
                    )
                fh.write(chunk)
    except HTTPException:
        remove_path(work_dir)
        raise
    if size == 0:
        remove_path(work_dir)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    ext = EXT_BY_OPERATION[op]
    dst = work_dir / f"output{ext}"
    started = time.perf_counter()
    try:
        if op == "trim":
            if start is None or start < 0:
                raise HTTPException(
                    status_code=400,
                    detail="Trim needs a valid start time in seconds.",
                )
            await run_in_threadpool(ffmpeg_service.trim_video, src, dst, start, end)
        elif op == "crop":
            if not width or not height or width <= 0 or height <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Crop needs a positive width and height.",
                )
            await run_in_threadpool(
                ffmpeg_service.crop_video, src, dst, width, height, x, y
            )
        elif op == "resize":
            if not width or not height:
                raise HTTPException(
                    status_code=400,
                    detail="Resize needs width and height (use -1 to keep aspect ratio).",
                )
            await run_in_threadpool(
                ffmpeg_service.resize_video, src, dst, width, height
            )
        elif op == "compress":
            await run_in_threadpool(ffmpeg_service.compress_video, src, dst, crf)
        elif op == "convert":
            await run_in_threadpool(ffmpeg_service.convert_to_mp4, src, dst)
        elif op == "audio":
            await run_in_threadpool(ffmpeg_service.extract_audio, src, dst)
        elif op == "thumbnail":
            await run_in_threadpool(
                ffmpeg_service.extract_frame, src, dst, timestamp
            )
        elif op == "subtitles":
            audio_tmp = work_dir / "subs_audio.mp3"
            await run_in_threadpool(ffmpeg_service.extract_audio, src, audio_tmp)
            _text, segments = await run_in_threadpool(
                transcription.transcribe_audio, audio_tmp
            )
            ffmpeg_service.write_srt(segments, dst)
        elif op == "gif":
            await run_in_threadpool(ffmpeg_service.video_to_gif, src, dst)
        elif op == "mute":
            await run_in_threadpool(ffmpeg_service.mute_video, src, dst)
    except HTTPException:
        remove_path(work_dir)
        raise
    except (FFmpegError, FFmpegNotAvailable) as exc:
        remove_path(work_dir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TranscriptionError as exc:
        remove_path(work_dir)
        status = 503 if exc.code == "unavailable" else 422
        raise HTTPException(status_code=status, detail=exc.message) from exc

    elapsed = time.perf_counter() - started
    processed_size = dst.stat().st_size if dst.exists() else 0
    log.info(
        "processed %s -> %s (%s to %s in %.1fs)",
        safe_name, op, human_filesize(size), human_filesize(processed_size), elapsed,
    )

    response = FileResponse(
        dst,
        media_type=MIME_BY_EXT[ext],
        filename=f"tiksafe-{op}{ext}",
        background=BackgroundTask(remove_path, work_dir),
    )
    response.headers["X-Original-Bytes"] = str(size)
    response.headers["X-Processed-Bytes"] = str(processed_size)
    response.headers["X-Processing-Seconds"] = f"{elapsed:.1f}"
    return response
