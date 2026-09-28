"""TikSave AI — Streamlit frontend.

Self-contained: if TIKSAFE_API_URL is not set, the FastAPI backend is started
automatically as a subprocess (works on Streamlit Community Cloud).
Set TIKSAFE_API_URL to point at a separately hosted API instead.
"""

import atexit
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.i18n import LANGUAGES, t  # noqa: E402

st.set_page_config(
    page_title="TikSave AI — Media Downloader & AI Video Toolkit",
    page_icon="🎬",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Backend bootstrap
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/api/health", timeout=3)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.5)
    return False


@st.cache_resource(show_spinner=False)
def get_api_base() -> str:
    """Return the API base URL, starting a local backend if needed."""
    env_url = os.environ.get("TIKSAFE_API_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(proc.terminate)
    base = f"http://127.0.0.1:{port}"
    if not _wait_for_health(base):
        proc.terminate()
        raise RuntimeError("The API server did not start in time.")
    return base


class APIError(Exception):
    pass


def _api_error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return str(data.get("error") or f"Request failed (HTTP {resp.status_code}).")
    except ValueError:
        return f"Request failed (HTTP {resp.status_code})."


def api_health() -> dict:
    try:
        resp = httpx.get(f"{API_BASE}/api/health", timeout=10)
        return resp.json() if resp.status_code == 200 else {}
    except httpx.HTTPError:
        return {}


def api_post(path: str, payload: dict, timeout: int = 120) -> dict:
    try:
        resp = httpx.post(f"{API_BASE}{path}", json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise APIError(f"Could not reach the API server: {exc}") from exc
    if resp.status_code != 200:
        raise APIError(_api_error_message(resp))
    return resp.json()


def api_download(path: str, payload: dict, timeout: int = 600) -> tuple[bytes, str]:
    try:
        resp = httpx.post(f"{API_BASE}{path}", json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise APIError(f"Could not reach the API server: {exc}") from exc
    if resp.status_code != 200:
        raise APIError(_api_error_message(resp))
    filename = "download"
    content_disposition = resp.headers.get("content-disposition", "")
    if "filename=" in content_disposition:
        filename = content_disposition.split("filename=")[1].strip().strip('"')
    return resp.content, filename


def api_upload_process(
    file_bytes: bytes, filename: str, mime: str, fields: dict, timeout: int = 900
) -> tuple[bytes, str, dict]:
    try:
        resp = httpx.post(
            f"{API_BASE}/api/process-video",
            files={"file": (filename, file_bytes, mime)},
            data=fields,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise APIError(f"Could not reach the API server: {exc}") from exc
    if resp.status_code != 200:
        raise APIError(_api_error_message(resp))
    filename_out = "processed"
    content_disposition = resp.headers.get("content-disposition", "")
    if "filename=" in content_disposition:
        filename_out = content_disposition.split("filename=")[1].strip().strip('"')
    stats = {
        "original": resp.headers.get("X-Original-Bytes"),
        "processed": resp.headers.get("X-Processed-Bytes"),
        "seconds": resp.headers.get("X-Processing-Seconds"),
    }
    return resp.content, filename_out, stats


# ---------------------------------------------------------------------------
# App state & language
# ---------------------------------------------------------------------------

with st.spinner("…"):
    try:
        API_BASE = get_api_base()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

if "lang" not in st.session_state:
    st.session_state.lang = "en"
if "media" not in st.session_state:
    st.session_state.media = None
if "transcript" not in st.session_state:
    st.session_state.transcript = ""

lang = st.session_state.lang
_ = lambda key: t(key, lang)  # noqa: E731

st.markdown(
    """
    <style>
      .tiksafe-card { border: 1px solid rgba(128,128,128,.25); border-radius: 12px;
                      padding: 1rem 1.2rem; margin-bottom: 1rem; }
      .tiksafe-badge { display: inline-block; padding: .15rem .6rem; border-radius: 999px;
                       font-size: .8rem; font-weight: 600; }
      .badge-ok { background: #e6f4ea; color: #137333; }
      .badge-warn { background: #fef7e0; color: #b06000; }
      .badge-off { background: #f1f3f4; color: #5f6368; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(f"## 🎬 {_('app_title')}")
    st.caption(_("app_subtitle"))

    choice = st.radio(
        _("sidebar_language"),
        options=list(LANGUAGES.keys()),
        format_func=lambda code: LANGUAGES[code],
        index=list(LANGUAGES.keys()).index(lang),
    )
    if choice != lang:
        st.session_state.lang = choice
        st.rerun()
    lang = st.session_state.lang
    _ = lambda key: t(key, lang)  # noqa: E731

    health = api_health()
    ai_on = bool(health.get("ai"))
    badge = (
        f"<span class='tiksafe-badge badge-ok'>● {_('ai_on')}</span>"
        if ai_on
        else f"<span class='tiksafe-badge badge-off'>● {_('ai_off')}</span>"
    )
    st.markdown(f"**{_('sidebar_ai_status')}**<br>{badge}", unsafe_allow_html=True)
    if not ai_on:
        st.caption(_("ai_unavailable_hint"))

    with st.expander(f"⚖️ {_('legal_title')}"):
        st.write(_("legal_notice"))

    st.divider()
    st.caption(_("footer_note"))

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title(f"🎬 {_('app_title')}")
st.caption(_("app_subtitle"))

tab_analyze, tab_ai, tab_process = st.tabs(
    [_("nav_analyze"), _("nav_ai_toolkit"), _("nav_process")]
)

# ---------------------------------------------------------------------------
# Tab 1: Analyze + downloads
# ---------------------------------------------------------------------------

with tab_analyze:
    st.subheader(_("analyze_header"))
    st.write(_("analyze_caption"))

    url = st.text_input(_("url_label"), placeholder=_("url_placeholder"))

    if st.button(_("analyze_button"), type="primary"):
        if not url or not url.strip():
            st.warning(_("url_label") + " …")
        else:
            with st.spinner(_("analyzing")):
                try:
                    result = api_post("/api/analyze", {"url": url.strip()})
                    st.session_state.media = result["data"]
                    st.session_state.transcript = ""
                except APIError as exc:
                    st.session_state.media = None
                    st.error(f"**{_('analysis_failed')}:** {exc}")

    media = st.session_state.media
    if media:
        col_preview, col_info = st.columns([1, 2])
        with col_preview:
            if media.get("thumbnail"):
                st.image(media["thumbnail"], caption=_("video_preview"),
                         use_container_width=True)
        with col_info:
            st.markdown(f"### {media.get('title') or 'TikTok video'}")
            author = media.get("author")
            if author:
                st.write(f"👤 **{_('creator')}:** {author}")
            meta_bits = []
            if media.get("duration"):
                meta_bits.append(f"⏱️ {_('duration')}: {media['duration']:.0f}s")
            if media.get("view_count"):
                meta_bits.append(f"👁️ {_('views')}: {media['view_count']:,}")
            if media.get("like_count"):
                meta_bits.append(f"❤️ {_('likes')}: {media['like_count']:,}")
            if media.get("upload_date"):
                meta_bits.append(f"📅 {_('uploaded')}: {media['upload_date']}")
            if meta_bits:
                st.write(" · ".join(meta_bits))
            if media.get("description"):
                with st.expander(_("description")):
                    st.write(media["description"])

        formats = media.get("available_formats") or []
        if formats:
            with st.expander(f"🎞️ {_('formats_header')} ({len(formats)})"):
                for fmt in formats:
                    st.write(
                        f"`{fmt['format_id']}` · {fmt['ext']} · "
                        f"{fmt.get('resolution') or '?'} · {fmt.get('filesize_human')}"
                    )

        st.markdown(f"#### ⬇️ {_('download_card_header')}")
        dcol1, dcol2, dcol3 = st.columns(3)
        with dcol1:
            if st.button(f"🎬 {_('dl_video')}", use_container_width=True):
                with st.spinner(_("preparing")):
                    try:
                        data, filename = api_download(
                            "/api/download",
                            {"url": media["webpage_url"], "format_id": "best"},
                        )
                        st.download_button(
                            label=f"💾 {filename}", data=data,
                            file_name=filename, mime="video/mp4",
                            use_container_width=True,
                        )
                    except APIError as exc:
                        st.error(str(exc))
        with dcol2:
            if st.button(f"🎵 {_('dl_audio')}", use_container_width=True):
                with st.spinner(_("preparing")):
                    try:
                        data, filename = api_download(
                            "/api/audio",
                            {"url": media["webpage_url"], "bitrate": "128k"},
                        )
                        st.download_button(
                            label=f"💾 {filename}", data=data,
                            file_name=filename, mime="audio/mpeg",
                            use_container_width=True,
                        )
                    except APIError as exc:
                        st.error(str(exc))
        with dcol3:
            if st.button(f"🖼️ {_('dl_thumbnail')}", use_container_width=True):
                with st.spinner(_("preparing")):
                    try:
                        data, filename = api_download(
                            "/api/thumbnail", {"url": media["webpage_url"]}
                        )
                        st.download_button(
                            label=f"💾 {filename}", data=data,
                            file_name=filename, mime="image/jpeg",
                            use_container_width=True,
                        )
                    except APIError as exc:
                        st.error(str(exc))
    else:
        st.info(_("no_media"))

# ---------------------------------------------------------------------------
# Tab 2: AI toolkit
# ---------------------------------------------------------------------------

with tab_ai:
    st.subheader(_("ai_header"))
    if not api_health().get("ai"):
        st.warning(f"{_('ai_off')} {_('ai_unavailable_hint')}")
    else:
        default_topic = ""
        if st.session_state.media:
            default_topic = st.session_state.media.get("title") or ""

        card_caption, card_tags = st.columns(2)

        with card_caption:
            with st.container(border=True):
                st.markdown(f"#### 🎯 {_('ai_caption')}")
                topic = st.text_input(
                    _("topic_label"), value=default_topic, key="cap_topic"
                )
                styles = st.multiselect(
                    _("styles_label"),
                    options=["professional", "viral", "storytelling",
                             "short", "emotional", "educational"],
                    default=["professional", "viral", "short"],
                    key="cap_styles",
                )
                if st.button(_("generate"), key="cap_go"):
                    if not topic.strip():
                        st.warning(_("topic_label"))
                    else:
                        with st.spinner(_("generate") + "…"):
                            try:
                                result = api_post(
                                    "/api/caption",
                                    {"topic": topic.strip(), "language": lang,
                                     "styles": styles or None},
                                )
                                for style, caption_text in result["captions"].items():
                                    st.markdown(f"**{style}**")
                                    st.code(caption_text, language=None)
                            except APIError as exc:
                                st.error(str(exc))

        with card_tags:
            with st.container(border=True):
                st.markdown(f"#### #️⃣ {_('ai_hashtags')}")
                topic_tags = st.text_input(
                    _("topic_label"), value=default_topic, key="tag_topic"
                )
                if st.button(_("generate"), key="tag_go"):
                    if not topic_tags.strip():
                        st.warning(_("topic_label"))
                    else:
                        with st.spinner(_("generate") + "…"):
                            try:
                                result = api_post(
                                    "/api/hashtags",
                                    {"topic": topic_tags.strip(), "language": lang},
                                )
                                cols = st.columns(3)
                                for col, (label, tags) in zip(
                                    cols,
                                    [(_("hashtags_primary"), result["primary"]),
                                     (_("hashtags_niche"), result["niche"]),
                                     (_("hashtags_broad"), result["broad"])],
                                ):
                                    with col:
                                        st.markdown(f"**{label}**")
                                        st.code(
                                            " ".join(tags) or "—", language=None
                                        )
                            except APIError as exc:
                                st.error(str(exc))

        card_transcribe, card_summarize = st.columns(2)

        with card_transcribe:
            with st.container(border=True):
                st.markdown(f"#### 🎙️ {_('ai_transcribe')}")
                st.caption(_("transcript_hint"))
                if st.button(_("transcribe_button"), key="tr_go"):
                    if not st.session_state.media:
                        st.warning(_("no_media"))
                    else:
                        with st.spinner(_("transcribing")):
                            try:
                                result = api_post(
                                    "/api/transcribe",
                                    {"url": st.session_state.media["webpage_url"]},
                                    timeout=900,
                                )
                                st.session_state.transcript = result["text"]
                            except APIError as exc:
                                st.error(str(exc))
                transcript_text = st.text_area(
                    _("transcript_label"),
                    value=st.session_state.transcript,
                    height=180,
                    key="tr_text",
                )
                st.session_state.transcript = transcript_text
                if transcript_text.strip():
                    st.download_button(
                        f"⬇️ {_('download_txt')}",
                        data=transcript_text,
                        file_name="transcript.txt",
                        mime="text/plain",
                    )

        with card_summarize:
            with st.container(border=True):
                st.markdown(f"#### 📝 {_('ai_summarize')}")
                summary_source = st.text_area(
                    _("transcript_label"),
                    value=st.session_state.transcript,
                    height=120,
                    key="sum_text",
                    placeholder=_("transcript_hint"),
                )
                if st.button(_("summarize_button"), key="sum_go"):
                    if not summary_source.strip():
                        st.warning(_("transcript_label"))
                    else:
                        with st.spinner(_("summarizing")):
                            try:
                                result = api_post(
                                    "/api/summarize",
                                    {"text": summary_source.strip(),
                                     "language": lang},
                                )
                                st.markdown(f"**{_('summary_label')}**")
                                st.write(result["summary"])
                                if result.get("key_points"):
                                    st.markdown(f"**{_('key_points')}**")
                                    for point in result["key_points"]:
                                        st.write(f"• {point}")
                                tag_cols = st.columns(2)
                                with tag_cols[0]:
                                    if result.get("topics"):
                                        st.markdown(f"**{_('topics')}**")
                                        st.write(", ".join(result["topics"]))
                                with tag_cols[1]:
                                    if result.get("keywords"):
                                        st.markdown(f"**{_('keywords')}**")
                                        st.write(", ".join(result["keywords"]))
                                st.caption(f"⚠️ {_('ai_disclaimer')}")
                            except APIError as exc:
                                st.error(str(exc))

        with st.container(border=True):
            st.markdown(f"#### 🌐 {_('ai_translate')}")
            tcol1, tcol2 = st.columns([3, 1])
            with tcol1:
                translate_input = st.text_area(
                    _("translate_label"), height=100, key="trl_text"
                )
            with tcol2:
                target = st.selectbox(
                    _("target_label"),
                    options=list(LANGUAGES.keys()),
                    format_func=lambda code: LANGUAGES[code],
                    key="trl_target",
                )
                if st.button(_("translate_button"), key="trl_go"):
                    if not translate_input.strip():
                        st.warning(_("translate_label"))
                    else:
                        with st.spinner(_("translating")):
                            try:
                                result = api_post(
                                    "/api/translate",
                                    {"text": translate_input.strip(),
                                     "target": target},
                                )
                                st.code(result["translated"], language=None)
                            except APIError as exc:
                                st.error(str(exc))

# ---------------------------------------------------------------------------
# Tab 3: Video processing (user uploads only)
# ---------------------------------------------------------------------------

with tab_process:
    st.subheader(_("process_header"))
    st.write(_("process_caption"))

    uploaded = st.file_uploader(_("upload_label"), type=["mp4", "mov", "mkv", "webm"])
    if uploaded is not None:
        op_labels = {
            "trim": _("op_trim"), "crop": _("op_crop"),
            "resize": _("op_resize"), "compress": _("op_compress"),
            "convert": _("op_convert"), "audio": _("op_audio"),
            "thumbnail": _("op_thumbnail"), "subtitles": _("op_subtitles"),
        }
        op_key = st.selectbox(
            _("operation_label"),
            options=list(op_labels.keys()),
            format_func=lambda k: op_labels[k],
        )
        fields: dict = {"operation": op_key}

        if op_key == "trim":
            c1, c2 = st.columns(2)
            with c1:
                fields["start"] = st.number_input(
                    _("start_label"), min_value=0.0, value=0.0, step=1.0
                )
            with c2:
                end_val = st.number_input(
                    _("end_label"), min_value=0.0, value=0.0, step=1.0
                )
                if end_val > 0:
                    fields["end"] = end_val
        elif op_key == "crop":
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                fields["width"] = st.number_input(_("width_label"), value=640, step=2)
            with c2:
                fields["height"] = st.number_input(_("height_label"), value=640, step=2)
            with c3:
                fields["x"] = st.number_input(_("x_label"), value=0, step=2)
            with c4:
                fields["y"] = st.number_input(_("y_label"), value=0, step=2)
        elif op_key == "resize":
            c1, c2 = st.columns(2)
            with c1:
                fields["width"] = st.number_input(_("width_label"), value=720, step=2)
            with c2:
                fields["height"] = st.number_input(
                    _("height_label"), value=-1, step=2,
                    help="-1 keeps the aspect ratio",
                )
        elif op_key == "compress":
            fields["crf"] = st.slider(_("crf_label"), 18, 40, 28)
        elif op_key == "thumbnail":
            fields["timestamp"] = st.text_input(_("timestamp_label"), value="00:00:01")

        if st.button(_("process_button"), type="primary"):
            with st.spinner(_("processing")):
                try:
                    data, filename, stats = api_upload_process(
                        uploaded.getvalue(), uploaded.name,
                        uploaded.type or "video/mp4", fields,
                    )
                    orig = (
                        f"{int(stats['original']) / 1_048_576:.1f} MB"
                        if stats.get("original") else "?"
                    )
                    proc_size = (
                        f"{int(stats['processed']) / 1_048_576:.1f} MB"
                        if stats.get("processed") else "?"
                    )
                    secs = stats.get("seconds") or "?"
                    m1, m2, m3 = st.columns(3)
                    m1.metric(_("original_size"), orig)
                    m2.metric(_("processed_size"), proc_size)
                    m3.metric(_("processing_time"), f"{secs}s")
                    mime = "video/mp4"
                    if filename.endswith(".mp3"):
                        mime = "audio/mpeg"
                    elif filename.endswith(".jpg"):
                        mime = "image/jpeg"
                    elif filename.endswith(".srt"):
                        mime = "text/plain"
                    st.download_button(
                        f"⬇️ {_('download_processed')}", data=data,
                        file_name=filename, mime=mime,
                        use_container_width=True,
                    )
                except APIError as exc:
                    st.error(str(exc))
