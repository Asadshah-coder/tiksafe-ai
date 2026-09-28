"""Tests for video processing: validation paths and pure FFmpeg helpers."""

import pytest

from backend.services import ffmpeg_service


def _upload(client, monkeypatch, filename, data, operation, **fields):
    monkeypatch.setattr(
        "backend.api.routes.processing.ffmpeg_service.ffmpeg_available",
        lambda: True,
    )
    payload = {"operation": operation, **fields}
    return client.post(
        "/api/process-video",
        files={"file": (filename, data, "video/mp4")},
        data=payload,
    )


def test_rejects_disallowed_extension(client, monkeypatch):
    resp = _upload(client, monkeypatch, "payload.exe", b"xxx", "compress")
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["error"]


def test_rejects_unknown_operation(client, monkeypatch):
    monkeypatch.setattr(
        "backend.api.routes.processing.ffmpeg_service.ffmpeg_available",
        lambda: True,
    )
    resp = client.post(
        "/api/process-video",
        files={"file": ("v.mp4", b"xxx", "video/mp4")},
        data={"operation": "explode"},
    )
    assert resp.status_code == 400


def test_rejects_empty_file(client, monkeypatch):
    resp = _upload(client, monkeypatch, "v.mp4", b"", "convert")
    assert resp.status_code == 400


def test_trim_requires_start(client, monkeypatch):
    monkeypatch.setattr(
        "backend.api.routes.processing.ffmpeg_service.ffmpeg_available",
        lambda: True,
    )
    resp = client.post(
        "/api/process-video",
        files={"file": ("v.mp4", b"xxx", "video/mp4")},
        data={"operation": "trim", "start": "-1"},
    )
    assert resp.status_code == 400


def test_crop_requires_dimensions(client, monkeypatch):
    resp = _upload(client, monkeypatch, "v.mp4", b"xxx", "crop")
    assert resp.status_code == 400


def test_unavailable_ffmpeg_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        "backend.api.routes.processing.ffmpeg_service.ffmpeg_available",
        lambda: False,
    )
    resp = client.post(
        "/api/process-video",
        files={"file": ("v.mp4", b"xxx", "video/mp4")},
        data={"operation": "convert"},
    )
    assert resp.status_code == 503


def _stub_temp_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.services.ffmpeg_service.get_settings",
        lambda: type(
            "S", (), {"temp_dir": tmp_path, "ffmpeg_timeout_seconds": 5}
        )(),
    )


def test_write_srt_format(tmp_path, monkeypatch):
    _stub_temp_dir(monkeypatch, tmp_path)
    segments = [
        {"start": 0.5, "end": 2.25, "text": "Hello world"},
        {"start": 65.0, "end": 67.5, "text": "Second line"},
    ]
    dst = tmp_path / "out.srt"
    ffmpeg_service.write_srt(segments, dst)
    content = dst.read_text(encoding="utf-8")
    assert "00:00:00,500 --> 00:00:02,250" in content
    assert "00:01:05,000 --> 00:01:07,500" in content
    assert "Hello world" in content
    assert "Second line" in content


def test_write_srt_skips_empty_segments(tmp_path, monkeypatch):
    _stub_temp_dir(monkeypatch, tmp_path)
    dst = tmp_path / "out.srt"
    ffmpeg_service.write_srt([{"start": 0, "end": 1, "text": "   "}], dst)
    assert dst.read_text(encoding="utf-8").strip() == ""


def test_ffmpeg_checked_path_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.services.ffmpeg_service.get_settings",
        lambda: type("S", (), {"temp_dir": tmp_path, "ffmpeg_timeout_seconds": 5})(),
    )
    with pytest.raises(ffmpeg_service.FFmpegError):
        ffmpeg_service._checked_path("/etc/passwd")


def test_ffmpeg_available_returns_bool():
    assert isinstance(ffmpeg_service.ffmpeg_available(), bool)


needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_service.ffmpeg_available(),
    reason="FFmpeg not installed",
)


@needs_ffmpeg
def test_extract_audio_rejects_silent_video(tmp_path, monkeypatch):
    import subprocess

    _stub_temp_dir(monkeypatch, tmp_path)
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-an", str(silent)],
        check=True, timeout=60,
    )
    assert ffmpeg_service.has_audio_stream(silent) is False
    with pytest.raises(ffmpeg_service.FFmpegError, match="no audio track"):
        ffmpeg_service.extract_audio(silent, tmp_path / "out.mp3")


@needs_ffmpeg
def test_api_audio_on_silent_video_gives_clear_error(client, monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(
        "backend.api.routes.processing.ffmpeg_service.ffmpeg_available",
        lambda: True,
    )
    # Point the API temp dir at tmp_path so the silent clip can be built there
    from backend.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("TIKSAFE_TEMP_DIR", str(tmp_path))
    try:
        silent = tmp_path / "silent.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
             "-c:v", "libx264", "-an", str(silent)],
            check=True, timeout=60,
        )
        resp = client.post(
            "/api/process-video",
            files={"file": ("silent.mp4", silent.read_bytes(), "video/mp4")},
            data={"operation": "audio"},
        )
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 422
    assert "no audio track" in resp.json()["error"]


@needs_ffmpeg
def test_video_to_gif(tmp_path, monkeypatch):
    import subprocess

    _stub_temp_dir(monkeypatch, tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-an", str(src)],
        check=True, timeout=60,
    )
    dst = ffmpeg_service.video_to_gif(src, tmp_path / "out.gif", width=160, fps=5)
    assert dst.exists() and dst.stat().st_size > 0
    assert not (tmp_path / "out_palette.png").exists()


@needs_ffmpeg
def test_mute_video_removes_audio(tmp_path, monkeypatch):
    import subprocess

    _stub_temp_dir(monkeypatch, tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
        check=True, timeout=60,
    )
    assert ffmpeg_service.has_audio_stream(src) is True
    dst = ffmpeg_service.mute_video(src, tmp_path / "muted.mp4")
    assert dst.exists()
    assert ffmpeg_service.has_audio_stream(dst) is False


@needs_ffmpeg
def test_probe_returns_curated_metadata(tmp_path, monkeypatch):
    import subprocess

    _stub_temp_dir(monkeypatch, tmp_path)
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=2:size=640x480:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
        check=True, timeout=60,
    )
    info = ffmpeg_service.probe(src)
    assert info["video"]["width"] == 640
    assert info["video"]["height"] == 480
    assert info["audio"]["codec"] == "aac"
    assert 1.5 < info["duration_seconds"] < 2.5


@needs_ffmpeg
def test_video_info_endpoint(client, monkeypatch, tmp_path):
    import subprocess

    from backend.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("TIKSAFE_TEMP_DIR", str(tmp_path))
    try:
        src = tmp_path / "up.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
             "-c:v", "libx264", "-an", str(src)],
            check=True, timeout=60,
        )
        resp = client.post(
            "/api/video-info",
            files={"file": ("up.mp4", src.read_bytes(), "video/mp4")},
        )
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 200
    info = resp.json()["info"]
    assert info["video"]["width"] == 320
    assert info["audio"] is None


def test_quality_format_mapping():
    from backend.api.routes.download import _quality_format

    assert _quality_format("best") == "bv*+ba/b"
    assert "1080" in _quality_format("high")
    assert "720" in _quality_format("medium")
    assert "480" in _quality_format("low")


def test_download_request_rejects_bad_quality():
    import pytest as _pytest

    from backend.schemas.media import DownloadRequest

    with _pytest.raises(Exception):
        DownloadRequest(url="https://www.tiktok.com/@x/video/1", quality="ultra")
