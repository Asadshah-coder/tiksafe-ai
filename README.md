# 🎬 TikSave AI — TikTok Video Downloader & AI Toolkit

A production-quality web application that analyzes public TikTok videos, offers
download/export options for legitimately available media, edits user-uploaded
videos ("Clean Export"), and ships an AI toolkit for captions, hashtags,
transcription, summaries, and translation.

Built with **FastAPI**, **Streamlit**, **yt-dlp**, **FFmpeg**, and **Whisper**.

---

## ✨ Features

- **URL analysis** — paste a TikTok link, get title, creator, duration, views,
  likes, thumbnail, and available formats. Robust validation rejects empty,
  malformed, or off-domain URLs before anything else happens.
- **Downloads** — video (MP4), audio (MP3), and thumbnail for publicly
  available media, with file-size display and automatic temp-file cleanup.
- **Clean Export (video processing)** — upload your *own* video and trim, crop,
  resize, compress, convert to MP4, extract audio/thumbnail, or generate
  subtitles. Shows original vs. processed size and processing time.
- **AI Toolkit** (optional, needs an API key)
  - 🎯 Caption generator — professional, viral, storytelling, short, emotional, educational
  - #️⃣ Hashtag generator — primary / niche / broad
  - 🎙️ Transcription — Whisper with timestamps, TXT download
  - 📝 Summarizer — summary, key points, topics, keywords
  - 🌐 Translator — English ⇄ Urdu ⇄ Roman Urdu
- **Trilingual UI** — English, اردو, Roman Urdu (add more via `frontend/locales/`).
- **Security-first** — domain allowlist, filename sanitization, upload limits,
  rate limiting, FFmpeg via argument arrays only, no stack traces to clients.

---

## 🏗️ Architecture

```
tiksafe-ai/
├── backend/
│   ├── api/routes/      # analyze, download, ai, processing
│   ├── core/            # config, logging, security
│   ├── services/        # extractor, downloader, ffmpeg_service,
│   │                    # transcription, ai_service
│   ├── ai/              # base, openai, gemini (provider abstraction)
│   ├── schemas/         # media, ai (Pydantic models)
│   └── main.py          # FastAPI app, error handlers, cleanup jobs
├── frontend/
│   ├── streamlit_app.py # dashboard (auto-starts API if needed)
│   ├── i18n.py          # locale helper
│   └── locales/         # en, ur, roman_ur
├── tests/               # pytest suite (mocked externals)
├── docs/architecture.md # deeper design notes
├── Dockerfile / docker-compose.yml
└── temp/                # ephemeral media (auto-cleaned)
```

See [`docs/architecture.md`](docs/architecture.md) for data flows and the
security model.

## 🛠️ Tech stack

| Piece | Technology |
|---|---|
| API | FastAPI, Pydantic v2, Uvicorn |
| UI | Streamlit |
| Extraction | yt-dlp (public content only) |
| Processing | FFmpeg (subprocess, argument arrays) |
| Speech-to-text | faster-whisper (optional, lazy-loaded) |
| AI | OpenAI / Gemini via provider abstraction |
| Tests | pytest, FastAPI TestClient |
| Deploy | Docker, docker-compose |

---

## 🚀 Installation

### Prerequisites

- Python 3.10+
- FFmpeg on PATH (for video processing & audio extraction)
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: [ffmpeg.org/download](https://ffmpeg.org/download.html)

### Local development

```bash
git clone https://github.com/<you>/tiksafe-ai.git
cd tiksafe-ai

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env               # then edit .env (add API keys if you want AI)
```

Run the API:

```bash
uvicorn backend.main:app --reload
# → http://localhost:8000  (docs at /docs)
```

Run the frontend (starts its own API automatically if `TIKSAFE_API_URL` is unset):

```bash
streamlit run frontend/streamlit_app.py
# → http://localhost:8501
```

To point the UI at a separately hosted API:

```bash
TIKSAFE_API_URL=http://localhost:8000 streamlit run frontend/streamlit_app.py
```

## 🔑 Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | No | Enables AI toolkit (tried first) |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini` |
| `GEMINI_API_KEY` | No | Enables AI toolkit (fallback) |
| `GEMINI_MODEL` | No | Default `gemini-2.0-flash` |
| `TIKSAFE_MAX_UPLOAD_MB` | No | Upload cap (default 200) |
| `TIKSAFE_MAX_DOWNLOAD_MB` | No | Download cap (default 500) |
| `TIKSAFE_RATE_LIMIT_PER_MINUTE` | No | Per-IP rate limit (default 60) |
| `TIKSAFE_WHISPER_MODEL` | No | `tiny/base/small/medium/large` (default `small`) |
| `TIKSAFE_API_URL` | No | Frontend → API base URL |

Without any AI key the app runs fully; AI endpoints return
`503 "AI features are currently unavailable."`

## 🐳 Docker setup

```bash
cp .env.example .env   # add keys if you want AI features
docker compose up --build
```

- API → http://localhost:8000 (`/docs` for interactive API docs)
- Web UI → http://localhost:8501

FFmpeg is installed inside the image via `apt-get` (see `Dockerfile`).

---

## 📡 API documentation

Interactive docs: `http://localhost:8000/docs`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health + capability flags |
| `POST` | `/api/analyze` | `{url}` → video metadata & formats |
| `POST` | `/api/download` | `{url, format_id}` → video file |
| `POST` | `/api/audio` | `{url, bitrate}` → MP3 file |
| `POST` | `/api/thumbnail` | `{url}` → thumbnail image |
| `POST` | `/api/caption` | `{topic, language, styles}` → captions |
| `POST` | `/api/hashtags` | `{topic, language}` → hashtag groups |
| `POST` | `/api/transcribe` | `{url, language}` → transcript + segments |
| `POST` | `/api/summarize` | `{text?, url?, language}` → summary |
| `POST` | `/api/translate` | `{text, target}` → translation |
| `POST` | `/api/process-video` | multipart upload + operation → processed file |

`process-video` operations: `trim`, `crop`, `resize`, `compress`, `convert`,
`audio`, `thumbnail`, `subtitles`.

---

## 🧪 Testing

```bash
pytest -v
```

External services are mocked — tests need no API keys, no network, and no
FFmpeg (FFmpeg-dependent paths are validated without executing it).

---

## 🔒 Security considerations

- TikTok domain allowlist; URLs parsed with `urllib`, never trusted raw.
- Filenames sanitized; uploads restricted by extension and size.
- FFmpeg called with argument arrays only, paths confined to `temp/`, every
  call has a timeout.
- In-memory per-IP rate limiting; CORS configurable via env.
- Temp media deleted after each response + periodic TTL cleanup.
- No credentials are ever sent to TikTok; the app cannot access private,
  login-walled, or DRM-protected content — and doesn't try to.
- Errors return friendly messages; stack traces stay in server logs.

## ⚖️ Legal / usage notice

> This tool is intended for media that you own, have permission to
> download/use, or that is otherwise lawfully available for download. Users are
> responsible for complying with applicable laws, platform terms, and copyright
> requirements.

TikSave AI does not bypass authentication, DRM, access controls, or
private-account restrictions, and does not claim to download every TikTok
video. The "Clean Export" video editor only processes videos you upload
yourself.

---

## 🔮 Future improvements

- Background job queue (Celery/Redis) for long transcriptions
- Per-user history & saved projects
- Batch URL analysis
- Burned-in subtitle rendering
- More languages (locale files make this trivial)
- Prometheus metrics + structured JSON logs

## 📄 License

MIT — see [LICENSE](LICENSE).
