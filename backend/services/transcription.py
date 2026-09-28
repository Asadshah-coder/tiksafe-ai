"""Speech-to-text via Whisper (faster-whisper preferred, openai-whisper fallback).

The engine is imported lazily so the API runs fine without it; callers get a
clear 'unavailable' error instead of a crash.
"""

from __future__ import annotations

from pathlib import Path

from ..core.config import get_settings
from ..core.logging import get_logger
from ..core.security import is_within_directory

log = get_logger("transcription")


class TranscriptionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _engine() -> str | None:
    try:
        import faster_whisper  # noqa: F401

        return "faster-whisper"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401

        return "whisper"
    except ImportError:
        pass
    return None


def whisper_available() -> bool:
    return _engine() is not None


def transcribe_audio(
    audio_path: str | Path, language: str | None = None
) -> tuple[str, list[dict]]:
    """Transcribe an audio file. Returns (full_text, segments)."""
    path = Path(audio_path)
    settings = get_settings()
    if not is_within_directory(settings.temp_dir, path) or not path.exists():
        raise TranscriptionError("invalid_file", "Audio file not found.")

    engine = _engine()
    if engine is None:
        raise TranscriptionError(
            "unavailable",
            "Speech-to-text is not installed on this server, "
            "so transcription is unavailable.",
        )

    model_name = settings.whisper_model
    try:
        if engine == "faster-whisper":
            from faster_whisper import WhisperModel

            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            raw_segments, _info = model.transcribe(
                str(path), language=language, beam_size=5
            )
            segments = [
                {
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": seg.text.strip(),
                }
                for seg in raw_segments
                if seg.text.strip()
            ]
        else:
            import whisper

            safe_model = model_name if model_name in (
                "tiny", "base", "small", "medium", "large",
            ) else "small"
            model = whisper.load_model(safe_model)
            result = model.transcribe(str(path), language=language)
            segments = [
                {
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": str(seg["text"]).strip(),
                }
                for seg in result.get("segments", [])
            ]
    except TranscriptionError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("transcription failed")
        raise TranscriptionError(
            "transcription_failed",
            "Transcription failed. The audio may be too noisy or too long.",
        ) from exc

    text = " ".join(seg["text"] for seg in segments).strip()
    if not text:
        raise TranscriptionError(
            "no_speech", "No speech was detected in this audio."
        )
    return text, segments
