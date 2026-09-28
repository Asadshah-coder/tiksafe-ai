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
