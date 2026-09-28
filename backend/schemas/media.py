"""Pydantic schemas for media analysis and download endpoints."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048, description="TikTok video URL")


class FormatOption(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str] = None
    filesize: Optional[int] = None
    filesize_human: str = "unknown"
    note: Optional[str] = None
    has_video: bool = True
    has_audio: bool = True


class MediaInfo(BaseModel):
    status: Literal["success"] = "success"
    title: str
    author: Optional[str] = None
    author_id: Optional[str] = None
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    webpage_url: str
    upload_date: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    description: Optional[str] = None
    available_formats: list[FormatOption] = []


class AnalyzeResponse(BaseModel):
    ok: bool = True
    data: MediaInfo


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    format_id: Optional[str] = Field(
        default="best", max_length=64, description="yt-dlp format selector"
    )
    quality: str = Field(
        default="best",
        description="Quality preset: best, high (1080p), medium (720p), low (480p)",
    )

    @field_validator("quality")
    @classmethod
    def _validate_quality(cls, value: str) -> str:
        value = (value or "best").strip().lower()
        if value not in {"best", "high", "medium", "low"}:
            raise ValueError("quality must be best, high, medium, or low")
        return value


class AudioRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    bitrate: str = Field(default="128k", pattern=r"^\d{2,3}k$")


class ThumbnailRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str
    code: str
    detail: Optional[str] = None
