"""FFmpeg operations via safe subprocess argument arrays.

Rules enforced here:
- Never shell=True, never build shell strings from user input.
- All paths must live inside the configured temp directory.
- Every call has a timeout and captures stderr for server-side logging.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from ..core.config import get_settings
from ..core.logging import get_logger
from ..core.security import is_within_directory

log = get_logger("ffmpeg")


class FFmpegError(Exception):
    """A user-facing FFmpeg failure (no stack traces leak to clients)."""


class FFmpegNotAvailable(Exception):
    """FFmpeg is not installed on this machine."""


@lru_cache(maxsize=1)
def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FFmpegNotAvailable(
            "FFmpeg is not installed on this server, so video processing "
            "is unavailable."
        )
    return found


def ffmpeg_available() -> bool:
    try:
        ffmpeg_binary()
        return True
    except FFmpegNotAvailable:
        return False


def _checked_path(path: str | Path) -> Path:
    candidate = Path(path)
    if not is_within_directory(get_settings().temp_dir, candidate):
        raise FFmpegError("Refusing to process a file outside the working directory.")
    return candidate


def run_ffmpeg(args: list[str], timeout: int | None = None) -> None:
    binary = ffmpeg_binary()
    timeout = timeout or get_settings().ffmpeg_timeout_seconds
    cmd = [binary, "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise FFmpegNotAvailable(
            "FFmpeg is not installed on this server."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(
            "Processing took too long and was stopped. Try a shorter clip."
        ) from exc
    if proc.returncode != 0:
        log.warning("ffmpeg failed: %s", (proc.stderr or "").strip()[:500])
        raise FFmpegError(
            "Media processing failed. The file may be corrupted or in an "
            "unsupported format."
        )


def has_audio_stream(src: str | Path) -> bool:
    """Check via ffprobe whether the file has an audio stream.

    Returns True when unsure (e.g. ffprobe missing) so FFmpeg still gets
    a chance and reports its own error.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0",
             str(_checked_path(src))],
            capture_output=True, text=True, timeout=30,
        )
        return bool(proc.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return True


def extract_audio(src: str | Path, dst: str | Path, bitrate: str = "128k") -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    if not has_audio_stream(src_p):
        raise FFmpegError(
            "This video has no audio track, so there is nothing to extract."
        )
    run_ffmpeg(
        ["-i", str(src_p), "-vn", "-c:a", "libmp3lame", "-b:a", bitrate, str(dst_p)]
    )
    return dst_p


def trim_video(
    src: str | Path, dst: str | Path, start: float, end: float | None
) -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    if start < 0:
        raise FFmpegError("Trim start time must be zero or positive.")
    if end is not None and end <= start:
        raise FFmpegError("Trim end time must be after the start time.")
    args = ["-ss", f"{start:.3f}", "-i", str(src_p)]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-c", "copy", str(dst_p)]
    run_ffmpeg(args)
    return dst_p


def crop_video(
    src: str | Path, dst: str | Path, width: int, height: int, x: int = 0, y: int = 0
) -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    if width <= 0 or height <= 0:
        raise FFmpegError("Crop width and height must be positive.")
    if x < 0 or y < 0:
        raise FFmpegError("Crop offsets must be zero or positive.")
    run_ffmpeg(
        ["-i", str(src_p), "-vf", f"crop={width}:{height}:{x}:{y}",
         "-c:a", "copy", str(dst_p)]
    )
    return dst_p


def resize_video(
    src: str | Path, dst: str | Path, width: int, height: int
) -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    if width == 0 or height == 0:
        raise FFmpegError("Resize dimensions must not be zero (use -1 to keep aspect ratio).")
    run_ffmpeg(
        ["-i", str(src_p), "-vf", f"scale={width}:{height}",
         "-c:a", "copy", str(dst_p)]
    )
    return dst_p


def compress_video(src: str | Path, dst: str | Path, crf: int = 28) -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    crf = min(max(int(crf), 18), 40)
    run_ffmpeg(
        ["-i", str(src_p), "-vcodec", "libx264", "-crf", str(crf),
         "-preset", "medium", "-acodec", "aac", str(dst_p)]
    )
    return dst_p


def convert_to_mp4(src: str | Path, dst: str | Path) -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    run_ffmpeg(
        ["-i", str(src_p), "-c:v", "libx264", "-c:a", "aac",
         "-movflags", "+faststart", str(dst_p)]
    )
    return dst_p


def extract_frame(
    src: str | Path, dst: str | Path, timestamp: str = "00:00:01"
) -> Path:
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    run_ffmpeg(
        ["-ss", timestamp, "-i", str(src_p), "-frames:v", "1", "-q:v", "2", str(dst_p)]
    )
    return dst_p


def video_to_gif(src: str | Path, dst: str | Path, width: int = 480, fps: int = 10) -> Path:
    """Convert a video clip to an animated GIF (two-pass palette for quality)."""
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    width = min(max(int(width), 160), 1280)
    fps = min(max(int(fps), 1), 30)
    palette = dst_p.with_name(dst_p.stem + "_palette.png")
    try:
        run_ffmpeg(
            ["-i", str(src_p), "-vf",
             f"fps={fps},scale={width}:-1:flags=lanczos,palettegen",
             str(palette)]
        )
        run_ffmpeg(
            ["-i", str(src_p), "-i", str(palette), "-lavfi",
             f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse",
             str(dst_p)]
        )
    finally:
        if palette.exists():
            palette.unlink(missing_ok=True)
    return dst_p


def mute_video(src: str | Path, dst: str | Path) -> Path:
    """Remove the audio track from a video (stream copy, fast)."""
    src_p, dst_p = _checked_path(src), _checked_path(dst)
    run_ffmpeg(["-i", str(src_p), "-c:v", "copy", "-an", str(dst_p)])
    return dst_p


def probe(src: str | Path) -> dict:
    """Return curated media metadata via ffprobe (format + streams).

    Raises FFmpegError when the file cannot be read.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FFmpegError("Media analysis is unavailable on this server.")
    src_p = _checked_path(src)
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(src_p)],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise FFmpegError("Could not read media information.") from exc
    if proc.returncode != 0:
        log.warning("ffprobe failed: %s", (proc.stderr or "").strip()[:300])
        raise FFmpegError(
            "Could not read this file. It may be corrupted or unsupported."
        )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError("Could not read media information.") from exc

    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

    def _fps(raw: str | None) -> float | None:
        try:
            num, den = (raw or "0/1").split("/")
            return round(float(num) / float(den), 2) if float(den) else None
        except (ValueError, ZeroDivisionError):
            return None

    def _num(raw, cast=float):
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return None

    return {
        "filename": fmt.get("filename", "").split("/")[-1],
        "format": fmt.get("format_name"),
        "duration_seconds": _num(fmt.get("duration")),
        "size_bytes": _num(fmt.get("size"), int),
        "bitrate_kbps": round(_num(fmt.get("bit_rate"), float) / 1000, 1)
        if _num(fmt.get("bit_rate"), float) else None,
        "video": {
            "codec": video.get("codec_name"),
            "width": _num(video.get("width"), int),
            "height": _num(video.get("height"), int),
            "fps": _fps(video.get("avg_frame_rate")),
            "pixel_format": video.get("pix_fmt"),
        } if video else None,
        "audio": {
            "codec": audio.get("codec_name"),
            "sample_rate_hz": _num(audio.get("sample_rate"), int),
            "channels": _num(audio.get("channels"), int),
        } if audio else None,
    }


def probe_duration(src: str | Path) -> float | None:
    """Return media duration in seconds, or None if ffprobe is unavailable."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(_checked_path(src))],
            capture_output=True, text=True, timeout=30,
        )
        return float(proc.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(int(seconds * 1000), 0)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def write_srt(segments: list[dict], dst: str | Path) -> Path:
    """Write transcript segments to a SubRip (.srt) subtitle file."""
    dst_p = _checked_path(dst)
    lines: list[str] = []
    for index, seg in enumerate(segments, start=1):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        lines.append(str(index))
        lines.append(
            f"{_srt_timestamp(float(seg.get('start', 0)))} --> "
            f"{_srt_timestamp(float(seg.get('end', 0)))}"
        )
        lines.append(text)
        lines.append("")
    dst_p.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return dst_p
