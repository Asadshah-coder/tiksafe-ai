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
    page_title="TikSave AI — TikTok Video Toolkit",
    page_icon="🎬",
    layout="wide",
)

THEME_CSS = PROJECT_ROOT / "frontend" / "assets" / "theme.css"
if THEME_CSS.exists():
    st.markdown(
        f"<style>{THEME_CSS.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
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


def _filename_from_headers(resp: httpx.Response, default: str) -> str:
    content_disposition = resp.headers.get("content-disposition", "")
    if "filename=" in content_disposition:
        return content_disposition.split("filename=")[1].strip().strip('"')
    return default


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
    stats = {
        "original": resp.headers.get("X-Original-Bytes"),
        "processed": resp.headers.get("X-Processed-Bytes"),
        "seconds": resp.headers.get("X-Processing-Seconds"),
    }
    return resp.content, _filename_from_headers(resp, "processed"), stats


def api_upload_info(file_bytes: bytes, filename: str, mime: str) -> dict:
    try:
        resp = httpx.post(
            f"{API_BASE}/api/video-info",
            files={"file": (filename, file_bytes, mime)},
            timeout=120,
        )
    except httpx.HTTPError as exc:
        raise APIError(f"Could not reach the API server: {exc}") from exc
    if resp.status_code != 200:
        raise APIError(_api_error_message(resp))
    return resp.json()["info"]


# ---------------------------------------------------------------------------
# App state & language
# ---------------------------------------------------------------------------

with st.spinner("…"):
    try:
        API_BASE = get_api_base()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

for key, default in [
    ("lang", "en"), ("media", None), ("transcript", ""),
    ("nav", "home"), ("dl_count", 0), ("proc_count", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default

lang = st.session_state.lang
_ = lambda key: t(key, lang)  # noqa: E731

# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------


def ad_slot() -> None:
    """Honest placeholder where the owner's AdSense unit will go."""
    st.markdown(
        f"<div class='ts-ad-slot'>{_('ad_label')}</div>",
        unsafe_allow_html=True,
    )


def bump(counter: str) -> None:
    st.session_state[counter] = st.session_state.get(counter, 0) + 1


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

NAV_OPTIONS = ["home", "ai", "process", "about", "policies", "contact"]

with st.sidebar:
    st.markdown("## 🎬 TikSave AI")
    st.caption(_("app_subtitle"))

    nav = st.radio(
        _("nav_label"),
        options=NAV_OPTIONS,
        format_func=lambda k: _(f"nav_{k}"),
        index=NAV_OPTIONS.index(st.session_state.nav),
        key="nav_radio",
    )
    if nav != st.session_state.nav:
        st.session_state.nav = nav
        st.rerun()

    st.divider()
    choice = st.radio(
        _("sidebar_language"),
        options=list(LANGUAGES.keys()),
        format_func=lambda code: LANGUAGES[code],
        index=list(LANGUAGES.keys()).index(lang),
        key="lang_radio",
    )
    if choice != lang:
        st.session_state.lang = choice
        st.rerun()
    lang = st.session_state.lang
    _ = lambda key: t(key, lang)  # noqa: E731

    health = api_health()
    ai_on = bool(health.get("ai"))
    badge_cls = "badge-ok" if ai_on else "badge-off"
    badge_txt = _("ai_on") if ai_on else _("ai_off")
    st.markdown(
        f"**{_('sidebar_ai_status')}**<br>"
        f"<span class='tiksafe-badge {badge_cls}'>● {badge_txt}</span>",
        unsafe_allow_html=True,
    )
    if not ai_on:
        st.caption(_("ai_unavailable_hint"))

    with st.expander(f"⚖️ {_('legal_title')}"):
        st.write(_("legal_notice"))

# ---------------------------------------------------------------------------
# Page: Home
# ---------------------------------------------------------------------------


def render_home() -> None:
    st.markdown(
        f"""
        <div class="ts-hero">
          <span class="ts-hero-badge">{_('hero_badge')}</span>
          <h1>{_('hero_title')}</h1>
          <p>{_('hero_sub')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="ts-stats">
          <span class="ts-stat"><b>{st.session_state.dl_count + st.session_state.proc_count}</b>{_('stat_session')}</span>
          <span class="ts-stat"><b>10</b>{_('stat_tools')}</span>
          <span class="ts-stat"><b>3</b>{_('stat_langs')}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 🔗")
    url = st.text_input(_("url_label"), placeholder=_("url_placeholder"),
                        label_visibility="collapsed")
    if st.button(_("analyze_button"), type="primary", use_container_width=True):
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
        quality = st.selectbox(
            _("quality_label"),
            options=["best", "high", "medium", "low"],
            format_func=lambda q: _(f"q_{q}"),
        )
        dcol1, dcol2, dcol3 = st.columns(3)
        with dcol1:
            if st.button(f"🎬 {_('dl_video')}", use_container_width=True):
                with st.spinner(_("preparing")):
                    try:
                        data, filename = api_download(
                            "/api/download",
                            {"url": media["webpage_url"], "quality": quality},
                        )
                        bump("dl_count")
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
                        bump("dl_count")
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
                        bump("dl_count")
                        st.download_button(
                            label=f"💾 {filename}", data=data,
                            file_name=filename, mime="image/jpeg",
                            use_container_width=True,
                        )
                    except APIError as exc:
                        st.error(str(exc))
    else:
        st.info(_("no_media"))

    ad_slot()

    st.markdown(f"### {_('how_title')}")
    s1, s2, s3 = st.columns(3)
    for col, num, title, desc in [
        (s1, "1", _("how_s1t"), _("how_s1d")),
        (s2, "2", _("how_s2t"), _("how_s2d")),
        (s3, "3", _("how_s3t"), _("how_s3d")),
    ]:
        with col:
            st.markdown(
                f"<div class='ts-card'><span class='ts-step-num'>{num}</span>"
                f"<h4>{title}</h4><p>{desc}</p></div>",
                unsafe_allow_html=True,
            )

    st.markdown(f"### {_('feat_title')}")
    feats = [
        ("⬇️", _("feat1t"), _("feat1d")),
        ("🎵", _("feat2t"), _("feat2d")),
        ("✂️", _("feat3t"), _("feat3d")),
        ("🤖", _("feat4t"), _("feat4d")),
        ("🎙️", _("feat5t"), _("feat5d")),
        ("🌐", _("feat6t"), _("feat6d")),
    ]
    for row in range(2):
        cols = st.columns(3)
        for col, (icon, title, desc) in zip(cols, feats[row * 3:(row + 1) * 3]):
            with col:
                st.markdown(
                    f"<div class='ts-card'><h4>{icon} {title}</h4><p>{desc}</p></div>",
                    unsafe_allow_html=True,
                )

    st.markdown(f"### ❓ {_('faq_title')}")
    for i in range(1, 5):
        with st.expander(_(f"faq{i}q")):
            st.write(_(f"faq{i}a"))


# ---------------------------------------------------------------------------
# Page: AI toolkit
# ---------------------------------------------------------------------------


def render_ai() -> None:
    st.markdown(f"## 🤖 {_('ai_header')}")
    ai_on = bool(api_health().get("ai"))
    if not ai_on:
        st.warning(f"{_('ai_off')} {_('ai_unavailable_hint')}")

    # Offline keyword helper — always available, honestly labeled.
    with st.container(border=True):
        st.markdown(f"#### ⚡ {_('kw_title')}")
        st.caption(_("kw_sub"))
        kw_input = st.text_area(_("kw_input"), height=100, key="kw_text")
        if st.button(_("kw_button"), key="kw_go"):
            if not kw_input.strip():
                st.warning(_("kw_input"))
            else:
                try:
                    result = api_post(
                        "/api/keywords",
                        {"text": kw_input.strip(), "max_keywords": 12},
                    )
                    k1, k2 = st.columns(2)
                    with k1:
                        st.markdown(f"**{_('kw_keywords')}**")
                        st.code(", ".join(result["keywords"]) or "—", language=None)
                    with k2:
                        st.markdown(f"**{_('kw_hashtags')}**")
                        st.code(" ".join(result["hashtags"]) or "—", language=None)
                    st.caption(f"ℹ️ {_('kw_note')}")
                except APIError as exc:
                    st.error(str(exc))

    if not ai_on:
        st.stop()

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
                                    st.code(" ".join(tags) or "—", language=None)
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
# Page: Clean Export (user uploads only)
# ---------------------------------------------------------------------------


def render_process() -> None:
    st.markdown(f"## 🎬 {_('process_header')}")
    st.write(_("process_caption"))

    uploaded = st.file_uploader(
        _("upload_label"), type=["mp4", "mov", "mkv", "webm", "avi"]
    )
    if uploaded is None:
        st.info(_("upload_label"))
        return

    with st.container(border=True):
        st.markdown(f"#### 🔍 {_('inspector_title')}")
        st.caption(_("inspector_sub"))
        if st.button(_("inspector_btn"), key="inspect_go"):
            with st.spinner(_("analyzing")):
                try:
                    info = api_upload_info(
                        uploaded.getvalue(), uploaded.name,
                        uploaded.type or "video/mp4",
                    )
                    v, a = info.get("video"), info.get("audio")
                    cols = st.columns(4)
                    dur = info.get("duration_seconds")
                    cols[0].metric(
                        _("duration"), f"{dur:.1f}s" if dur else "—"
                    )
                    if v and v.get("width"):
                        cols[1].metric(
                            _("resolution"), f"{v['width']}×{v['height']}"
                        )
                    else:
                        cols[1].metric(_("resolution"), "—")
                    cols[2].metric(_("codec"), (v or {}).get("codec") or "—")
                    size_b = info.get("size_bytes")
                    cols[3].metric(
                        _("size_label"),
                        f"{size_b / 1_048_576:.1f} MB" if size_b else "—",
                    )
                    extra = []
                    if v and v.get("fps"):
                        extra.append(f"🎞️ {v['fps']} fps")
                    br = info.get("bitrate_kbps")
                    if br:
                        extra.append(f"📶 {br} kbps")
                    if a and a.get("codec"):
                        extra.append(
                            f"🔊 {a['codec']} {a.get('channels') or ''}ch".strip()
                        )
                    else:
                        extra.append(f"🔇 {_('inspector_none')}")
                    st.write(" · ".join(extra))
                except APIError as exc:
                    st.error(str(exc))

    op_labels = {
        "trim": _("op_trim"), "crop": _("op_crop"),
        "resize": _("op_resize"), "compress": _("op_compress"),
        "convert": _("op_convert"), "audio": _("op_audio"),
        "thumbnail": _("op_thumbnail"), "subtitles": _("op_subtitles"),
        "gif": _("op_gif"), "mute": _("op_mute"),
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
                bump("proc_count")
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
                elif filename.endswith((".jpg", ".jpeg")):
                    mime = "image/jpeg"
                elif filename.endswith(".srt"):
                    mime = "text/plain"
                elif filename.endswith(".gif"):
                    mime = "image/gif"
                st.download_button(
                    f"⬇️ {_('download_processed')}", data=data,
                    file_name=filename, mime=mime,
                    use_container_width=True,
                )
            except APIError as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# Page: About / Policies / Contact
# ---------------------------------------------------------------------------


def render_about() -> None:
    st.markdown(f"## ℹ️ {_('nav_about')}")
    st.markdown(f"### {_('about_title')}")
    st.write(_("about_body"))
    st.markdown(
        f"<div class='ts-card'><h4>{_('about_built_h')}</h4><p>{_('about_built')}</p></div>",
        unsafe_allow_html=True,
    )
    ad_slot()


def render_policies() -> None:
    st.markdown(f"## 📜 {_('nav_policies')}")
    tab_p, tab_t, tab_d = st.tabs(
        [_("tab_privacy"), _("tab_terms"), _("tab_dmca")]
    )
    with tab_p:
        st.markdown(f"### {_('tab_privacy')}")
        st.write(_("privacy_body"))
    with tab_t:
        st.markdown(f"### {_('tab_terms')}")
        st.write(_("terms_body"))
    with tab_d:
        st.markdown(f"### {_('tab_dmca')}")
        st.write(_("dmca_body"))


def render_contact() -> None:
    st.markdown(f"## ✉️ {_('nav_contact')}")
    st.write(_("contact_sub"))
    st.markdown(
        f"<div class='ts-card'><h4>📧 {_('contact_email')}</h4>"
        f"<p><a href='mailto:asad.aiworks@gmail.com'>asad.aiworks@gmail.com</a></p></div>",
        unsafe_allow_html=True,
    )
    ad_slot()


# ---------------------------------------------------------------------------
# Router + footer
# ---------------------------------------------------------------------------

page = st.session_state.nav
if page == "home":
    render_home()
elif page == "ai":
    render_ai()
elif page == "process":
    render_process()
elif page == "about":
    render_about()
elif page == "policies":
    render_policies()
elif page == "contact":
    render_contact()

st.markdown(
    f"""
    <div class="ts-footer">
      <div class="ts-brand">🎬 TikSave AI <span class="x">×</span> Asad Bukhari <span class="x">×</span> Muse AI</div>
      <div class="ts-muted">{_('footer_note')}</div>
      <div class="ts-muted">{_('legal_notice')}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
