"""Tests for the offline keyword & hashtag helper (no AI, no network)."""

from backend.services.keywords import extract_keywords


def test_extract_keywords_basic():
    text = "My amazing travel vlog from the mountains, travel tips and mountain views"
    keywords, hashtags = extract_keywords(text, max_keywords=5)
    assert "travel" in keywords
    assert "mountains" in keywords or "mountain" in keywords
    assert all(h.startswith("#") for h in hashtags)
    assert len(keywords) <= 5


def test_extract_keywords_removes_stopwords():
    keywords, _ = extract_keywords("the and of this video is about cooking", 10)
    for stop in ("the", "and", "of", "this", "is"):
        assert stop not in keywords
    assert "cooking" in keywords


def test_extract_keywords_empty():
    keywords, hashtags = extract_keywords("", 10)
    assert keywords == []
    assert hashtags == []


def test_keywords_endpoint(client):
    resp = client.post(
        "/api/keywords",
        json={"text": "Best biryani recipe in Lahore, biryani lovers must try", "max_keywords": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["offline"] is True
    assert "biryani" in data["keywords"]
    assert "#biryani" in data["hashtags"]


def test_keywords_endpoint_validates_length(client):
    resp = client.post("/api/keywords", json={"text": "", "max_keywords": 5})
    assert resp.status_code == 422
