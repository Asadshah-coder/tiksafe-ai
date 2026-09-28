"""Tiny i18n helper. Add a language by dropping a new JSON file in locales/."""

import json
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

LANGUAGES = {
    "en": "English",
    "ur": "اردو",
    "roman_ur": "Roman Urdu",
}


@lru_cache(maxsize=8)
def _load(lang: str) -> dict:
    path = LOCALES_DIR / f"{lang}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def t(key: str, lang: str = "en") -> str:
    """Translate a key, falling back to English, then to the key itself."""
    strings = _load(lang)
    if key in strings:
        return strings[key]
    english = _load("en")
    return english.get(key, key)
