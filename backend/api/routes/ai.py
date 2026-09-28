"""AI toolkit endpoints: caption, hashtags, transcribe, summarize, translate."""

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ...core.security import remove_path
from ...schemas.ai import (
    CaptionRequest,
    CaptionResponse,
    HashtagRequest,
    HashtagResponse,
    SummarizeRequest,
    SummarizeResponse,
    TranscriptSegment,
    TranscribeRequest,
    TranscribeResponse,
    TranslateRequest,
    TranslateResponse,
)
from ...services import ai_service, downloader, transcription

router = APIRouter()


@router.post("/caption", response_model=CaptionResponse, summary="Generate captions")
async def create_caption(payload: CaptionRequest) -> CaptionResponse:
    captions = await ai_service.generate_captions(
        payload.topic, payload.language, payload.styles
    )
    return CaptionResponse(ok=True, captions=captions)


@router.post("/hashtags", response_model=HashtagResponse, summary="Generate hashtags")
async def create_hashtags(payload: HashtagRequest) -> HashtagResponse:
    tags = await ai_service.generate_hashtags(payload.topic, payload.language)
    return HashtagResponse(ok=True, **tags)


@router.post("/transcribe", response_model=TranscribeResponse, summary="Transcribe audio")
def transcribe_video(payload: TranscribeRequest) -> TranscribeResponse:
    work_dir = None
    try:
        audio_path, work_dir, _meta = downloader.download_audio(payload.url)
        text, segments = transcription.transcribe_audio(
            audio_path, payload.language
        )
    finally:
        if work_dir is not None:
            remove_path(work_dir)
    return TranscribeResponse(
        ok=True,
        text=text,
        segments=[TranscriptSegment(**seg) for seg in segments],
        language=payload.language,
    )


@router.post("/summarize", response_model=SummarizeResponse, summary="Summarize transcript")
async def summarize(payload: SummarizeRequest) -> SummarizeResponse:
    text = (payload.text or "").strip()
    if not text and payload.url:
        work_dir = None
        try:
            audio_path, work_dir, _meta = await run_in_threadpool(
                downloader.download_audio, payload.url
            )
            text, _segments = await run_in_threadpool(
                transcription.transcribe_audio, audio_path, payload.language
            )
        finally:
            if work_dir is not None:
                remove_path(work_dir)
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Provide transcript text or a video URL to summarize.",
        )
    result = await ai_service.summarize_text(text, payload.language)
    return SummarizeResponse(ok=True, **result)


@router.post("/translate", response_model=TranslateResponse, summary="Translate text")
async def translate(payload: TranslateRequest) -> TranslateResponse:
    translated = await ai_service.translate_text(payload.text, payload.target)
    return TranslateResponse(ok=True, translated=translated, target=payload.target)
