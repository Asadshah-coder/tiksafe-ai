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
