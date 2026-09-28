"""Shared pytest fixtures: project root on sys.path, test env, API test client."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("TIKSAFE_ENV", "test")
for var in ("OPENAI_API_KEY", "GEMINI_API_KEY",
            "TIKSAFE_OPENAI_API_KEY", "TIKSAFE_GEMINI_API_KEY"):
    os.environ.pop(var, None)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)
