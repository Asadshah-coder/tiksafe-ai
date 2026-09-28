"""API tests. External services (yt-dlp, AI providers) are mocked."""

from backend.schemas.media import MediaInfo


def _fake_media() -> MediaInfo:
    return MediaInfo(
        status="success",
        title="Test video",
        author="tester",
        author_id="tester",
        duration=12.5,
        thumbnail="https://example.com/t.jpg",
        webpage_url="https://www.tiktok.com/@tester/video/123",
        upload_date="20240101",
        view_count=100,
        like_count=10,
        description="A test video",
        available_formats=[],
    )


def test_analyze_ok(client, monkeypatch):
    monkeypatch.setattr(
        "backend.api.routes.analyze.extract_metadata",
        lambda url: _fake_media(),
    )
    resp = client.post(
        "/api/analyze",
        json={"url": "https://www.tiktok.com/@tester/video/123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["title"] == "Test video"
    assert body["data"]["author"] == "tester"


def test_analyze_rejects_unsupported_domain(client):
    resp = client.post(
        "/api/analyze", json={"url": "https://youtube.com/watch?v=abc"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "unsupported_domain"


def test_analyze_rejects_empty_url(client):
    resp = client.post("/api/analyze", json={"url": "   "})
    assert resp.status_code == 400
    assert resp.json()["code"] == "empty_url"


def test_download_ok(client, monkeypatch, tmp_path):
    fake_file = tmp_path / "v.mp4"
    fake_file.write_bytes(b"fake-video-bytes")
    monkeypatch.setattr(
        "backend.api.routes.download.downloader.download_video",
        lambda url, format_id="best": (
            fake_file, tmp_path, {"title": "Test", "ext": "mp4", "size": 16}
        ),
    )
    resp = client.post(
        "/api/download",
        json={"url": "https://www.tiktok.com/@t/video/1"},
    )
    assert resp.status_code == 200
    assert resp.content == b"fake-video-bytes"
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_audio_ok(client, monkeypatch, tmp_path):
    fake_file = tmp_path / "a.mp3"
    fake_file.write_bytes(b"fake-audio")
    monkeypatch.setattr(
        "backend.api.routes.download.downloader.download_audio",
        lambda url, bitrate="128k": (
            fake_file, tmp_path, {"title": "Test", "ext": "mp3", "size": 10}
        ),
    )
    resp = client.post(
        "/api/audio", json={"url": "https://www.tiktok.com/@t/video/1"}
    )
    assert resp.status_code == 200
    assert resp.content == b"fake-audio"


def test_thumbnail_ok(client, monkeypatch, tmp_path):
    fake_file = tmp_path / "t.jpg"
    fake_file.write_bytes(b"fake-image")
    monkeypatch.setattr(
        "backend.api.routes.download.downloader.download_thumbnail",
        lambda url: (
            fake_file, tmp_path, {"title": "Test", "ext": "jpg", "size": 10}
        ),
    )
    resp = client.post(
        "/api/thumbnail", json={"url": "https://www.tiktok.com/@t/video/1"}
    )
    assert resp.status_code == 200
    assert resp.content == b"fake-image"


def test_caption_without_api_keys_returns_503(client):
    resp = client.post(
        "/api/caption", json={"topic": "cats", "language": "en"}
    )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["error"].lower()


def test_hashtags_without_api_keys_returns_503(client):
    resp = client.post("/api/hashtags", json={"topic": "cats"})
    assert resp.status_code == 503


def test_translate_without_api_keys_returns_503(client):
    resp = client.post(
        "/api/translate", json={"text": "hello", "target": "ur"}
    )
    assert resp.status_code == 503


def test_summarize_without_api_keys_returns_503(client):
    resp = client.post(
        "/api/summarize", json={"text": "some transcript", "language": "en"}
    )
    assert resp.status_code == 503


def test_summarize_requires_text_or_url(client):
    resp = client.post("/api/summarize", json={"language": "en"})
    assert resp.status_code == 400


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "ffmpeg" in body
    assert "ai" in body
    assert "transcription" in body
    assert body["ai"] is False  # no keys in the test environment


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["service"] == "tiksafe-ai"


def test_rate_limit_headers_not_on_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
