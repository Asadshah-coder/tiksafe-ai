# TikSave AI — Architecture

## Overview

TikSave AI is a two-tier web application:

- **Backend** — FastAPI (`backend/`): validation, media extraction, downloads,
  video processing, and AI toolkit endpoints.
- **Frontend** — Streamlit (`frontend/`): a modern dashboard that talks to the
  backend over HTTP. It can auto-start a local backend subprocess
  (`TIKSAFE_API_URL` unset) or point at a separately hosted API.

```
browser ──▶ Streamlit UI ──HTTP──▶ FastAPI ──┬──▶ yt-dlp (public metadata/downloads)
                                             ├──▶ FFmpeg subprocess (arg arrays only)
                                             ├──▶ Whisper (lazy import, optional)
                                             └──▶ OpenAI / Gemini (optional keys)
```

## Backend layers

| Layer | Location | Responsibility |
|---|---|---|
| API routes | `backend/api/routes/` | HTTP in/out, Pydantic schemas, file responses |
| Services | `backend/services/` | `extractor`, `downloader`, `ffmpeg_service`, `transcription`, `ai_service` |
| AI providers | `backend/ai/` | `base` (ABC), `openai`, `gemini` — swappable |
| Schemas | `backend/schemas/` | `media`, `ai` request/response models |
| Core | `backend/core/` | `config` (env), `logging`, `security` |

Extraction logic never lives in Streamlit — the frontend is a thin client.

## Key flows

**Analyze:** `POST /api/analyze` → `validate_tiktok_url()` → yt-dlp
`extract_info(download=False)` → `MediaInfo` (title, author, duration,
thumbnail, formats). Failures are classified (`private_content`,
`unavailable`, `network_timeout`, …) and mapped to friendly HTTP statuses.

**Download:** `POST /api/download|/audio|/thumbnail` → temp working dir per
request → `FileResponse` + `BackgroundTask(remove_path)` → directory deleted
after the response is sent. A periodic task (every 10 min) also purges entries
older than `TIKSAFE_TEMP_FILE_TTL_SECONDS`.

**Process video (Clean Export):** `POST /api/process-video` (multipart) →
extension + size validation → FFmpeg via argument arrays with timeouts →
result streamed back, working dir removed. Only user-uploaded files are
processed here — this path never touches third-party platform content.

**Transcribe:** download public audio → `transcribe_audio()` (faster-whisper,
else openai-whisper, else 503) → text + timestamped segments.

**AI features:** `get_provider()` picks OpenAI first, then Gemini; with no key
configured every AI endpoint returns **503 "AI features are currently
unavailable"** instead of crashing. System prompts instruct the model to use
only provided facts and never invent details about the video.

## Security model

- Strict TikTok domain allowlist; URLs are parsed with `urllib`, never regex-matched.
- Filename sanitization, upload extension allowlist, per-request size caps.
- FFmpeg invoked with argument arrays only; paths must be inside `temp/`.
- In-memory sliding-window rate limiting; CORS configurable.
- No cookies/credentials are ever sent to TikTok; no auth, DRM, or
  access-control bypass exists anywhere in the codebase.
- Error handlers return friendly messages; stack traces are logged
  server-side only.

## Extending

- **New AI provider:** subclass `AIProvider` in `backend/ai/` and add it to
  `get_provider()` in `services/ai_service.py`.
- **New language:** add `frontend/locales/<code>.json` and register it in
  `frontend/i18n.py` (`LANGUAGES`).
- **New video operation:** add a function to `ffmpeg_service.py`, an entry in
  `EXT_BY_OPERATION`/`OPERATIONS` in `routes/processing.py`, and a label in
  the frontend.
