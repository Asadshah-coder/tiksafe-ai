"""Tests for URL validation, filename sanitization, and upload checks."""

import pytest

from backend.core.security import (
    URLValidationError,
    sanitize_filename,
    validate_tiktok_url,
    validate_upload_filename,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@creator/video/7234567890123456789",
        "https://tiktok.com/@creator/video/7234567890123456789",
        "http://www.tiktok.com/@creator/video/123",
        "https://vm.tiktok.com/ZM2AbC123/",
        "https://vt.tiktok.com/ZSAbC123xy/",
        "https://m.tiktok.com/v/7234567890123456789.html",
        "https://www.tiktok.com/@creator/video/123?is_from_webapp=1&sender_device=pc",
        "  https://www.tiktok.com/@creator/video/123  ",
    ],
)
def test_valid_tiktok_urls(url):
    normalized = validate_tiktok_url(url)
    assert normalized.startswith(("http://", "https://"))
    assert "tiktok.com" in normalized


@pytest.mark.parametrize(
    "url,code",
    [
        ("", "empty_url"),
        ("   ", "empty_url"),
        (None, "empty_url"),
        ("not a url", "invalid_scheme"),
        ("ftp://www.tiktok.com/@x/video/1", "invalid_scheme"),
        ("https://youtube.com/watch?v=abc", "unsupported_domain"),
        ("https://tiktok.com.evil.com/@x/video/1", "unsupported_domain"),
        ("https://eviltiktok.com/@x/video/1", "unsupported_domain"),
        ("https://www.tiktok.com/", "invalid_url"),
        ("https://www.tiktok.com", "invalid_url"),
        ("x" * 3000, "url_too_long"),
    ],
)
def test_invalid_tiktok_urls(url, code):
    with pytest.raises(URLValidationError) as exc_info:
        validate_tiktok_url(url)
    assert exc_info.value.code == code


def test_url_normalization_strips_fragment():
    out = validate_tiktok_url("https://www.tiktok.com/@a/video/1#frag")
    assert "#frag" not in out


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("my video.mp4", "my_video.mp4"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\x.mp4", "x.mp4"),
        ("", "file"),
        ("...", "file"),
        ("a" * 200 + ".mp4", ("a" * 200 + ".mp4")[:120]),
        ("weird<>name?.mp4", "weird_name_.mp4"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_validate_upload_filename_ok():
    assert validate_upload_filename("clip.MP4") == "clip.MP4"
    assert validate_upload_filename("my movie.mov") == "my_movie.mov"


def test_validate_upload_filename_rejects_bad_types():
    with pytest.raises(ValueError):
        validate_upload_filename("payload.exe")
    with pytest.raises(ValueError):
        validate_upload_filename("noextension")
