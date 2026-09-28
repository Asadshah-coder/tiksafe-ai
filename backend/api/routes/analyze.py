"""POST /api/analyze — validate a TikTok URL and extract public metadata."""

from fastapi import APIRouter

from ...schemas.media import AnalyzeRequest, AnalyzeResponse
from ...services.extractor import extract_metadata

router = APIRouter()


@router.post("", response_model=AnalyzeResponse, summary="Analyze a TikTok video URL")
def analyze_video(payload: AnalyzeRequest) -> AnalyzeResponse:
    info = extract_metadata(payload.url)
    return AnalyzeResponse(ok=True, data=info)
